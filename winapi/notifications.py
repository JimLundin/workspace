"""Bounded, local Notification Center reads and explicit individual dismissal."""

import queue
import threading
import time
from contextlib import suppress
from dataclasses import replace
from itertools import islice
from typing import Protocol

lazy from win32more import FAILED
lazy from win32more.Windows.Foundation import AsyncStatus, IAsyncInfo
lazy from win32more.Windows.UI.Notifications import NotificationKinds
lazy from win32more.Windows.UI.Notifications.Management import UserNotificationListener, UserNotificationListenerAccessStatus
lazy from win32more.Windows.Win32.System.WinRT import RO_INIT_MULTITHREADED, RoInitialize, RoUninitialize

from winapi.notification_banners import BannerPolicy, Coverage
from winapi.system_notices import Access, Banners, Notice, NoticeKey, Observation, Observed, Unavailable, creation_time


class NotificationSource(Protocol):
    """The notification worker owns one source's apartment and observation lifetime."""

    def open(self) -> bool: ...
    def read(self, stopped: threading.Event) -> Observation: ...
    def dismiss(self, key: NoticeKey) -> None: ...
    def close(self) -> None: ...


class BannerLease(Protocol):
    def sync(self) -> Coverage: ...
    def close(self) -> None: ...


class NativeNotifications:
    __slots__ = ()

    def open(self) -> bool:
        return not FAILED(RoInitialize(RO_INIT_MULTITHREADED))

    def read(self, stopped: threading.Event) -> Observation:
        listener = UserNotificationListener.get_Current()
        if listener.GetAccessStatus() != UserNotificationListenerAccessStatus.Allowed:
            return Unavailable(Access.DENIED)
        # Poll instead of awaiting: win32more's awaitable completes a cancelled future when a timed-out read finishes.
        operation = listener.GetNotificationsAsync(NotificationKinds.Toast)
        info = operation.as_(IAsyncInfo)
        deadline = time.monotonic() + 3
        while info.Status == AsyncStatus.Started:
            if stopped.wait(0.05) or time.monotonic() >= deadline:
                info.Cancel()
                raise TimeoutError("Notification Center read did not finish")
        if info.Status != AsyncStatus.Completed:
            raise OSError("Notification Center read failed")
        rows = operation.GetResults()
        found: list[Notice] = []
        for index, row in enumerate(rows):
            if index >= 256:
                break
            try:
                binding = row.Notification.Visual.GetBinding("ToastGeneric")
                if not binding:
                    continue
                texts = tuple(str(text.Text).strip()[:4096] for text in islice(binding.GetTextElements(), 16))
                if not texts or not any(texts):
                    continue
                identity, created = int(row.Id), creation_time(row.CreationTime)
                if identity < 0 or created < 0:
                    continue
                info = row.AppInfo
                found.append(
                    Notice(
                        NoticeKey(identity, created),
                        str(info.AppUserModelId)[:512],
                        str(info.DisplayInfo.DisplayName)[:256],
                        texts[0][:512],
                        "\n".join(texts[1:])[:8192],
                    )
                )
            except OSError:
                continue  # The source can disappear between enumeration and reading.
        return Observed(tuple(sorted(found, key=notice_created, reverse=True)))

    def dismiss(self, key: NoticeKey) -> None:
        listener = UserNotificationListener.get_Current()
        source = listener.GetNotification(key.identity)
        if source and creation_time(source.CreationTime) == key.created:
            listener.RemoveNotification(key.identity)

    def close(self) -> None:
        RoUninitialize()


class NotificationObserver:
    """WinRT lives on one MTA worker; no notification content is logged or saved."""

    __slots__ = ("banner_policy", "dismissals", "results", "source", "stopped", "thread")

    def __init__(self, *, source: NotificationSource | None = None, banner_policy: BannerLease | None = None) -> None:
        self.results: queue.Queue[Observation] = queue.Queue(maxsize=1)
        self.source: NotificationSource = NativeNotifications() if source is None else source
        self.banner_policy: BannerLease = BannerPolicy() if banner_policy is None else banner_policy
        self.dismissals: queue.Queue[NoticeKey] = queue.Queue(maxsize=64)
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, name="Windows notifications", daemon=True)
        self.thread.start()

    def publish(self, value: Observation) -> None:
        with suppress(queue.Empty):
            self.results.get_nowait()
        self.results.put_nowait(value)

    def dismiss(self, key: NoticeKey) -> None:
        with suppress(queue.Full):
            self.dismissals.put_nowait(key)

    def run(self) -> None:
        if not self.source.open():
            self.publish(Unavailable(Access.UNAVAILABLE))
            return
        try:
            failures = 0
            while not self.stopped.is_set():
                try:
                    while not self.dismissals.empty():
                        key = self.dismissals.get_nowait()
                        with suppress(OSError):
                            self.source.dismiss(key)
                    observation = self.source.read(self.stopped)
                    match observation:
                        case Observed():
                            failures = 0
                            try:
                                coverage = self.banner_policy.sync()
                                observation = replace(observation, banners=Banners.PARTIAL if coverage.unavailable else Banners.SUPPRESSED)
                            except OSError:
                                observation = replace(observation, banners=Banners.PARTIAL)
                        case Unavailable(access=access):
                            failures += 1
                            if access is Access.DENIED or failures >= 3:
                                self.banner_policy.close()
                    self.publish(observation)
                except OSError, TimeoutError:
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
                self.source.close()

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=4)


def notice_created(notice: Notice) -> int:
    return notice.key.created
