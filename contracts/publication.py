"""One view per owner: publish from any thread, render on the view's thread, close once.

The owner keeps its immutable state and lock. This lifecycle owns only the view,
its coalesced render and its closure; `create` and `render` run on the view's
thread, reached through `post`.
"""

import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Protocol

from cell import Cell

type Post = Callable[[Callable[[], None]], None]


class Closable(Protocol):
    def close(self) -> None: ...


class Unavailable(Enum):
    CLOSED = auto()
    # Creation raised; the traceback is in agent-ui.log and a later open retries.
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class _Published[V]:
    view: V | None = None
    pending: bool = False
    """A render is posted and has not run yet."""
    closed: bool = False


@dataclass(frozen=True, slots=True)
class ViewPublication[V: Closable]:
    _post: Post
    _create: Callable[[], V]
    _render: Callable[[V | None], None]
    log: Callable[[str], None] = field(kw_only=True)
    _published: Cell[_Published[V]] = field(default_factory=lambda: Cell(_Published[V]()), init=False, repr=False)
    """Replaced whole under the lock."""
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    ready: threading.Event = field(default_factory=threading.Event, init=False)
    """Set while a created view is attached."""
    closed_ready: threading.Event = field(default_factory=threading.Event, init=False)
    """Confirms the view thread released the view."""

    @property
    def closed(self) -> bool:
        return self._published.get().closed

    def post(self, job: Callable[[], None]) -> None:
        """Any thread: run an owner job on the view's thread, unless the view has closed by then."""

        def run() -> None:
            if not self.closed:
                job()

        self._post(run)

    def changed(self) -> None:
        """Any thread: coalesce one render of the owner's latest state."""
        with self._lock:
            published = self._published.get()
            if published.closed or published.pending:
                return
            self._published.set(replace(published, pending=True))
        self._post(self._deliver)

    def _deliver(self) -> None:
        with self._lock:
            published = self._published.update(lambda published: replace(published, pending=False))
        if not published.closed:
            self._render(published.view)

    def holds(self, view: V) -> bool:
        with self._lock:
            return self._published.get().view is view

    def opened(self) -> V | Unavailable:
        """View thread: the view, created on first use and rendered with the latest state."""
        with self._lock:
            published = self._published.get()
            if published.closed:
                return Unavailable.CLOSED
            view = published.view
        if view is None:
            try:
                view = self._create()
            except Exception:
                self.log(traceback.format_exc())
                return Unavailable.FAILED
            with self._lock:
                attached = not self._published.get().closed
                if attached:
                    self._published.update(lambda published: replace(published, view=view))
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
            if self._published.get().closed:
                return False
            self._published.update(lambda published: replace(published, closed=True))
        self.ready.clear()

        def destroy() -> None:
            try:
                if release is not None:
                    release()
                with self._lock:
                    view = self._published.get().view
                    self._published.update(lambda published: replace(published, view=None))
                if view is not None:
                    view.close()
            finally:
                self.closed_ready.set()

        self._post(destroy)
        return True

    def abandon(self) -> None:
        """The view thread has stopped and will never run the close; confirm closure now."""
        self.closed_ready.set()
