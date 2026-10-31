"""Real triage and work-bridge wiring with explicitly released debounce steps.

The fixture owns only waiting: locks, worker threads, model calls, HTTP requests
and response files use the production implementation. Each advance releases one
delay after the test has supplied the observations for that step.
"""

import threading
import time
from collections.abc import Callable
from pathlib import Path
from queue import Queue

from assistant.feed_contracts import FeedCommand, FeedRejected
from assistant.feed_sources import Candidate
from assistant.feed_triage_service import Store, Triage
from assistant.feed_work import FeedWork
from assistant.local_bridge import LocalBridge
from assistant.work_bridge import WorkOwners
from assistant.work_bridge_contracts import WORK_BRIDGE, BridgeCommand, BridgeResponse, FeedResponse
from assistant.work_canvas_commands import CanvasCommand, CanvasRefused, CanvasResponse
from automation.personal_work import PersonalRequest, PersonalResponse, WorkRefused
from automation.task import Profile


def feed_unavailable(_: FeedCommand) -> FeedResponse:
    return FeedRejected("The work feed is unavailable.")


def no_personal_work(_: PersonalRequest) -> PersonalResponse:
    return WorkRefused("My work is unavailable.")


def no_canvas(_: CanvasCommand) -> CanvasResponse:
    return CanvasRefused("The local canvas is unavailable.")


def feed_bridge(endpoint: Path, triage: Triage) -> LocalBridge[BridgeCommand, BridgeResponse]:
    """The application's work bridge with only the feed owner available."""
    return LocalBridge(endpoint, WORK_BRIDGE, WorkOwners(triage.command, no_personal_work, no_canvas).handle)


class TriageFixture(Triage):
    __slots__ = ("delays",)

    def __init__(
        self,
        store: Store,
        model: Callable[[tuple[Candidate, ...], tuple[str, ...]], str],
        *,
        submit: Callable[[str, str, Profile], None] | None = None,
        clock: Callable[[], float] = time.time,
        work: FeedWork | None = None,
    ) -> None:
        # Preserve the real owner's dependency interface rather than hide it in options.
        self.delays: Queue[tuple[float, threading.Event]] = Queue()
        super().__init__(store, model, submit=submit, wait=self.wait_for_stop, clock=clock, work=work)

    def wait_for_stop(self, stopped: threading.Event, timeout: float) -> bool:
        released = threading.Event()
        self.delays.put((timeout, released))
        while not released.is_set():
            if stopped.wait(0.01):
                return True
        return stopped.is_set()

    def advance(self) -> None:
        timeout, released = self.delays.get(timeout=5)
        assert timeout == 1.5, "The worker did not reach the expected debounce boundary."
        released.set()
