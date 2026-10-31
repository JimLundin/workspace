"""Short-lived work context: window changes in memory, sampled without input hooks."""

import threading
import time
from collections.abc import Callable

from automation.activity import DEFAULT_POLICY, ContextSnapshot, Observation, Policy, Sample, observed


class ActivityTracker:
    """Poll only foreground app/title changes; never capture idle screenshots or keys."""

    __slots__ = ("_state", "agent_active", "lock", "policy", "read", "stopped", "thread")

    def __init__(self, read: Callable[[], Observation], agent_active: Callable[[], bool], *, policy: Policy = DEFAULT_POLICY) -> None:
        self.read, self.agent_active, self.policy = read, agent_active, policy
        self.lock = threading.Lock()
        self._state = ContextSnapshot(0, "unavailable" if policy.enabled else "disabled")
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None

    def observe(self, observation: Observation, now: float, *, agent_active: bool = False) -> ContextSnapshot:
        with self.lock:
            if self.stopped.is_set():
                return self._state
            self._state = observed(self._state, Sample(observation, now, agent_active=agent_active), self.policy)
            return self._state

    def snapshot(self) -> ContextSnapshot:
        if self.stopped.is_set():
            with self.lock:
                return self._state
        if not self.policy.enabled:
            return ContextSnapshot(time.time(), "disabled")
        try:
            observation = self.read()
        except OSError:
            observation = "unavailable"
        return self.observe(observation, time.time(), agent_active=self.agent_active())

    def start(self) -> None:
        if self.policy.enabled and self.thread is None:
            self.thread = threading.Thread(target=self.run, name="work context", daemon=True)
            self.thread.start()

    def run(self) -> None:
        while not self.stopped.is_set():
            self.snapshot()
            self.stopped.wait(1)

    def close(self) -> None:
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        with self.lock:
            self._state = ContextSnapshot(time.time(), "disabled")
