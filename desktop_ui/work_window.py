"""The thread-safe connection to the work view: publication and commands."""

import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from cell import Cell
from contracts.publication import Post, Unavailable, ViewPublication
from contracts.task import requested
from contracts.work_commands import AnswerTask, WorkViewCommand
from contracts.work_snapshot import WorkSnapshot
from desktop_ui.view_publication import log_view


class WorkView(Protocol):
    """Widgets are created and called only through the owning UI thread."""

    def render(self, snapshot: WorkSnapshot) -> None: ...
    def show(self, *, focus: bool = True, on_presented: Callable[[], None] | None = None) -> None: ...
    def close(self) -> None: ...


class WorkOpening(Protocol):
    """A transient first-open presentation (the wait cursor), owned and released on the UI thread."""

    def show(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _Presented:
    state: WorkSnapshot = field(default_factory=WorkSnapshot)
    opening: bool = False
    """A reveal is in progress; a second one waits for it."""
    shown: bool = False
    """The view has drawn a frame at least once."""
    loading: WorkOpening | None = None


@dataclass(frozen=True, slots=True, weakref_slot=True)
class WorkWindow:
    """Own immutable view state and enqueue rendering without waiting for it."""

    on_command: Callable[[WorkViewCommand], None]
    on_problem: Callable[[str], None] | None
    _create_loading: Callable[[], WorkOpening] | None
    publication: ViewPublication[WorkView]
    _presented: Cell[_Presented] = field(default_factory=lambda: Cell(_Presented()), init=False, repr=False)
    """Replaced whole under the lock."""
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def open(
        cls,
        on_command: Callable[[WorkViewCommand], None],
        *,
        post: Post,
        create_view: Callable[[WorkWindow], WorkView],
        on_problem: Callable[[str], None] | None = None,
        create_loading: Callable[[], WorkOpening] | None = None,
    ) -> WorkWindow:
        # Commands, dispatch, the durable view, failure reporting and transient
        # loading have independent effect owners; each enters at composition.
        # The publication creates and renders the window made just after it.
        def create() -> WorkView:
            return create_view(window)

        def render(view: WorkView | None) -> None:
            window._render(view)

        window = cls(on_command, on_problem, create_loading, ViewPublication(post, create, render, log=log_view))
        return window

    @property
    def state(self) -> WorkSnapshot:
        return self._presented.get().state

    def publish(self, snapshot: WorkSnapshot) -> None:
        with self._lock:
            if self.publication.closed or snapshot == self.state:
                return
            self._presented.update(lambda presented: replace(presented, state=snapshot))
        self.publication.changed()

    def _render(self, view: WorkView | None) -> None:
        with self._lock:
            snapshot = self.state
        if view is not None:
            view.render(snapshot)

    def _prepare(self) -> WorkView | None:
        opened = self.publication.opened()
        match opened:
            case Unavailable.CLOSED:
                return None
            case Unavailable.FAILED:
                self.problem("The work overview could not open. Try Work again; details are in agent-ui.log.")
                return None
            case _:
                return opened

    def prepare(self) -> None:
        """Prepare the native view on its owner thread without showing/focusing it."""

        def prepare() -> None:
            self._prepare()

        self.publication.post(prepare)

    def show(self, *, focus: bool = True) -> None:
        def reveal() -> None:
            with self._lock:
                presented = self._presented.get()
                if presented.opening:
                    return
                self._presented.set(replace(presented, opening=True))
                first_open = not presented.shown
            try:
                loading = self._create_loading() if first_open and self._create_loading is not None else None
                with self._lock:
                    self._presented.update(lambda presented: replace(presented, loading=loading))
                if loading is not None:
                    loading.show()
                view = self._prepare()
                if view is not None:
                    # Native show schedules painting; the presentation owns
                    # loading until its viewport has actually drawn a frame.
                    view.show(focus=focus, on_presented=self._presented_view)
                else:
                    self.cancel_show()
            except BaseException:
                self.cancel_show()
                raise

        self.publication.post(reveal)

    def _presented_view(self) -> None:
        with self._lock:
            if not self.publication.closed:
                self._presented.update(lambda presented: replace(presented, shown=True))
        self.cancel_show()

    def cancel_show(self, view: WorkView | None = None) -> None:
        """Release transient presentation on its UI thread, including cancellation."""
        if view is not None and not self.publication.holds(view):
            return
        with self._lock:
            loading = self._presented.get().loading
            self._presented.update(lambda presented: replace(presented, loading=None))
        try:
            if loading is not None:
                loading.close()
        finally:
            # Dispatcher shutdown can pump native events. Keep the reveal
            # guard until its transient surface has finished closing.
            with self._lock:
                self._presented.update(lambda presented: replace(presented, opening=False))

    def problem(self, message: str) -> None:
        with self._lock:
            if self.publication.closed:
                return
            self._presented.update(lambda presented: replace(presented, state=replace(presented.state, status=message)))
        self.publication.changed()
        if self.on_problem is not None:
            self.on_problem(message)

    def send(self, command: WorkViewCommand) -> bool:
        with self._lock:
            if self.publication.closed:
                return False
            match command:
                case AnswerTask(task_id=task_id, request_id=request_id):
                    task = next((task for task in self.state.tasks if task.id == task_id), None)
                    request = requested(task) if task is not None else None
                    if request is None or request.id != request_id:
                        return False
                case _:
                    pass
        try:
            self.on_command(command)
        except Exception as error:
            log_view(traceback.format_exc())
            self.problem(str(error) or "The work request could not be submitted.")
            return False
        return True

    def close(self) -> None:
        self.publication.close(release=self.cancel_show)
