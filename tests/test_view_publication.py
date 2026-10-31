"""Publication reaches one lazily created view on its own thread, and closing it is confirmed once."""

import threading
from collections import deque
from collections.abc import Callable

from assistant.view_publication import Unavailable, ViewPublication


class RecordingView:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class ViewThread:
    """The view thread's FIFO, drained explicitly by the test."""

    def __init__(self) -> None:
        self.jobs: deque[Callable[[], None]] = deque()

    def run(self) -> None:
        while self.jobs:
            self.jobs.popleft()()


def test_changes_from_any_thread_coalesce_into_one_render_on_the_view_thread() -> None:
    # Defect: a producer thread renders widgets itself, waits on a slow render,
    # or queues one render per change.
    thread = ViewThread()
    renders: list[tuple[RecordingView | None, int]] = []
    release, rendering = threading.Event(), threading.Event()

    def render(view: RecordingView | None) -> None:
        renders.append((view, threading.get_ident()))
        if len(renders) == 2:
            rendering.set()
            assert release.wait(timeout=3)

    view = RecordingView()
    publication = ViewPublication(thread.jobs.append, lambda: view, render)
    assert publication.opened() is view and renders == [(view, threading.get_ident())]
    producer = threading.Thread(target=lambda: [publication.changed() for _ in range(100)])
    producer.start()
    producer.join(timeout=2)
    assert not producer.is_alive() and len(thread.jobs) == 1
    painter = threading.Thread(target=thread.run)
    painter.start()
    assert rendering.wait(timeout=2)
    publication.changed()  # A slow render holds no lock that publishing needs.
    release.set()
    painter.join(timeout=2)
    # The change made during the slow render is rendered next, on the view thread.
    assert not painter.is_alive() and [owner for _, owner in renders] == [threading.get_ident(), painter.ident, painter.ident]


def test_creation_is_lazy_retries_after_failure_and_never_outlives_a_close() -> None:
    # Defect: publishing creates the view, a failed creation is final, or a
    # view created while its owner closes stays open.
    thread = ViewThread()
    attempts: list[RecordingView] = []

    def create() -> RecordingView:
        if not attempts:
            attempts.append(RecordingView())
            raise RuntimeError("Fixture: native view unavailable")
        attempts.append(RecordingView())
        return attempts[-1]

    publication = ViewPublication(thread.jobs.append, create, lambda _view: None)
    publication.changed()
    thread.run()
    assert not attempts and not publication.ready.is_set()
    assert publication.opened() is Unavailable.FAILED and not publication.ready.is_set()
    assert publication.opened() is attempts[1] and publication.ready.is_set()
    assert publication.opened() is attempts[1]

    late = RecordingView()
    closing: ViewPublication[RecordingView]

    def closed_during_creation() -> RecordingView:
        closing.close()
        return late

    closing = ViewPublication(thread.jobs.append, closed_during_creation, lambda _view: None)
    assert closing.opened() is Unavailable.CLOSED and late.closed and not closing.ready.is_set()
    thread.run()
    assert closing.closed_ready.is_set()


def test_close_releases_then_closes_the_view_once_and_confirms_after_the_view_thread_runs() -> None:
    # Defect: closure is confirmed before the view is released, runs twice, or
    # queued renders and owner jobs still run after close.
    thread = ViewThread()
    events: list[str] = []
    view = RecordingView()
    publication = ViewPublication(thread.jobs.append, lambda: view, lambda _view: events.append("render"))
    assert publication.opened() is view and events == ["render"]
    events.clear()
    publication.changed()
    publication.post(lambda: events.append("job"))
    assert publication.close(lambda: events.append("release" if not view.closed else "late release"))
    assert not publication.close() and not publication.closed_ready.is_set() and not publication.ready.is_set()
    publication.changed()
    thread.run()
    assert events == ["release"] and view.closed and publication.closed_ready.is_set()
    assert publication.opened() is Unavailable.CLOSED
