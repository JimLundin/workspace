"""Bounded, local Notification Center reads and explicit individual dismissal."""
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false

import asyncio
import queue
import threading
from contextlib import suppress
from dataclasses import replace
from itertools import islice

from assistant.system_notices import Access, Banners, Notice, NoticeKey, Observation, Observed, Unavailable, creation_time

from .notification_banners import BannerPolicy


async def read() -> Observation:
    from win32more.Windows.UI.Notifications import NotificationKinds  # noqa: PLC0415
    from win32more.Windows.UI.Notifications.Management import UserNotificationListener, UserNotificationListenerAccessStatus  # noqa: PLC0415

    listener = UserNotificationListener.get_Current()
    if listener.GetAccessStatus() != UserNotificationListenerAccessStatus.Allowed:
        return Unavailable(Access.DENIED)
    rows = await asyncio.wait_for(listener.GetNotificationsAsync(NotificationKinds.Toast), 3)
    found: list[Notice] = []
    for index, row in enumerate(rows):
        if index >= 256:
            break
        try:
            binding = row.Notification.Visual.GetBinding('ToastGeneric')
            if not binding:
                continue
            texts = tuple(str(text.Text).strip()[:4096] for text in islice(binding.GetTextElements(), 16))
            if not texts or not any(texts):
                continue
            identity, created = int(row.Id), creation_time(row.CreationTime)
            if identity < 0 or created < 0:
                continue
            info = row.AppInfo
            found.append(Notice(NoticeKey(identity, created), str(info.AppUserModelId)[:512],
                                str(info.DisplayInfo.DisplayName)[:256], texts[0][:512], '\n'.join(texts[1:])[:8192]))
        except OSError:
            continue  # The source can disappear between enumeration and reading.
    return Observed(tuple(sorted(found, key=lambda notice: notice.key.created, reverse=True)))


class NotificationObserver:
    """WinRT lives on one MTA worker; no notification content is logged or saved."""

    __slots__ = ('banner_policy', 'dismissals', 'results', 'stopped', 'thread')

    def __init__(self) -> None:
        self.results: queue.Queue[Observation] = queue.Queue(maxsize=1)
        self.banner_policy = BannerPolicy()
        self.dismissals: queue.Queue[NoticeKey] = queue.Queue(maxsize=64)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, name='Windows notifications', daemon=True)
        self.thread.start()

    def publish(self, value: Observation) -> None:
        with suppress(queue.Empty):
            self.results.get_nowait()
        self.results.put_nowait(value)

    def dismiss(self, key: NoticeKey) -> None:
        with suppress(queue.Full):
            self.dismissals.put_nowait(key)

    def run(self) -> None:
        from win32more import FAILED  # noqa: PLC0415
        from win32more.Windows.UI.Notifications.Management import UserNotificationListener  # noqa: PLC0415
        from win32more.Windows.Win32.System.WinRT import RO_INIT_MULTITHREADED, RoInitialize, RoUninitialize  # noqa: PLC0415

        if FAILED(RoInitialize(RO_INIT_MULTITHREADED)):
            self.publish(Unavailable(Access.UNAVAILABLE))
            return
        try:
            with asyncio.Runner() as runner:
                failures = 0
                while not self.stopped.is_set():
                    try:
                        listener = UserNotificationListener.get_Current()
                        while not self.dismissals.empty():
                            key = self.dismissals.get_nowait()
                            with suppress(OSError):
                                source = listener.GetNotification(key.identity)
                                if source and creation_time(source.CreationTime) == key.created:
                                    listener.RemoveNotification(key.identity)
                        observation = runner.run(read())
                        if isinstance(observation, Observed):
                            failures = 0
                            try:
                                coverage = self.banner_policy.sync()
                                observation = replace(observation, banners=Banners.PARTIAL if coverage.unavailable else Banners.SUPPRESSED)
                            except OSError:
                                observation = replace(observation, banners=Banners.PARTIAL)
                        else:
                            failures += 1
                            if observation.access is Access.DENIED or failures >= 3:
                                self.banner_policy.close()
                        self.publish(observation)
                    except (OSError, TimeoutError):
                        failures += 1
                        if failures >= 3:
                            with suppress(OSError):
                                self.banner_policy.close()
                        self.publish(Unavailable(Access.UNAVAILABLE))
                    if self.stopped.wait(1):
                        break

        finally:
            try:
                self.banner_policy.close()
            finally:
                RoUninitialize()

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=4)
