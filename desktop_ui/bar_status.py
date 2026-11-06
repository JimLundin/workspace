"""System indicators are observed off the UI thread, with one bounded result slot.

The same worker applies speaker-level requests. Windows' audio interfaces need a
multithreaded COM apartment, which Qt's thread cannot join. Requests coalesce, so
a drag applies its latest level rather than every intermediate one.
The same worker reads processor and memory use, every two seconds.
"""

import queue
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from typing import Final

from desktop_ui.ambient import SystemStatus
from winapi.machine_status import CpuTimes, cpu_load
lazy from winapi import resources, system_status

RESOURCES: Final = 2.0  # Seconds between processor and memory readings; faster readings only flicker.


class Observation:
    """Each observation reads the speakers and Wi-Fi; processor load needs the previous sample to measure against."""

    __slots__ = ("clock", "last", "sampled", "times")

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.last = SystemStatus()
        self.times: CpuTimes | None = None
        self.sampled = 0.0

    def observe(self) -> SystemStatus:
        audio = system_status.audio()
        now = self.clock()
        # Until a first load is known, the next tick measures one; then every interval.
        if self.last.cpu is None or now - self.sampled >= RESOURCES:
            times = resources.cpu_times()
            self.last = replace(self.last, cpu=cpu_load(self.times, times), memory=resources.memory_load())
            self.times, self.sampled = times, now
        return replace(self.last, speakers=audio.speakers, wifi=system_status.wifi(), volume=audio.volume)


def apply_volume(level: float) -> bool:
    return system_status.set_volume(level)


class StatusObserver:
    __slots__ = ("apply", "cancelled", "observe", "requests", "results", "wake", "worker")

    def __init__(self, observe: Callable[[], SystemStatus] | None = None, apply: Callable[[float], bool] = apply_volume) -> None:
        self.observe = observe if observe is not None else Observation().observe
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
