"""Real triage/HTTP wiring with explicitly released debounce steps.

The fixture owns only waiting: locks, worker threads, model calls, HTTP requests
and response files use the production implementation. Each advance releases one
delay after the test has supplied the observations for that step.
"""

import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue

from assistant.console_requests import Command
from assistant.feed_triage import Board, Candidate
from assistant.feed_triage_service import Store, Triage
from assistant.feed_work import FeedWork
from automation.task import Profile


class LocalBridge(ThreadingHTTPServer):
    def serve_forever(self, poll_interval: float = 0.5) -> None:
        # HTTP behavior is unchanged; idle fixture shutdown need not take .5s.
        super().serve_forever(poll_interval=0.02)


def open_bridge(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    return LocalBridge(("127.0.0.1", 0), handler)


class TriageFixture(Triage):
    __slots__ = ("delays",)

    def __init__(
        self,
        endpoint: Path,
        store: Store,
        publish: Callable[[Board], None],
        model: Callable[[tuple[Candidate, ...], tuple[str, ...]], str],
        console: Callable[[Command], bool],
        *,
        submit: Callable[[str, str, Profile], None] | None = None,
        clock: Callable[[], float] = time.time,
        work: FeedWork | None = None,
    ) -> None:
        # Preserve the real owner's dependency interface rather than hide it in options.
        self.delays: Queue[tuple[float, threading.Event]] = Queue()
        super().__init__(
            endpoint, store, publish, model, console, submit=submit, server_factory=open_bridge, wait=self.wait_for_stop, clock=clock, work=work
        )

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
