"""System indicators are observed off the UI thread, with one bounded result slot.

The same worker applies speaker-level requests. Windows' audio interfaces need a
multithreaded COM apartment, which Qt's thread cannot join. Requests coalesce, so
a drag applies its latest level rather than every intermediate one.
"""

import queue
import threading
from collections.abc import Callable
from contextlib import suppress

from desktop_ui.ambient import SystemStatus
lazy from winapi import system_status


def observed_status() -> SystemStatus:
    audio = system_status.audio()
    return SystemStatus(audio.speakers, system_status.wifi(), audio.volume)


def apply_volume(level: float) -> bool:
    return system_status.set_volume(level)


class StatusObserver:
    __slots__ = ("apply", "cancelled", "observe", "requests", "results", "wake", "worker")

    def __init__(self, observe: Callable[[], SystemStatus] = observed_status, apply: Callable[[float], bool] = apply_volume) -> None:
        self.observe = observe
        self.apply = apply
        self.cancelled = threading.Event()
        self.wake = threading.Event()
        self.requests: queue.Queue[float] = queue.Queue(maxsize=1)
        self.results: queue.Queue[SystemStatus] = queue.Queue(maxsize=1)
        self.worker = threading.Thread(target=self.run, name="toolbar system status", daemon=True)
        self.worker.start()

    def set_volume(self, level: float) -> None:
        """Called from the UI thread only: it is the one producer, so replacing the pending level cannot race."""
        with suppress(queue.Empty):
            self.requests.get_nowait()
        self.requests.put_nowait(level)
        self.wake.set()

    def run(self) -> None:
        while not self.cancelled.is_set():
            with suppress(queue.Empty):
                self.apply(self.requests.get_nowait())
            observed = self.observe()
            with suppress(queue.Empty):
                self.results.get_nowait()
            self.results.put_nowait(observed)
            self.wake.wait(1)
            self.wake.clear()

    def close(self) -> None:
        self.cancelled.set()
        self.wake.set()
        self.worker.join(timeout=0.1)
