"""One native view per owner: publish from any thread, render on the view's thread, close once.

The owner keeps its immutable state and lock. This lifecycle owns only the view,
its coalesced render and its closure; `create` and `render` run on the view's
thread, reached through `post`.
"""

import contextlib
import threading
import time
import traceback
from collections.abc import Callable
from enum import Enum, auto
from typing import Final, Protocol

from usage import DIRECTORY

VIEW_LOG: Final = DIRECTORY / "agent-ui.log"

type Post = Callable[[Callable[[], None]], None]


def log_view(text: str) -> None:
    with contextlib.suppress(OSError):
        VIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
        with VIEW_LOG.open("a", encoding="utf-8") as output:
            output.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


class Closable(Protocol):
    def close(self) -> None: ...


class Unavailable(Enum):
    CLOSED = auto()
    # Creation raised; the traceback is in agent-ui.log and a later open retries.
    FAILED = auto()


class ViewPublication[V: Closable]:
    __slots__ = ("_create", "_lock", "_pending", "_post", "_render", "_view", "closed", "closed_ready", "ready")

    def __init__(self, post: Post, create: Callable[[], V], render: Callable[[V | None], None]) -> None:
        self._post, self._create, self._render = post, create, render
        self._lock = threading.Lock()
        self._pending = self.closed = False
        self._view: V | None = None
        # Set while a created view is attached; closed_ready confirms the view thread released it.
        self.ready, self.closed_ready = threading.Event(), threading.Event()

    def post(self, job: Callable[[], None]) -> None:
        """Any thread: run an owner job on the view's thread, unless the view has closed by then."""

        def run() -> None:
            if not self.closed:
                job()

        self._post(run)

    def changed(self) -> None:
        """Any thread: coalesce one render of the owner's latest state."""
        with self._lock:
            if self.closed or self._pending:
                return
            self._pending = True
        self._post(self._deliver)

    def _deliver(self) -> None:
        with self._lock:
            self._pending = False
            view, closed = self._view, self.closed
        if not closed:
            self._render(view)

    def holds(self, view: V) -> bool:
        with self._lock:
            return self._view is view

    def opened(self) -> V | Unavailable:
        """View thread: the view, created on first use and rendered with the latest state."""
        with self._lock:
            if self.closed:
                return Unavailable.CLOSED
            view = self._view
        if view is None:
            try:
                view = self._create()
            except Exception:
                log_view(traceback.format_exc())
                return Unavailable.FAILED
            with self._lock:
                attached = not self.closed
                if attached:
                    self._view = view
            if not attached:
                # Creation may close the owner; a late view must not outlive it.
                view.close()
                return Unavailable.CLOSED
            self.ready.set()
        self._deliver()
        return view

    def close(self, release: Callable[[], None] | None = None) -> bool:
        """Any thread: stop publishing, then release and close the view on its thread once."""
        with self._lock:
            if self.closed:
                return False
            self.closed = True
        self.ready.clear()

        def destroy() -> None:
            try:
                if release is not None:
                    release()
                with self._lock:
                    view, self._view = self._view, None
                if view is not None:
                    view.close()
            finally:
                self.closed_ready.set()

        self._post(destroy)
        return True

    def abandon(self) -> None:
        """The view thread has stopped and will never run the close; confirm closure now."""
        self.closed_ready.set()
