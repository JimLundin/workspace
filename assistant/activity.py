"""Short-lived work context: window changes in memory, sampled without input hooks."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from automation.activity import DEFAULT_POLICY, ContextSnapshot, Observation, Policy, Sample, observed
from cell import Cell


@dataclass(frozen=True, slots=True)
class _Tracked:
    snapshot: ContextSnapshot
    agent_active: bool = False
    """Whether the agent is working, as the control thread last said."""


@dataclass(frozen=True, slots=True)
class ActivityTracker:
    """Poll only foreground app/title changes; never capture idle screenshots or keys.

    Its own thread and every reader of `snapshot` share the latest record, so it is
    one Cell, replaced under the lock.
    """

    read: Callable[[], Observation]
    policy: Policy
    thread: threading.Thread
    """The polling thread; started only while the policy is enabled."""
    _state: Cell[_Tracked]
    lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    stopped: threading.Event = field(default_factory=threading.Event, init=False)

    @classmethod
    def of(cls, read: Callable[[], Observation], *, policy: Policy = DEFAULT_POLICY) -> ActivityTracker:
        # The thread runs the tracker made just after it.
        def run() -> None:
            tracker.run()

        thread = threading.Thread(target=run, name="work context", daemon=True)
        tracker = cls(read, policy, thread, Cell(_Tracked(ContextSnapshot(0, "unavailable" if policy.enabled else "disabled"))))
        return tracker

    def agent_working(self, *, active: bool) -> None:
        """The control thread says whether the agent is working; later samples carry it."""
        with self.lock:
            self._state.set(replace(self._state.get(), agent_active=active))

    def observe(self, observation: Observation, now: float, *, agent_active: bool = False) -> ContextSnapshot:
        with self.lock:
            tracked = self._state.get()
            if self.stopped.is_set():
                return tracked.snapshot
            snapshot = observed(tracked.snapshot, Sample(observation, now, agent_active=agent_active), self.policy)
            self._state.set(replace(tracked, snapshot=snapshot))
            return snapshot

    def snapshot(self) -> ContextSnapshot:
        if self.stopped.is_set():
            with self.lock:
                return self._state.get().snapshot
        if not self.policy.enabled:
            return ContextSnapshot(time.time(), "disabled")
        try:
            observation = self.read()
        except OSError:
            observation = "unavailable"
        with self.lock:
            agent_active = self._state.get().agent_active
        return self.observe(observation, time.time(), agent_active=agent_active)

    def start(self) -> None:
        if self.policy.enabled and self.thread.ident is None:
            self.thread.start()

    def run(self) -> None:
        while not self.stopped.is_set():
            self.snapshot()
            self.stopped.wait(1)

    def close(self) -> None:
        self.stopped.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=2)
        with self.lock:
            self._state.set(replace(self._state.get(), snapshot=ContextSnapshot(time.time(), "disabled")))
