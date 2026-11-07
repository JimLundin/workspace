"""Bounded, local Notification Center observations."""

import os
import queue
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
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


@dataclass(frozen=True, slots=True)
class FileStamp:
    """A file's modification time and size: a cheap sign that it changed."""

    modified_ns: int
    size: int


type Stamp = tuple[FileStamp, ...] | None
"""Each of Windows' notification database files' stamps; None when they cannot be read."""

DATABASE = ("wpndatabase.db", "wpndatabase.db-wal")


class NotificationSource(Protocol):
    """The notification worker owns one source's apartment and observation lifetime."""

    def open(self) -> bool: ...
    def stamp(self) -> Stamp: ...
    def read(self, stopped: threading.Event, known: Mapping[NoticeKey, Notice]) -> Observation: ...
    def close(self) -> None: ...


class BannerLease(Protocol):
    def sync(self) -> Coverage: ...
    def close(self) -> None: ...


def _notification_store() -> Path | None:
    local = os.environ.get("LOCALAPPDATA")
    return None if local is None else Path(local) / "Microsoft" / "Windows" / "Notifications"


@dataclass(frozen=True, slots=True)
class NativeNotifications:
    """Windows offers change events only to packaged apps, so reads follow database writes instead."""

    store: Path | None = field(default_factory=_notification_store)

    def open(self) -> bool:
        return not FAILED(RoInitialize(RO_INIT_MULTITHREADED))

    def stamp(self) -> Stamp:
        """Stat costs microseconds; a full read costs ~0.2 s of CPU in this process for 50 notices."""
        if self.store is None:
            return None
        try:
            return tuple(FileStamp(status.st_mtime_ns, status.st_size) for status in (os.stat(self.store / name) for name in DATABASE))
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
        found = (notice for row in islice(operation.GetResults(), 256) if (notice := _known_or_read(row, known)) is not None)
        return Observed(tuple(sorted(found, key=notice_created, reverse=True)))

    def close(self) -> None:
        RoUninitialize()


@dataclass(frozen=True, slots=True)
class NotificationObserver:
    """WinRT lives on one MTA worker; no notification content is logged or saved."""

    source: NotificationSource = field(kw_only=True)
    banner_policy: BannerLease = field(kw_only=True)
    results: queue.Queue[Observation] = field(default_factory=lambda: queue.Queue[Observation](maxsize=1), kw_only=True)
    stopped: threading.Event = field(default_factory=threading.Event, kw_only=True)
    finished: threading.Event = field(default_factory=threading.Event, kw_only=True)
    """Set when the worker thread exits."""

    @classmethod
    def start(cls, *, source: NotificationSource | None = None, banner_policy: BannerLease | None = None) -> NotificationObserver:
        observer = cls(
            source=NativeNotifications() if source is None else source,
            banner_policy=BannerPolicy() if banner_policy is None else banner_policy,
        )
        threading.Thread(target=observer.run, name="Windows notifications", daemon=True).start()
        return observer

    def publish(self, value: Observation) -> None:
        with suppress(queue.Empty):
            self.results.get_nowait()
        self.results.put_nowait(value)

    def run(self) -> None:
        try:
            self._watch()
        finally:
            self.finished.set()

    def _watch(self) -> None:
        if not self.source.open():
            self.publish(Unavailable(Access.UNAVAILABLE))
            return
        try:
            failures = 0
            known: frozendict[NoticeKey, Notice] = frozendict()
            read_stamp: Stamp = None
            due = 0.0
            while not self.stopped.is_set():
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
        self.finished.wait(timeout=4)


def _known_or_read(row: UserNotification, known: Mapping[NoticeKey, Notice]) -> Notice | None:
    try:
        key = NoticeKey(int(row.Id), creation_time(row.CreationTime))
        return known.get(key) or read_notice(row, key)
    except OSError:
        return None  # The source can disappear between enumeration and reading.


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
