"""System indicators are observed off the UI thread, with one bounded result slot.

The same worker applies the speakers' level and mute. Windows' audio interfaces need a
multithreaded COM apartment, which Qt's thread cannot join. Requests coalesce by
kind, so a drag applies its latest level rather than every intermediate one, and
never drops a mute requested beside it.
The same worker reads processor and memory use, every two seconds.
"""

import queue
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import Final, Protocol

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


@dataclass(frozen=True, slots=True)
class Pending:
    """Requests not yet applied: a later request of a kind replaces the earlier one."""

    volume: float | None = None
    muted: bool | None = None


class Speakers(Protocol):
    """What applies the speakers' requests."""

    def volume(self, level: float) -> bool: ...
    def mute(self, *, muted: bool) -> bool: ...


@dataclass(frozen=True, slots=True)
class DefaultSpeakers:
    """Windows' default playback device."""

    def volume(self, level: float) -> bool:
        return system_status.set_volume(level)

    def mute(self, *, muted: bool) -> bool:
        return system_status.set_mute(muted=muted)


def apply(speakers: Speakers, pending: Pending) -> None:
    if pending.volume is not None:
        speakers.volume(pending.volume)
    if pending.muted is not None:
        speakers.mute(muted=pending.muted)


def _observe_status() -> Callable[[], SystemStatus]:
    return Observation().observe


@dataclass(frozen=True, slots=True)
class StatusObserver:
    observe: Callable[[], SystemStatus] = field(default_factory=_observe_status)
    speakers: Speakers = field(default_factory=DefaultSpeakers)
    cancelled: threading.Event = field(default_factory=threading.Event)
    wake: threading.Event = field(default_factory=threading.Event)
    requests: Cell[Pending] = field(default_factory=lambda: Cell(Pending()))
    lock: threading.Lock = field(default_factory=threading.Lock)
    """Serializes the UI thread's requests with the worker taking them."""
    results: queue.Queue[SystemStatus] = field(default_factory=lambda: queue.Queue[SystemStatus](maxsize=1))
    finished: threading.Event = field(default_factory=threading.Event)
    """Set when the worker thread exits."""

    @classmethod
    def start(cls, observe: Callable[[], SystemStatus] | None = None, speakers: Speakers | None = None) -> StatusObserver:
        applied = DefaultSpeakers() if speakers is None else speakers
        observer = cls(speakers=applied) if observe is None else cls(observe, applied)
        threading.Thread(target=observer.run, name="toolbar system status", daemon=True).start()
        return observer

    def request(self, change: Callable[[Pending], Pending]) -> None:
        with self.lock:
            self.requests.update(change)
        self.wake.set()

    def set_volume(self, level: float) -> None:
        self.request(lambda pending: replace(pending, volume=level))

    def set_mute(self, *, muted: bool) -> None:
        self.request(lambda pending: replace(pending, muted=muted))

    def taken(self) -> Pending:
        """The pending requests, leaving none."""
        with self.lock:
            pending = self.requests.get()
            self.requests.set(Pending())
        return pending

    def run(self) -> None:
        try:
            self._poll()
        finally:
            self.finished.set()

    def _poll(self) -> None:
        while not self.cancelled.is_set():
            apply(self.speakers, self.taken())
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
