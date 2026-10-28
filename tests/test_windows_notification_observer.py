"""Notification mirroring must retain delivery when banner control fails."""

import asyncio
import sys
import unittest
from unittest.mock import patch

if sys.platform != "win32":
    raise unittest.SkipTest("Native notification observer")

from assistant.system_notices import Banners, Notice, NoticeKey, Observation, Observed, Unavailable
from winapi.notification_banners import BannerPolicy, Coverage
from winapi.notifications import NotificationObserver


class Lease(BannerPolicy):
    __slots__ = ("closes", "syncs")

    def __init__(self) -> None:
        super().__init__(settings_path="unused", backup_path="unused")
        self.closes = self.syncs = 0

    def sync(self) -> Coverage:
        self.syncs += 1
        if self.syncs == 1:
            raise OSError("Fixture banner settings are unavailable")
        return Coverage(0, 0)

    def close(self) -> None:
        self.closes += 1


def test_banner_failure_keeps_notice_delivery_and_repeated_read_failures_release_suppression() -> None:
    notice = Notice(NoticeKey(1, 10), "Fixture", "Fixture", "Update", "Local test")
    calls = 0
    results: list[Observation] = []
    async def read_fixture() -> Observation:
        nonlocal calls
        calls += 1
        if calls > 2:
            raise TimeoutError("Fixture notification read timed out")
        return Observed((notice,))
    def publish(observer: NotificationObserver, result: Observation) -> None:
        results.append(result)
        if len(results) == 5:
            observer.stopped.set()
    with patch("winapi.notifications.threading.Thread.start"):
        observer = NotificationObserver()
    lease = Lease()
    observer.banner_policy = lease
    with patch("winapi.notifications.read", read_fixture), patch.object(NotificationObserver, "publish", publish):
        observer.thread.start()
        observer.thread.join(timeout=8)
    assert not observer.thread.is_alive()
    assert results[:2] == [Observed((notice,), Banners.PARTIAL), Observed((notice,), Banners.SUPPRESSED)]
    assert all(isinstance(result, Unavailable) for result in results[2:])
    assert lease.closes == 2  # Repeated failure recovery, followed by owner shutdown.


def test_notification_polls_share_one_event_loop_for_late_winrt_callbacks() -> None:
    loops: list[asyncio.AbstractEventLoop] = []
    completed: list[bool] = []
    async def observe() -> Observation:
        loop = asyncio.get_running_loop()
        loops.append(loop)
        if len(loops) == 1:
            loop.call_later(.02, completed.append, True)
        return Observed(())
    def publish(observer: NotificationObserver, _result: Observation) -> None:
        if len(loops) == 2:
            observer.stopped.set()
    with patch('winapi.notifications.threading.Thread.start'):
        observer = NotificationObserver()
    observer.banner_policy = Lease()
    with patch('winapi.notifications.read', observe), patch.object(NotificationObserver, 'publish', publish):
        observer.thread.start()
        observer.thread.join(timeout=4)
    assert not observer.thread.is_alive() and len(loops) == 2
    assert loops[0] is loops[1] and completed == [True]
