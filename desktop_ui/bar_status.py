"""System indicators are observed off the UI thread, with one bounded result slot.

The same worker applies the speakers' level and mute, and Wi-Fi scans and joins.
Windows' audio interfaces need a multithreaded COM apartment, which Qt's thread
cannot join, and a scan or join blocks. Requests coalesce by kind, so a drag
applies its latest level rather than every intermediate one, and never drops a
mute requested beside it.
The same worker reads processor and memory use every two seconds, and the Wi-Fi
networks in range each tick while their panel is open.
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
from winapi.machine_status import CpuTimes, Memory, cpu_load
lazy from winapi import resources, system_status

RESOURCES: Final = 2.0  # Seconds between processor and memory readings; faster readings only flicker.


@dataclass(frozen=True, slots=True)
class _Sampled:
    last: SystemStatus = field(default_factory=SystemStatus)
    times: CpuTimes | None = None
    """The processor times the next load measures against."""
    sampled: float = 0.0


def sampled_resources(last: SystemStatus, cpu: int | None, memory: Memory | None) -> SystemStatus:
    """The new processor and memory readings, each added to its history; an unread one leaves a gap."""
    return replace(
        last,
        cpu=cpu,
        memory=memory,
        cpu_history=last.cpu_history.added(cpu),
        memory_history=last.memory_history.added(memory.used if memory is not None else None),
    )


@dataclass(frozen=True, slots=True)
class Observation:
    """Each observation reads the speakers and Wi-Fi; processor load needs the previous sample to measure against."""

    clock: Callable[[], float] = time.monotonic
    _sampled: Cell[_Sampled] = field(default_factory=lambda: Cell(_Sampled()), init=False, repr=False)

    def observe(self, *, listing: bool) -> SystemStatus:
        audio = system_status.audio()
        now = self.clock()
        sampled = self._sampled.get()
        # Until a first load is known, the next tick measures one; then every interval.
        if sampled.last.cpu is None or now - sampled.sampled >= RESOURCES:
            times = resources.cpu_times()
            sampled = _Sampled(sampled_resources(sampled.last, cpu_load(sampled.times, times), resources.memory_use()), times, now)
            self._sampled.set(sampled)
        networks = system_status.networks() if listing else ()
        return replace(sampled.last, speakers=audio.speakers, wifi=system_status.wifi(), volume=audio.volume, networks=networks)


@dataclass(frozen=True, slots=True)
class Pending:
    """Requests not yet applied: a later request of a kind replaces the earlier one."""

    volume: float | None = None
    muted: bool | None = None
    scan: bool = False
    join: str | None = None
    """The saved profile to connect through."""


class Machine(Protocol):
    """What applies the requests."""

    def volume(self, level: float) -> bool: ...
    def mute(self, *, muted: bool) -> bool: ...
    def scan(self) -> None: ...
    def join(self, profile: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ThisMachine:
    """Windows' default playback device and Wi-Fi adapters."""

    def volume(self, level: float) -> bool:
        return system_status.set_volume(level)

    def mute(self, *, muted: bool) -> bool:
        return system_status.set_mute(muted=muted)

    def scan(self) -> None:
        system_status.scan()

    def join(self, profile: str) -> bool:
        return system_status.join(profile)


def apply(machine: Machine, pending: Pending) -> None:
    if pending.volume is not None:
        machine.volume(pending.volume)
    if pending.muted is not None:
        machine.mute(muted=pending.muted)
    if pending.join is not None:
        machine.join(pending.join)
    if pending.scan:
        machine.scan()


class Observe(Protocol):
    """One reading of the system; `listing` reads the Wi-Fi networks in range too."""

    def __call__(self, *, listing: bool) -> SystemStatus: ...


def _observe_status() -> Observe:
    return Observation().observe


@dataclass(frozen=True, slots=True)
class StatusObserver:
    observe: Observe = field(default_factory=_observe_status)
    machine: Machine = field(default_factory=ThisMachine)
    cancelled: threading.Event = field(default_factory=threading.Event)
    wake: threading.Event = field(default_factory=threading.Event)
    listing: threading.Event = field(default_factory=threading.Event)
    """The Wi-Fi panel is open: each tick reads the networks in range."""
    requests: Cell[Pending] = field(default_factory=lambda: Cell(Pending()))
    lock: threading.Lock = field(default_factory=threading.Lock)
    """Serializes the UI thread's requests with the worker taking them."""
    results: queue.Queue[SystemStatus] = field(default_factory=lambda: queue.Queue[SystemStatus](maxsize=1))
    finished: threading.Event = field(default_factory=threading.Event)
    """Set when the worker thread exits."""

    @classmethod
    def start(cls, observe: Observe | None = None, machine: Machine | None = None) -> StatusObserver:
        applied = ThisMachine() if machine is None else machine
        observer = cls(machine=applied) if observe is None else cls(observe, applied)
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

    def survey(self, *, listing: bool) -> None:
        """Read the networks in range while `listing`, scanning afresh as it starts."""
        if listing and not self.listing.is_set():
            self.listing.set()
            self.request(lambda pending: replace(pending, scan=True))
        elif not listing:
            self.listing.clear()

    def join(self, profile: str) -> None:
        self.request(lambda pending: replace(pending, join=profile))

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
            apply(self.machine, self.taken())
            observed = self.observe(listing=self.listing.is_set())
            with suppress(queue.Empty):
                self.results.get_nowait()
            self.results.put_nowait(observed)
            self.wake.wait(1)
            self.wake.clear()

    def close(self) -> None:
        self.cancelled.set()
        self.wake.set()
        self.finished.wait(timeout=0.1)
