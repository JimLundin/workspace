"""Observe a potentially slow native microphone without waiting on Qt's thread."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Sample:
    revision: int
    at: float
    level: float | None


class AudioMeter:
    """Own one native reader and publish only its latest immutable observation.

    The events, lock and handoff require mutation for thread ownership. Native
    reading happens outside the handoff lock, so a slow driver cannot hold Qt.
    Revisions discard a read completed after its capture was stopped/restarted.
    """

    __slots__ = ("_lock", "_revision", "_sample", "clock", "enabled", "read", "stopped", "worker")

    def __init__(self, read: Callable[[], float | None], *, clock: Callable[[], float] = time.monotonic) -> None:
        self.read: Callable[[], float | None] = read
        self.clock: Callable[[], float] = clock
        self.enabled: threading.Event = threading.Event()
        self.stopped: threading.Event = threading.Event()
        self._lock: threading.Lock = threading.Lock()
        self._revision: int = 0
        self._sample: Sample | None = None
        self.worker: threading.Thread = threading.Thread(target=self.run, name="microphone level observer", daemon=True)
        self.worker.start()

    def listen(self, *, enabled: bool) -> None:
        with self._lock:
            if self.enabled.is_set() == enabled:
                return
            self._revision += 1
            self._sample = None
            self.enabled.set() if enabled else self.enabled.clear()

    def level(self) -> float | None:
        with self._lock:
            sample = self._sample
            if self.stopped.is_set() or not self.enabled.is_set() or sample is None:
                return None
        return sample.level if self.clock() - sample.at <= 0.25 else None

    def run(self) -> None:
        while not self.stopped.is_set():
            if not self.enabled.wait(0.05):
                continue
            if self.stopped.is_set():
                return
            with self._lock:
                revision = self._revision
            level = self.read()
            sample = Sample(revision, self.clock(), level)
            with self._lock:
                if revision == self._revision and self.enabled.is_set():
                    self._sample = sample
            self.stopped.wait(0.05)

    def close(self) -> None:
        self.stopped.set()
        self.enabled.set()
        self.worker.join(timeout=0.1)
