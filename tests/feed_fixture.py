"""Real triage and work-bridge wiring with explicitly released debounce steps.

The fixture owns only waiting: locks, worker threads, model calls, typed owner calls
and response files use the production implementation. Each advance releases one
delay after the test has supplied the observations for that step.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from queue import Queue

from assistant.feed_contracts import FeedCommand, FeedRejected
from assistant.feed_triage_service import Model, Store, Triage
from assistant.feed_work import FeedWork
from assistant.work_bridge import WorkOwners
from assistant.work_bridge_contracts import BRIDGE_COMMAND, BRIDGE_RESPONSE, BridgeCommand, FeedResponse
from contracts.personal_work import PersonalRequest, PersonalResponse, WorkRefused
from contracts.task import Profile
from contracts.work_canvas_commands import CanvasCommand, CanvasRefused, CanvasResponse


def feed_unavailable(_: FeedCommand) -> FeedResponse:
    return FeedRejected("The work feed is unavailable.")


def no_personal_work(_: PersonalRequest) -> PersonalResponse:
    return WorkRefused("My work is unavailable.")


def no_canvas(_: CanvasCommand) -> CanvasResponse:
    return CanvasRefused("The local canvas is unavailable.")


def owner_request(owners: WorkOwners) -> Callable[[BridgeCommand], str]:
    """Use the desktop's real serialization/routing boundary without a listener."""

    def request(command: BridgeCommand) -> str:
        return BRIDGE_RESPONSE.dump_json(owners.handle(BRIDGE_COMMAND.validate_json(BRIDGE_COMMAND.dump_json(command)))).decode("utf-8")

    return request


def feed_bridge(triage: Triage) -> Callable[[BridgeCommand], str]:
    """The application's desktop command adapter with only feed available."""
    return owner_request(WorkOwners(triage.command, no_personal_work, no_canvas))


@dataclass(frozen=True, slots=True)
class Delays:
    """The triage loop's cancellable waits, released one at a time by the test."""

    waiting: Queue[tuple[float, threading.Event]] = field(default_factory=Queue[tuple[float, threading.Event]])

    def wait_for_stop(self, stopped: threading.Event, timeout: float) -> bool:
        released = threading.Event()
        self.waiting.put((timeout, released))
        while not released.is_set():
            if stopped.wait(0.01):
                return True
        return stopped.is_set()


@dataclass(frozen=True, slots=True)
class TriageFixture:
    """A real triage owner whose debounce waits the test releases."""

    triage: Triage
    delays: Delays

    @classmethod
    def start(
        cls,
        store: Store,
        model: Model,
        *,
        submit: Callable[[str, str, Profile], None] | None = None,
        clock: Callable[[], float] = time.time,
        work: FeedWork | None = None,
    ) -> TriageFixture:
        delays = Delays()
        # A short tick: day changes and refused retries surface without a real second's wait.
        triage = Triage.start(store, model, submit=submit, wait=delays.wait_for_stop, clock=clock, work=work, tick_s=0.02)
        return cls(triage, delays)

    def advance(self) -> None:
        timeout, released = self.delays.waiting.get(timeout=5)
        assert timeout == 1.5, "The worker did not reach the expected debounce boundary."
        released.set()
