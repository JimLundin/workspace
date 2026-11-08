"""Saved work reaches a lazy native view through its public immutable boundary."""

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import replace

from contracts.task import (
    Question,
    RequestSource,
    State,
    Task,
    TaskStatus,
    TextAnswer,
    Waiting,
)
from contracts.work_commands import AnswerTask, Submit, WorkViewCommand
from contracts.work_snapshot import WorkSnapshot
from desktop_ui.work_window import WorkOpening, WorkView, WorkWindow


def work_task(state: State = TaskStatus.READY, *, identity: str = "task-one") -> Task:
    return Task(
        identity, "Prepare the workbook", "Read every sheet and explain the total.", RequestSource("conversation"), 0, 100.0, 200.0, 0, state, None
    )


class RecordingWorkView:
    def __init__(self, *, rendering: Callable[[WorkSnapshot], None] | None = None) -> None:
        self.states: list[WorkSnapshot] = []
        self.shown: list[bool] = []
        self.threads: list[int] = []
        self.closed = False
        self.rendering = rendering

    def render(self, snapshot: WorkSnapshot) -> None:
        if self.rendering is not None:
            self.rendering(snapshot)
        self.states.append(snapshot)
        self.threads.append(threading.get_ident())

    def show(self, *, focus: bool = True, on_presented: Callable[[], None] | None = None) -> None:
        self.shown.append(focus)
        self.threads.append(threading.get_ident())
        if on_presented is not None:
            on_presented()

    def close(self) -> None:
        self.closed = True


class WorkUi:
    def __init__(self, view: RecordingWorkView | None = None) -> None:
        self.jobs: deque[Callable[[], None]] = deque()
        self.view = view or RecordingWorkView()
        self.created = 0
        self.commands: list[WorkViewCommand] = []
        self.problems: list[str] = []
        self.work = WorkWindow.open(self.commands.append, post=self.jobs.append, create_view=self.create, on_problem=self.problems.append)

    def create(self, _work: WorkWindow) -> WorkView:
        self.created += 1
        return self.view

    def paint(self) -> None:
        while self.jobs:
            self.jobs.popleft()()

    def close(self) -> None:
        self.work.close()
        self.paint()


class RecordingOpening:
    def __init__(self) -> None:
        self.visible = False
        self.closed = False

    def show(self) -> None:
        self.visible = True

    def close(self) -> None:
        self.visible = False
        self.closed = True


class DeferredWorkView(RecordingWorkView):
    def __init__(self) -> None:
        super().__init__()
        self.on_presented: Callable[[], None] | None = None

    def show(self, *, focus: bool = True, on_presented: Callable[[], None] | None = None) -> None:
        super().show(focus=focus)
        self.on_presented = on_presented

    def paint_frame(self) -> None:
        ready, self.on_presented = self.on_presented, None
        assert ready is not None
        ready()


def test_loading_remains_until_the_view_presents_its_first_frame() -> None:
    # Defect: show() returns before Qt's first paint, and disposing loading at
    # that point leaves a blank interval before the canvas becomes visible.
    jobs: deque[Callable[[], None]] = deque()
    view = DeferredWorkView()
    loading = RecordingOpening()
    work = WorkWindow.open(lambda _: None, post=jobs.append, create_view=lambda _: view, create_loading=lambda: loading)
    try:
        work.show(focus=False)
        while jobs:
            jobs.popleft()()
        assert loading.visible and not loading.closed
        # Defect: hiding a replaced view releases the loading surface of the current one.
        work.cancel_show(DeferredWorkView())
        assert loading.visible and not loading.closed
        view.paint_frame()
        assert (loading.closed, loading.visible) == (True, False)
    finally:
        work.close()
        while jobs:
            jobs.popleft()()


def test_closing_before_first_paint_releases_pending_loading() -> None:
    # Defect: transferring loading ownership to a paint callback leaks it if
    # the native view is destroyed before that callback can run.
    jobs: deque[Callable[[], None]] = deque()
    view = DeferredWorkView()
    loading = RecordingOpening()
    work = WorkWindow.open(lambda _: None, post=jobs.append, create_view=lambda _: view, create_loading=lambda: loading)
    work.show(focus=False)
    while jobs:
        jobs.popleft()()
    assert loading.visible
    work.close()
    while jobs:
        jobs.popleft()()
    assert loading.closed and view.closed and work.publication.closed_ready.is_set()


def test_first_open_loading_precedes_creation_and_rendering_and_cleans_up_on_retry() -> None:
    # Defect: loading starts after expensive setup, survives failure, appears
    # during hidden preparation, or is recreated on ordinary canvas reopen.
    jobs: deque[Callable[[], None]] = deque()
    openings: list[RecordingOpening] = []
    errors: list[str] = []
    attempts = 0

    def opening() -> WorkOpening:
        result = RecordingOpening()
        openings.append(result)
        return result

    def render(_snapshot: WorkSnapshot) -> None:
        if not view.states:
            assert openings[-1].visible

    view = RecordingWorkView(rendering=render)

    def create(_work: WorkWindow) -> WorkView:
        nonlocal attempts
        attempts += 1
        assert openings[-1].visible
        if attempts == 1:
            raise RuntimeError("Fixture native view unavailable")
        return view

    work = WorkWindow.open(lambda _: None, post=jobs.append, create_view=create, on_problem=errors.append, create_loading=opening)
    work.show(focus=False)
    while jobs:
        jobs.popleft()()
    assert len(errors) == 1 and openings[0].closed and not openings[0].visible
    work.show(focus=False)
    while jobs:
        jobs.popleft()()
    assert view.shown == [False] and len(openings) == 2 and openings[1].closed
    # Once open, a normal reveal reuses the view and has no loading interlude.
    work.show(focus=False)
    while jobs:
        jobs.popleft()()
    assert view.shown == [False, False] and attempts == 2 and len(openings) == 2
    work.close()
    while jobs:
        jobs.popleft()()

    hidden = WorkWindow.open(lambda _: None, post=jobs.append, create_view=lambda _: RecordingWorkView(), create_loading=opening)
    hidden.prepare()
    while jobs:
        jobs.popleft()()
    assert len(openings) == 2
    hidden.close()
    while jobs:
        jobs.popleft()()


def test_loading_event_delivery_cannot_create_a_second_view() -> None:
    # Defect: delivering the native loading frame reenters reveal and creates
    # another loading window/view before the first factory attaches its view.
    jobs: deque[Callable[[], None]] = deque()
    creations: list[WorkView] = []

    class ReentrantOpening(RecordingOpening):
        def show(self) -> None:
            super().show()
            work.show(focus=False)
            jobs.popleft()()

    loading = ReentrantOpening()

    def create(_work: WorkWindow) -> WorkView:
        result = RecordingWorkView()
        creations.append(result)
        return result

    work = WorkWindow.open(lambda _: None, post=jobs.append, create_view=create, create_loading=lambda: loading)
    work.show(focus=False)
    while jobs:
        jobs.popleft()()
    assert len(creations) == 1 and loading.closed
    work.close()
    while jobs:
        jobs.popleft()()


def test_startup_preparation_reuses_the_hidden_view_and_latest_snapshot() -> None:
    # Defect: startup preparation reveals/focuses the desktop canvas, creates
    # duplicate views, or renders a stale publication when the user opens it.
    ui = WorkUi()
    ui.work.publish(WorkSnapshot(status="Saved work"))
    ui.work.prepare()
    ui.work.publish(WorkSnapshot(status="Latest work"))
    ui.paint()
    assert ui.created == 1 and not ui.view.shown
    assert ui.view.states[-1].status == "Latest work"
    # Defect: an unchanged poll re-renders the whole native view.
    ui.work.publish(WorkSnapshot(status="Latest work"))
    assert not ui.jobs
    ui.work.show(focus=False)
    ui.paint()
    assert ui.created == 1 and ui.view.shown == [False]
    ui.close()
    assert ui.view.closed and not ui.work.send(Submit("Too late")) and not ui.commands


def test_question_answers_require_the_exact_current_task_request() -> None:
    ui = WorkUi()
    task = work_task(Waiting(Question("question-one", "Which sheet?", "Choose the source.")))
    ui.work.publish(WorkSnapshot(tasks=(task,)))
    assert not ui.work.send(AnswerTask("another-task", "question-one", TextAnswer("Revenue")))
    assert not ui.work.send(AnswerTask(task.id, "question-two", TextAnswer("Revenue")))
    answer = AnswerTask(task.id, "question-one", TextAnswer("Revenue\nwith the complete ending. Åäö."))
    assert ui.work.send(answer) and ui.commands == [answer]
    replacement = replace(task, state=Waiting(Question("question-two", "Which year?", "")), revision=1)
    ui.work.publish(WorkSnapshot(tasks=(replacement,)))
    assert not ui.work.send(answer)
    latest = AnswerTask(task.id, "question-two", TextAnswer("2026"))
    assert ui.work.send(latest) and ui.commands == [answer, latest]
    ui.work.publish(WorkSnapshot(tasks=(replace(replacement, state=TaskStatus.READY),)))
    assert not ui.work.send(latest)
    ui.close()


def test_command_failure_reports_a_problem_without_discarding_current_tasks() -> None:
    errors: list[str] = []

    def reject(_command: WorkViewCommand) -> None:
        raise RuntimeError("Work process unavailable")

    work = WorkWindow.open(reject, post=lambda _: None, create_view=lambda _: RecordingWorkView(), on_problem=errors.append)
    snapshot = WorkSnapshot(tasks=(work_task(),))
    work.publish(snapshot)
    assert not work.send(Submit("Read the workbook"))
    assert errors == ["Work process unavailable"] and work.state.status == errors[0]
    assert work.state.tasks == snapshot.tasks
