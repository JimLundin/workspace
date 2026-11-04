"""The toolbar's status worker applies speaker levels off the UI thread."""

import threading
import time

from desktop_ui.ambient import SystemStatus
from desktop_ui.bar_status import StatusObserver


class Speakers:
    """A concrete level owner that records where and what the worker applied."""

    def __init__(self) -> None:
        self.held = threading.Event()
        self.release = threading.Event()
        self.applied: list[tuple[float, str]] = []

    def observe(self) -> SystemStatus:
        self.held.set()
        self.release.wait(2)
        return SystemStatus()

    def apply(self, level: float) -> bool:
        self.applied.append((level, threading.current_thread().name))
        return True


def test_a_drag_applies_only_its_latest_level_on_the_status_worker() -> None:
    # Defects: every intermediate level of a drag queues a native write, the write
    # runs on the caller's thread, or a request waits for the next polling second.
    speakers = Speakers()
    observer = StatusObserver(speakers.observe, speakers.apply)
    try:
        assert speakers.held.wait(2), "The worker did not start observing."
        for level in (0.2, 0.5, 0.7):
            observer.set_volume(level)
        started = time.monotonic()
        speakers.release.set()
        while not speakers.applied and time.monotonic() - started < 2:
            time.sleep(0.01)
        assert speakers.applied == [(0.7, "toolbar system status")]
        assert time.monotonic() - started < 0.9, "The request waited for the next polling interval."
    finally:
        observer.close()
