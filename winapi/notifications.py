"""Bounded, local Notification Center reads and explicit individual dismissal."""

import os
import queue
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from itertools import islice
from pathlib import Path
from typing import Protocol

lazy from win32more import FAILED
lazy from win32more.Windows.Foundation import AsyncStatus, IAsyncInfo
lazy from win32more.Windows.UI.Notifications import NotificationKinds, UserNotification
lazy from win32more.Windows.UI.Notifications.Management import UserNotificationListener, UserNotificationListenerAccessStatus
lazy from win32more.Windows.Win32.System.WinRT import RO_INIT_MULTITHREADED, RoInitialize, RoUninitialize

from winapi.notification_banners import BannerPolicy, Coverage
from winapi.system_notices import Access, Banners, Notice, NoticeKey, Observation, Observed, Unavailable, creation_time


# Modification time and size of Windows' notification database files; None when they cannot be read.
type Stamp = tuple[tuple[int, int], ...] | None

DATABASE = ("wpndatabase.db", "wpndatabase.db-wal")


class NotificationSource(Protocol):
    """The notification worker owns one source's apartment and observation lifetime."""

    def open(self) -> bool: ...
    def stamp(self) -> Stamp: ...
    def read(self, stopped: threading.Event, known: Mapping[NoticeKey, Notice]) -> Observation: ...
    def dismiss(self, key: NoticeKey) -> None: ...
    def close(self) -> None: ...


class BannerLease(Protocol):
    def sync(self) -> Coverage: ...
    def close(self) -> None: ...


class NativeNotifications:
    """Windows offers change events only to packaged apps, so reads follow database writes instead."""

    __slots__ = ("store",)

    def __init__(self) -> None:
        local = os.environ.get("LOCALAPPDATA")
        self.store = None if local is None else Path(local) / "Microsoft" / "Windows" / "Notifications"

    def open(self) -> bool:
        return not FAILED(RoInitialize(RO_INIT_MULTITHREADED))

    def stamp(self) -> Stamp:
        """Stat costs microseconds; a full read costs ~0.2 s of CPU in this process for 50 notices."""
        if self.store is None:
            return None
        try:
            return tuple((status.st_mtime_ns, status.st_size) for status in (os.stat(self.store / name) for name in DATABASE))
        except OSError:
            return None

    def read(self, stopped: threading.Event, known: Mapping[NoticeKey, Notice]) -> Observation:
        """Reuse known notices: reading a row's content costs ~40 ms, mostly its app display name."""
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
        found: list[Notice] = []
        for row in islice(operation.GetResults(), 256):
            try:
                key = NoticeKey(int(row.Id), creation_time(row.CreationTime))
                notice = known.get(key) or read_notice(row, key)
            except OSError:
                continue  # The source can disappear between enumeration and reading.
            if notice is not None:
                found.append(notice)
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
            known: frozendict[NoticeKey, Notice] = frozendict()
            read_stamp: Stamp = None
            due = 0.0
            while not self.stopped.is_set():
                while not self.dismissals.empty():
                    with suppress(OSError):
                        self.source.dismiss(self.dismissals.get_nowait())
                stamp = self.source.stamp()
                if stamp != read_stamp or time.monotonic() >= due:
                    observation = self.observe(known, failures)
                    match observation:
                        case Observed(notices=notices):
                            failures, known = 0, frozendict((notice.key, notice) for notice in notices)
                        case Unavailable():
                            failures += 1
                    # A changed stamp triggers the next read; the timeout covers writes Windows leaves out of its database.
                    read_stamp, due = stamp, time.monotonic() + (30 if stamp is not None and not failures else 1)
                    self.publish(observation)
                if self.stopped.wait(0.25):
                    break
        finally:
            try:
                self.banner_policy.close()
            finally:
                self.source.close()

    def observe(self, known: Mapping[NoticeKey, Notice], failures: int) -> Observation:
        try:
            observation = self.source.read(self.stopped, known)
        except OSError, TimeoutError:
            observation = Unavailable(Access.UNAVAILABLE)
        match observation:
            case Observed():
                try:
                    coverage = self.banner_policy.sync()
                    return replace(observation, banners=Banners.PARTIAL if coverage.unavailable else Banners.SUPPRESSED)
                except OSError:
                    return replace(observation, banners=Banners.PARTIAL)
            case Unavailable(access=access):
                if access is Access.DENIED or failures + 1 >= 3:
                    with suppress(OSError):
                        self.banner_policy.close()
                return observation

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=4)


def read_notice(row: UserNotification, key: NoticeKey) -> Notice | None:
    if key.identity < 0 or key.created < 0:
        return None
    binding = row.Notification.Visual.GetBinding("ToastGeneric")
    if not binding:
        return None
    texts = tuple(str(text.Text).strip()[:4096] for text in islice(binding.GetTextElements(), 16))
    if not any(texts):
        return None
    app = row.AppInfo
    return Notice(key, str(app.AppUserModelId)[:512], str(app.DisplayInfo.DisplayName)[:256], texts[0][:512], "\n".join(texts[1:])[:8192])


def notice_created(notice: Notice) -> int:
    return notice.key.created
