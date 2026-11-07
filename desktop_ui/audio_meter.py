"""Observe a potentially slow native microphone without waiting on Qt's thread."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from cell import Cell


@dataclass(frozen=True, slots=True)
class Sample:
    revision: int
    at: float
    level: float | None


@dataclass(frozen=True, slots=True)
class _Reading:
    revision: int = 0
    """Advances when capture stops or starts, discarding a read that straddled it."""
    sample: Sample | None = None


@dataclass(frozen=True, slots=True)
class AudioMeter:
    """Own one native reader and publish only its latest immutable observation.

    Native reading happens outside the handoff lock, so a slow driver cannot hold Qt.
    Revisions discard a read completed after its capture was stopped/restarted.
    """

    read: Callable[[], float | None]
    clock: Callable[[], float]
    enabled: threading.Event
    stopped: threading.Event
    finished: threading.Event
    """Set when the observing thread exits."""
    _reading: Cell[_Reading] = field(default_factory=lambda: Cell(_Reading()), init=False, repr=False)
    """Replaced whole under the lock."""
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def start(cls, read: Callable[[], float | None], *, clock: Callable[[], float] = time.monotonic) -> AudioMeter:
        meter = cls(read, clock, threading.Event(), threading.Event(), threading.Event())
        threading.Thread(target=meter.run, name="microphone level observer", daemon=True).start()
        return meter

    def listen(self, *, enabled: bool) -> None:
        with self._lock:
            if self.enabled.is_set() == enabled:
                return
            self._reading.update(lambda reading: _Reading(reading.revision + 1))
            self.enabled.set() if enabled else self.enabled.clear()

    def level(self) -> float | None:
        with self._lock:
            sample = self._reading.get().sample
            if self.stopped.is_set() or not self.enabled.is_set() or sample is None:
                return None
        return sample.level if self.clock() - sample.at <= 0.25 else None

    def run(self) -> None:
        try:
            self._observe()
        finally:
            self.finished.set()

    def _observe(self) -> None:
        while not self.stopped.is_set():
            if not self.enabled.wait(0.05):
                continue
            if self.stopped.is_set():
                return
            with self._lock:
                revision = self._reading.get().revision
            level = self.read()
            sample = Sample(revision, self.clock(), level)
            with self._lock:
                if revision == self._reading.get().revision and self.enabled.is_set():
                    self._reading.set(_Reading(revision, sample))
            self.stopped.wait(0.05)

    def close(self) -> None:
        self.stopped.set()
        self.enabled.set()
        self.finished.wait(timeout=0.1)
