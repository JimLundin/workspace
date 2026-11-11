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
from dataclasses import dataclass, field, replace
from typing import Final

from cell import Cell
from desktop_ui.ambient import SystemStatus
from winapi.machine_status import CpuTimes, cpu_load
lazy from winapi import resources, system_status

RESOURCES: Final = 2.0  # Seconds between processor and memory readings; faster readings only flicker.


@dataclass(frozen=True, slots=True)
class _Sampled:
    last: SystemStatus = field(default_factory=SystemStatus)
    times: CpuTimes | None = None
    """The processor times the next load measures against."""
    sampled: float = 0.0


@dataclass(frozen=True, slots=True)
class Observation:
    """Each observation reads the speakers and Wi-Fi; processor load needs the previous sample to measure against."""

    clock: Callable[[], float] = time.monotonic
    _sampled: Cell[_Sampled] = field(default_factory=lambda: Cell(_Sampled()), init=False, repr=False)

    def observe(self) -> SystemStatus:
        audio = system_status.audio()
        now = self.clock()
        sampled = self._sampled.get()
        # Until a first load is known, the next tick measures one; then every interval.
        if sampled.last.cpu is None or now - sampled.sampled >= RESOURCES:
            times = resources.cpu_times()
            sampled = _Sampled(replace(sampled.last, cpu=cpu_load(sampled.times, times), memory=resources.memory_use()), times, now)
            self._sampled.set(sampled)
        return replace(sampled.last, speakers=audio.speakers, wifi=system_status.wifi(), volume=audio.volume)


def apply_volume(level: float) -> bool:
    return system_status.set_volume(level)


def _observe_status() -> Callable[[], SystemStatus]:
    return Observation().observe


@dataclass(frozen=True, slots=True)
class StatusObserver:
    observe: Callable[[], SystemStatus] = field(default_factory=_observe_status)
    apply: Callable[[float], bool] = apply_volume
    cancelled: threading.Event = field(default_factory=threading.Event)
    wake: threading.Event = field(default_factory=threading.Event)
    requests: queue.Queue[float] = field(default_factory=lambda: queue.Queue[float](maxsize=1))
    results: queue.Queue[SystemStatus] = field(default_factory=lambda: queue.Queue[SystemStatus](maxsize=1))
    finished: threading.Event = field(default_factory=threading.Event)
    """Set when the worker thread exits."""

    @classmethod
    def start(cls, observe: Callable[[], SystemStatus] | None = None, apply: Callable[[float], bool] = apply_volume) -> StatusObserver:
        observer = cls(apply=apply) if observe is None else cls(observe, apply)
        threading.Thread(target=observer.run, name="toolbar system status", daemon=True).start()
        return observer

    def set_volume(self, level: float) -> None:
        """Called from the UI thread only: it is the one producer, so replacing the pending level cannot race."""
        with suppress(queue.Empty):
            self.requests.get_nowait()
        self.requests.put_nowait(level)
        self.wake.set()

    def run(self) -> None:
        try:
            self._poll()
        finally:
            self.finished.set()

    def _poll(self) -> None:
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
        self.finished.wait(timeout=0.1)
