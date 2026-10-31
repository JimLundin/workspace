"""Notification mirroring must retain delivery when banner control fails."""

import sys
import threading
import unittest
from collections.abc import Callable, Mapping

if sys.platform != "win32":
    raise unittest.SkipTest("Native notification observer")

from winapi.notification_banners import Coverage
from winapi.notifications import NotificationObserver, Stamp
from winapi.system_notices import Banners, Notice, NoticeKey, Observation, Observed, Unavailable


class Lease:
    __slots__ = ("closes", "syncs")

    def __init__(self) -> None:
        self.closes = self.syncs = 0

    def sync(self) -> Coverage:
        self.syncs += 1
        if self.syncs == 1:
            raise OSError("Fixture banner settings are unavailable")
        return Coverage(0, 0)

    def close(self) -> None:
        self.closes += 1


class Source:
    """Own fixture poll callbacks and lifecycle counters across the real worker thread."""

    __slots__ = ("closes", "known", "observe", "opens", "version", "writing")

    def __init__(self, observe: Callable[[], Observation], *, writing: bool = True) -> None:
        self.observe = observe
        self.opens = self.closes = self.version = 0
        self.writing = writing  # Whether Windows' database changes before every poll.
        self.known: list[Mapping[NoticeKey, Notice]] = []

    def open(self) -> bool:
        self.opens += 1
        return True

    def stamp(self) -> Stamp:
        if self.writing:
            self.version += 1
        return ((self.version, 0),)

    def read(self, stopped: threading.Event, known: Mapping[NoticeKey, Notice]) -> Observation:
        self.known.append(dict(known))
        return self.observe()

    def dismiss(self, key: NoticeKey) -> None:
        pass

    def close(self) -> None:
        self.closes += 1


def test_banner_failure_keeps_notice_delivery_and_repeated_read_failures_release_suppression() -> None:
    notice = Notice(NoticeKey(1, 10), "Fixture", "Fixture", "Update", "Local test")
    calls = 0

    def read_fixture() -> Observation:
        nonlocal calls
        calls += 1
        if calls > 2:
            raise TimeoutError("Fixture notification read timed out")
        return Observed((notice,))

    lease = Lease()
    source = Source(read_fixture)
    observer = NotificationObserver(source=source, banner_policy=lease)
    try:
        results = tuple(observer.results.get(timeout=2) for _ in range(5))
    finally:
        observer.close()
    assert not observer.thread.is_alive()
    assert results[:2] == (Observed((notice,), Banners.PARTIAL), Observed((notice,), Banners.SUPPRESSED))
    assert all(isinstance(result, Unavailable) for result in results[2:])
    assert lease.closes == 2  # Repeated failure recovery, followed by owner shutdown.
    assert source.opens == source.closes == 1
    # Each read reuses the last successful observation; failed reads keep it.
    assert source.known[:5] == [{}] + [{notice.key: notice}] * 4



def test_notification_reads_follow_database_changes_instead_of_every_poll() -> None:
    reads = 0

    def observe() -> Observation:
        nonlocal reads
        reads += 1
        return Observed(())

    source = Source(observe, writing=False)
    observer = NotificationObserver(source=source, banner_policy=Lease())
    try:
        observer.results.get(timeout=2)
        assert not observer.stopped.wait(0.8) and reads == 1
        source.version += 1
        observer.results.get(timeout=2)
    finally:
        observer.close()
    assert reads == 2
