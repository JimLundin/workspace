"""The toolbar's status worker applies speaker levels off the UI thread."""

import threading
import time

from desktop_ui.ambient import History, SystemStatus
from desktop_ui.bar_status import StatusObserver, sampled_resources
from winapi.machine_status import Memory


class Speakers:
    """A concrete machine that records where and what the worker applied."""

    def __init__(self) -> None:
        self.held = threading.Event()
        self.release = threading.Event()
        self.applied: list[tuple[float | bool, str]] = []

    def observe(self, *, listing: bool) -> SystemStatus:
        self.held.set()
        self.release.wait(2)
        return SystemStatus()

    def volume(self, level: float) -> bool:
        self.applied.append((level, threading.current_thread().name))
        return True

    def mute(self, *, muted: bool) -> bool:
        self.applied.append((muted, threading.current_thread().name))
        return True

    def scan(self) -> None:
        self.applied.append((True, "scan"))

    def join(self, profile: str) -> bool:
        self.applied.append((0.0, profile))
        return True


def test_a_drag_applies_only_its_latest_level_and_keeps_a_mute_on_the_status_worker() -> None:
    # Defects: every intermediate level of a drag queues a native write, a later level
    # drops the mute requested beside it, the write runs on the caller's thread, or a
    # request waits for the next polling second.
    speakers = Speakers()
    observer = StatusObserver.start(speakers.observe, speakers)
    try:
        assert speakers.held.wait(2), "The worker did not start observing."
        observer.set_volume(0.2)
        observer.set_mute(muted=True)
        for level in (0.5, 0.7):
            observer.set_volume(level)
        started = time.monotonic()
        speakers.release.set()
        while len(speakers.applied) < 2 and time.monotonic() - started < 2:
            time.sleep(0.01)
        assert speakers.applied == [(0.7, "toolbar system status"), (True, "toolbar system status")]
        assert time.monotonic() - started < 0.9, "The request waited for the next polling interval."
    finally:
        observer.close()


def test_the_history_keeps_its_newest_samples_and_leaves_a_gap_for_an_unread_one() -> None:
    # Defects: the history grows without bound, drops the newest sample instead of the
    # oldest, or records an unread processor or memory reading as zero use.
    status = SystemStatus(cpu_history=History((1, 2, 3), capacity=3), memory_history=History((10, 20, 30), capacity=3))
    read = sampled_resources(status, 4, Memory(40, 100))
    assert (read.cpu_history.samples, read.memory_history.samples) == ((2, 3, 4), (20, 30, 40))
    unread = sampled_resources(read, None, None)
    assert (unread.cpu_history.samples, unread.memory_history.samples) == ((3, 4, None), (30, 40, None))
