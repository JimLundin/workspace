"""The thread-safe connection to the work view: publication, commands and approval acknowledgement."""

import threading
import traceback
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from assistant.view_publication import Post, Unavailable, ViewPublication, log_view
from assistant.work_commands import AnswerTask, WorkCommand
from assistant.work_snapshot import WorkSnapshot
from automation.execution import ApprovalReview, current_review
from automation.task import ApprovalDecision, answers, requested


class WorkView(Protocol):
    """Widgets are created and called only through the owning UI thread."""

    def render(self, snapshot: WorkSnapshot) -> None: ...
    def show(self, *, focus: bool = True, on_presented: Callable[[], None] | None = None) -> None: ...
    def close(self) -> None: ...


class WorkOpening(Protocol):
    """A native loading presentation, owned and released on the UI thread."""

    def show(self) -> None: ...
    def close(self) -> None: ...


class WorkWindow:
    """Own immutable view state and enqueue rendering without waiting for it."""

    __slots__ = (
        "_create_loading",
        "_loading",
        "_lock",
        "_opening",
        "_presented",
        "_shown",
        "on_command",
        "on_problem",
        "publication",
        "state",
    )

    def __init__(
        self,
        on_command: Callable[[WorkCommand], None],
        *,
        post: Post,
        create_view: Callable[[WorkWindow], WorkView],
        on_problem: Callable[[str], None] | None = None,
        create_loading: Callable[[], WorkOpening] | None = None,
    ) -> None:
        # Commands, dispatch, the durable view, failure reporting and transient
        # loading have independent effect owners; each enters at composition.
        self.on_command, self.on_problem = on_command, on_problem
        self._create_loading: Callable[[], WorkOpening] | None = create_loading
        self._lock = threading.Lock()
        self._opening: bool = False
        self._shown: bool = False
        self._loading: WorkOpening | None = None
        self._presented: ApprovalReview | None = None
        self.state = WorkSnapshot()
        self.publication: ViewPublication[WorkView] = ViewPublication(post, lambda: create_view(self), self._render)

    def publish(self, snapshot: WorkSnapshot) -> None:
        with self._lock:
            if self.publication.closed or snapshot == self.state:
                return
            self.state = snapshot
            if self._presented is not None and not any(current_review(task, snapshot.reviews) == self._presented for task in snapshot.tasks):
                self._presented = None
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
                if self._opening:
                    return
                self._opening = True
                first_open = not self._shown
            try:
                loading = self._create_loading() if first_open and self._create_loading is not None else None
                with self._lock:
                    self._loading = loading
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
                self._shown = True
        self.cancel_show()

    def cancel_show(self, view: WorkView | None = None) -> None:
        """Release transient presentation on its UI thread, including cancellation."""
        if view is not None and not self.publication.holds(view):
            return
        with self._lock:
            loading, self._loading = self._loading, None
        try:
            if loading is not None:
                loading.close()
        finally:
            # Dispatcher shutdown can pump native events. Keep the reveal
            # guard until its transient surface has finished closing.
            with self._lock:
                self._opening = False

    def approval_presented(self, task_id: str, request_id: str) -> bool:
        """The native view acknowledges the exact live preview in its viewport."""
        with self._lock:
            if self.publication.closed:
                return False
            task = next((task for task in self.state.tasks if task.id == task_id), None)
            review = current_review(task, self.state.reviews) if task is not None else None
            if review is None or review.request.id != request_id:
                return False
            self._presented = review
            return True

    def problem(self, message: str) -> None:
        with self._lock:
            if self.publication.closed:
                return
            self.state = replace(self.state, status=message)
        self.publication.changed()
        if self.on_problem is not None:
            self.on_problem(message)

    def send(self, command: WorkCommand) -> bool:
        with self._lock:
            if self.publication.closed:
                return False
            match command:
                case AnswerTask(task_id=task_id, request_id=request_id, answer=answer):
                    task = next((task for task in self.state.tasks if task.id == task_id), None)
                    request = requested(task) if task is not None else None
                    if task is None or request is None or request.id != request_id or not answers(request, answer):
                        return False
                    review = current_review(task, self.state.reviews)
                    if answer is ApprovalDecision.APPROVED and (review is None or review != self._presented):
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
        if self.publication.close(release=self.cancel_show):
            with self._lock:
                self._presented = None
