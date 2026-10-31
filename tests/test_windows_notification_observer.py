"""Notification mirroring must retain delivery when banner control fails."""

import asyncio
import sys
import unittest
from collections.abc import Awaitable, Callable

if sys.platform != "win32":
    raise unittest.SkipTest("Native notification observer")

from winapi.notification_banners import Coverage
from winapi.notifications import NotificationObserver
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

    __slots__ = ("closes", "observe", "opens")

    def __init__(self, observe: Callable[[], Awaitable[Observation]]) -> None:
        self.observe = observe
        self.opens = self.closes = 0

    def open(self) -> bool:
        self.opens += 1
        return True

    async def read(self) -> Observation:
        return await self.observe()

    def dismiss(self, key: NoticeKey) -> None:
        pass

    def close(self) -> None:
        self.closes += 1


def test_banner_failure_keeps_notice_delivery_and_repeated_read_failures_release_suppression() -> None:
    notice = Notice(NoticeKey(1, 10), "Fixture", "Fixture", "Update", "Local test")
    calls = 0

    async def read_fixture() -> Observation:
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


def test_notification_polls_share_one_event_loop_for_late_winrt_callbacks() -> None:
    loops: list[asyncio.AbstractEventLoop] = []
    completed: list[bool] = []

    async def observe() -> Observation:
        loop = asyncio.get_running_loop()
        loops.append(loop)
        if len(loops) == 1:
            loop.call_later(0.02, completed.append, True)
        return Observed(())

    observer = NotificationObserver(source=Source(observe), banner_policy=Lease())
    try:
        for _ in range(2):
            observer.results.get(timeout=2)
    finally:
        observer.close()
    assert not observer.thread.is_alive() and len(loops) == 2
    assert loops[0] is loops[1] and completed == [True]
