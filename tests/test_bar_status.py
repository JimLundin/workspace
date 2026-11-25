import threading
import time

from desktop_ui.ambient import History, SystemStatus
from desktop_ui.bar_status import (
    RANKED_AWAY,
    RESOURCES,
    StatusObserver,
    due,
    sampled_resources,
)
from winapi.machine_status import Memory, ProcessSample


class Speakers:
    def __init__(self) -> None:
        self.held = threading.Event()
        self.release = threading.Event()
        self.applied: list[tuple[float | bool, str]] = []

    def observe(self, *, listing: bool, ranking: bool) -> SystemStatus:
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


def test_a_drag_applies_only_its_latest_level_and_keeps_a_mute_on_the_status_worker() -> (
    None
):
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
        assert speakers.applied == [
            (0.7, "toolbar system status"),
            (True, "toolbar system status"),
        ]
        assert time.monotonic() - started < 0.9, (
            "The request waited for the next polling interval."
        )
    finally:
        observer.close()


def test_the_history_keeps_its_newest_samples_and_leaves_a_gap_for_an_unread_one() -> (
    None
):
    status = SystemStatus(
        cpu_history=History((1, 2, 3), capacity=3),
        memory_history=History((10, 20, 30), capacity=3),
    )
    read = sampled_resources(status, 4, Memory(40, 100))
    assert (read.cpu_history.samples, read.memory_history.samples) == (
        (2, 3, 4),
        (20, 30, 40),
    )
    unread = sampled_resources(read, None, None)
    assert (unread.cpu_history.samples, unread.memory_history.samples) == (
        (3, 4, None),
        (30, 40, None),
    )


def test_each_apps_use_is_read_at_once_then_at_the_pace_of_whether_it_shows() -> (
    None
):
    # Defects: the first read waits a whole interval, so the panels open empty; the
    # slow pace applies while a panel shows the apps; or the fast one never stops.
    assert due(None, 0.0, ranking=False)
    last = ProcessSample(100.0, ())
    assert not due(last, 100.0 + RESOURCES / 2, ranking=True)
    assert due(last, 100.0 + RESOURCES, ranking=True)
    assert not due(last, 100.0 + RESOURCES, ranking=False)
    assert due(last, 100.0 + RANKED_AWAY, ranking=False)
