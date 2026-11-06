"""The session schedules painting without blocking model work or revealing a window."""

import threading
from collections import deque
from collections.abc import Callable

from assistant.agent_window import AgentWindow, View
from contracts.agent_session import Snapshot, pending
from contracts.presentation import Answer, StreamState
from contracts.recording_state import RecordingAction
from contracts.task import TextAnswer
from tests.agent_requests import asked, body


class RecordingView:
    __slots__ = ("closed", "shown", "states", "threads")

    def __init__(self) -> None:
        self.states: list[Snapshot] = []
        self.shown: list[bool] = []
        self.threads: list[int] = []
        self.closed = False

    def render(self, state: Snapshot) -> None:
        self.states.append(state)
        self.threads.append(threading.get_ident())

    def show(self, *, focus: bool = False) -> None:
        self.shown.append(focus)
        self.threads.append(threading.get_ident())

    def close(self) -> None:
        self.closed = True


class RecordingWindow(AgentWindow):
    """Keep the real session controller; replace only the UI thread and widgets."""

    __slots__ = ("jobs", "view")

    def __init__(  # noqa: PLR0913 - mirrors AgentWindow callbacks
        self,
        stop: Callable[[], None],
        *,
        post: Callable[[Callable[[], None]], None] | None = None,
        create_view: Callable[[AgentWindow], View] | None = None,
        on_problem: Callable[[str], None] | None = None,
        on_reset: Callable[[], bool] | None = None,
        on_submit: Callable[[str], None] | None = None,
        on_waiting: Callable[[bool], None] | None = None,
        on_recording: Callable[[RecordingAction], None] | None = None,
    ) -> None:
        self.view = RecordingView()
        self.jobs: deque[Callable[[], None]] = deque()
        super().__init__(
            stop,
            post=self.jobs.append,
            create_view=lambda agent: self.view,
            log=lambda _text: None,
            on_problem=on_problem,
            on_reset=on_reset,
            on_submit=on_submit,
            on_waiting=on_waiting,
            on_recording=on_recording,
        )

    def paint(self) -> None:
        while self.jobs:
            self.jobs.popleft()()


def test_background_activity_and_queued_turns_do_not_show_or_focus_the_panel() -> None:
    panel = RecordingWindow(lambda: None)
    panel.begin("Find the workbook")
    panel.step("Looking for files")
    panel.say("I found it.")
    panel.queued("Open that one")
    panel.problem("The workbook is temporarily unavailable.")
    panel.done("Try again later.")
    panel.finish()
    assert not panel.view.states, "Painting must wait for the UI thread."
    panel.paint()
    assert panel.view.states and not panel.view.shown
    assert "Find the workbook" in panel.all_text()
    assert "Try again later." in panel.all_text()
    panel.show()
    panel.show(focus=True)
    panel.paint()
    assert panel.view.shown == [False, True]
    panel.close()
    panel.paint()
    assert panel.view.closed


def test_explicit_ui_actions_reach_the_existing_session_callbacks() -> None:
    submitted: list[str] = []
    commands: list[str] = []

    def reset() -> bool:
        commands.append("new")
        return True

    panel = RecordingWindow(lambda: commands.append("stop"), on_submit=submitted.append, on_reset=reset)
    assert panel.submit("Open my workbook\nwith the complete ending")
    assert not panel.submit("  ")
    panel.stop()
    assert panel.new()
    assert submitted == ["Open my workbook\nwith the complete ending"]
    assert commands == ["stop", "new"]
    panel.begin("Working")
    assert not panel.new(), "New chat is unavailable until the current turn finishes."
    panel.stopping()
    assert not panel.submit("Keep this draft until stopping finishes")
    panel.close()
    panel.paint()


def test_live_publishers_cannot_update_a_later_turn_or_a_reset_conversation() -> None:
    panel = RecordingWindow(lambda: None)
    panel.begin("First task")
    first = panel.updates()
    first(Answer("same-id", "First answer", 1, StreamState.COMPLETE))
    panel.finish()
    panel.begin("Next task")
    second = panel.updates()
    panel.paint()
    before = panel.snapshot()
    first(Answer("late", "This belongs to the first request", 2))
    assert panel.snapshot() is before and not panel.jobs
    second(Answer("second-answer", "Second answer", 3))
    assert body(panel.snapshot().messages[-1]) == "Second answer"
    panel.reset()
    panel.begin("Fresh conversation")
    before = panel.snapshot()
    second(Answer("late", "This belongs to the old conversation", 4))
    assert panel.snapshot() is before and len(panel.snapshot().messages) == 1
    panel.close()
    panel.paint()


def test_quitting_during_ui_warmup_withdraws_requests_and_never_creates_a_late_window() -> None:
    panel = RecordingWindow(lambda: None)
    panel.show()
    panel.request_input(asked("open", "Open this?", "budget.xlsx", 1), lambda _reply: True)
    panel.close()
    assert not panel.respond("open", TextAnswer("Yes"))
    panel.paint()
    assert not panel.view.states and not panel.view.shown and not panel.publication.ready.is_set()


def test_captured_session_replies_cannot_enter_a_reprojected_request_with_the_same_id() -> None:
    # Defect: a canvas reply admitted after a session reset reaches a later
    # conversation that reused the same durable request id.
    delivered: list[TextAnswer] = []

    def accept(reply: TextAnswer) -> bool:
        match reply:
            case TextAnswer():
                delivered.append(reply)
                return True
            case _:
                return False

    panel = RecordingWindow(lambda: None)
    try:
        panel.request_input(asked("same", "Which owner?", "", 1), accept)
        captured = panel.snapshot()
        panel.reset()
        panel.request_input(asked("same", "Which sheet?", "", 2), accept)
        answer = TextAnswer("Revenue")
        assert not panel.respond("same", answer, expected_session=captured.identity)
        assert not delivered and panel.snapshot().waiting
        assert panel.respond("same", answer, expected_session=panel.snapshot().identity)
        assert delivered == [answer] and not panel.snapshot().waiting
    finally:
        panel.close()
        panel.paint()


def test_failed_widget_startup_reports_the_problem_and_can_be_retried() -> None:
    jobs: deque[Callable[[], None]] = deque()
    problems: list[str] = []
    view = RecordingView()
    attempts = 0

    def create(panel: AgentWindow) -> View:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Fixture: window initialization failed")
        return view

    panel = AgentWindow(lambda: None, post=jobs.append, create_view=create, on_problem=problems.append, log=lambda _text: None)
    while jobs:
        jobs.popleft()()
    assert len(problems) == 1 and not panel.publication.ready.is_set()
    panel.show()
    while jobs:
        jobs.popleft()()
    assert panel.publication.ready.is_set() and view.shown == [False]
    panel.close()
    while jobs:
        jobs.popleft()()


def test_snapshot_renders_follow_the_ui_queue_and_stop_after_close() -> None:
    # Defect: snapshot publication bypasses the UI queue or runs after close.
    # The fixture owns the event-loop FIFO while callbacks enqueue work.
    jobs: deque[Callable[[], None]] = deque()
    view = RecordingView()

    def observed_counts() -> tuple[int, ...]:
        return tuple(sum(pending(message) for message in state.messages) for state in view.states)

    panel = AgentWindow(lambda: None, post=jobs.append, create_view=lambda _: view, log=lambda _text: None)
    try:
        while jobs:
            jobs.popleft()()
        assert observed_counts() == (0,)
        panel.request_input(asked("owned", "Which sheet?", "", 1), lambda _: True)
        assert observed_counts() == (0,)
        while jobs:
            jobs.popleft()()
        assert observed_counts() == (0, 1)
        assert panel.respond("owned", TextAnswer("Revenue"))
        while jobs:
            jobs.popleft()()
        assert observed_counts() == (0, 1, 0)
        panel.request_input(asked("late", "Another sheet?", "", 2), lambda _: True)
    finally:
        panel.close()
        while jobs:
            jobs.popleft()()
    assert observed_counts() == (0, 1, 0)
