"""Short-lived work context: window changes in memory, sampled without input hooks."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from automation.activity import DEFAULT_POLICY, ContextSnapshot, Observation, Policy, Sample, observed
from cell import Cell


@dataclass(frozen=True, slots=True)
class ActivityTracker:
    """Poll only foreground app/title changes; never capture idle screenshots or keys."""

    read: Callable[[], Observation]
    agent_active: Callable[[], bool]
    policy: Policy
    _state: Cell[ContextSnapshot]
    """The latest snapshot, replaced under the lock."""
    lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    stopped: threading.Event = field(default_factory=threading.Event, init=False)
    _thread: Cell[threading.Thread | None] = field(default_factory=lambda: Cell[threading.Thread | None](None), init=False, repr=False)

    @property
    def thread(self) -> threading.Thread | None:
        """The polling thread, once started."""
        return self._thread.get()

    @classmethod
    def of(cls, read: Callable[[], Observation], agent_active: Callable[[], bool], *, policy: Policy = DEFAULT_POLICY) -> ActivityTracker:
        return cls(read, agent_active, policy, Cell(ContextSnapshot(0, "unavailable" if policy.enabled else "disabled")))

    def observe(self, observation: Observation, now: float, *, agent_active: bool = False) -> ContextSnapshot:
        with self.lock:
            if self.stopped.is_set():
                return self._state.get()
            return self._state.update(lambda state: observed(state, Sample(observation, now, agent_active=agent_active), self.policy))

    def snapshot(self) -> ContextSnapshot:
        if self.stopped.is_set():
            with self.lock:
                return self._state.get()
        if not self.policy.enabled:
            return ContextSnapshot(time.time(), "disabled")
        try:
            observation = self.read()
        except OSError:
            observation = "unavailable"
        return self.observe(observation, time.time(), agent_active=self.agent_active())

    def start(self) -> None:
        if self.policy.enabled and self._thread.get() is None:
            thread = threading.Thread(target=self.run, name="work context", daemon=True)
            self._thread.set(thread)
            thread.start()

    def run(self) -> None:
        while not self.stopped.is_set():
            self.snapshot()
            self.stopped.wait(1)

    def close(self) -> None:
        self.stopped.set()
        if (thread := self._thread.get()) is not None:
            thread.join(timeout=2)
        with self.lock:
            self._state.set(ContextSnapshot(time.time(), "disabled"))
