"""Durable input uses the same exact-request seam for native, typed, and voice replies."""

import contextlib
import threading
from collections import deque
from collections.abc import Callable

from assistant.agent_session import AgentRequest, pending
from assistant.agent_window import AgentWindow, View
from automation.task import ApprovalDecision, Reply, TextAnswer
from tests.agent_requests import asked, reviewed
from tests.test_agent_window import RecordingWindow


def has_pending_input(panel: AgentWindow) -> bool:
    return panel.waiting


def test_durable_questions_share_typed_voice_and_button_routing_without_waiting_threads() -> None:
    replies: list[Reply] = []
    submitted: list[str] = []
    waiting: list[bool] = []

    def accept(answer: Reply) -> bool:
        replies.append(answer)
        return True

    panel = RecordingWindow(lambda: None, on_submit=submitted.append, on_waiting=waiting.append)
    assert not panel.reply_by_voice("Start a task")
    first = asked("first", "Which workbook?", "Choose the source.", 1.0)
    panel.request_input(first, accept)
    panel.request_input(first, accept)
    assert sum(isinstance(message, AgentRequest) for message in panel.state.messages) == 1
    assert has_pending_input(panel) and panel.submit("Revenue\nwith the full ending. Åäö.")
    panel.request_input(first, accept)
    assert not has_pending_input(panel) and not panel.respond("first", TextAnswer("A duplicate answer"))
    panel.request_input(asked("second", "Which sheet?", "", 2.0), accept)
    assert panel.reply_by_voice("The 2026 sheet.")
    panel.request_input(asked("third", "Which column?", "", 3.0), accept)
    assert panel.respond("third", TextAnswer("Actual revenue"))
    assert replies == [TextAnswer("Revenue\nwith the full ending. Åäö."), TextAnswer("The 2026 sheet."), TextAnswer("Actual revenue")]
    assert not submitted and waiting == [True, False, True, False, True, False]
    panel.request_input(asked("fourth", "Still needed?", "", 4.0), accept)
    assert has_pending_input(panel)
    panel.withdraw_input()
    assert not has_pending_input(panel) and panel.submit("Start a follow-up") and submitted == ["Start a follow-up"]
    panel.begin("Find the workbook", lambda: None)
    panel.request_input(asked("fifth", "Which year?", "", 5.0), accept)
    panel.stopping()
    assert not has_pending_input(panel) and not panel.respond("fifth", TextAnswer("Too late"))
    # Defect: speech while stopping becomes a new task instead of being consumed.
    assert panel.reply_by_voice("Start another task") and submitted == ["Start a follow-up"]
    panel.close()
    panel.paint()


def test_a_new_request_during_reply_submission_remains_pending() -> None:
    replies: list[tuple[str, Reply]] = []
    panel = RecordingWindow(lambda: None)
    latest = asked("new", "Which year?", "", 2.0)

    def answer_new(answer: Reply) -> bool:
        replies.append(("new", answer))
        return True

    def answer_old(answer: Reply) -> bool:
        replies.append(("old", answer))
        panel.request_input(latest, answer_new)
        return True

    panel.request_input(asked("old", "Which workbook?", "", 1.0), answer_old)
    assert panel.respond("old", TextAnswer("Revenue"))
    assert panel.state.request == latest and has_pending_input(panel)
    assert not panel.respond("old", TextAnswer("A late answer")) and panel.state.request == latest
    assert panel.submit("2026")
    assert replies == [("old", TextAnswer("Revenue")), ("new", TextAnswer("2026"))] and not has_pending_input(panel)
    panel.close()
    panel.paint()


def test_a_restored_request_stays_pending_when_the_prior_submission_returns() -> None:
    replies: list[Reply] = []
    panel = RecordingWindow(lambda: None)
    question = asked("retry", "Which workbook?", "The previous answer could not be saved.", 1.0)

    def retry(answer: Reply) -> bool:
        replies.append(answer)
        return True

    def failed_commit(answer: Reply) -> bool:
        replies.append(answer)
        panel.withdraw_input()
        panel.request_input(question, retry)
        return True

    panel.request_input(question, failed_commit)
    assert panel.respond(question.id, TextAnswer("Revenue"))
    assert panel.state.request == question and has_pending_input(panel)
    assert panel.submit("The revenue workbook")
    assert replies == [TextAnswer("Revenue"), TextAnswer("The revenue workbook")] and not has_pending_input(panel)
    panel.close()
    panel.paint()


def test_duplicate_polling_and_simultaneous_replies_cannot_submit_twice() -> None:
    entered, release = threading.Event(), threading.Event()
    replies: list[Reply] = []
    accepted: list[bool] = []
    panel = RecordingWindow(lambda: None)
    question = asked("one", "Which workbook?", "", 1.0)

    def accept(answer: Reply) -> bool:
        replies.append(answer)
        entered.set()
        assert release.wait(timeout=3)
        return True

    panel.request_input(question, accept)
    sender = threading.Thread(target=lambda: accepted.append(panel.respond("one", TextAnswer("Revenue"))))
    sender.start()
    try:
        assert entered.wait(timeout=2)
        panel.request_input(question, accept)
        assert not panel.respond("one", TextAnswer("Second answer"))
    finally:
        release.set()
        sender.join(timeout=2)
    assert not sender.is_alive() and accepted == [True]
    panel.request_input(question, accept)
    assert not has_pending_input(panel) and not panel.respond("one", TextAnswer("Third answer"))
    assert replies == [TextAnswer("Revenue")]
    panel.close()
    panel.paint()


def test_rejected_replies_can_retry_without_resolving_or_reopening_the_request() -> None:
    replies: list[Reply] = []
    panel = RecordingWindow(lambda: None)
    request = reviewed("approval", "Write the workbook", "The full reviewed content.", 1.0)

    def accept(answer: Reply) -> bool:
        replies.append(answer)
        if len(replies) == 1:
            raise RuntimeError("Fixture: the work queue refused the reply.")
        return len(replies) > 2

    panel.request_input(request, accept)
    panel.input_presented(request.id)
    # Defect: a reply sink that raises leaves the request submitted and unanswerable.
    with contextlib.suppress(RuntimeError):
        panel.respond(request.id, ApprovalDecision.APPROVED)
    assert not panel.respond(request.id, ApprovalDecision.APPROVED) and has_pending_input(panel)
    assert panel.respond(request.id, ApprovalDecision.APPROVED) and not has_pending_input(panel)
    assert replies == [ApprovalDecision.APPROVED] * 3
    panel.request_input(request, accept)
    assert not has_pending_input(panel)
    panel.close()
    panel.paint()


def test_approval_requires_its_exact_native_display_and_never_accepts_partial_voice_matches() -> None:
    replies: list[Reply] = []

    def accept(answer: Reply) -> bool:
        replies.append(answer)
        return True

    panel = RecordingWindow(lambda: None)
    first = reviewed("first", "Write the workbook", "The first preview.", 1.0)
    panel.request_input(first, accept)
    assert panel.reply_by_voice("Approve!") and not replies
    panel.paint()
    assert not panel.respond("first", ApprovalDecision.APPROVED), "An enqueued render does not establish visible native content."
    panel.input_presented("stale")
    assert not panel.respond("first", ApprovalDecision.APPROVED)
    panel.input_presented("first")
    assert panel.reply_by_voice("Do not approve this") and not replies
    assert panel.reply_by_voice("  APPROVE. ") and replies == [ApprovalDecision.APPROVED]
    panel.request_input(reviewed("second", "Send the draft", "Another complete preview.", 2.0), accept)
    panel.input_presented("first")
    assert not panel.respond("second", ApprovalDecision.APPROVED)
    assert panel.reply_by_voice("Decline!") and replies == [ApprovalDecision.APPROVED, ApprovalDecision.DECLINED]
    panel.request_input(reviewed("third", "Write again", "Fresh preview.", 3.0), accept)
    panel.reset()
    panel.input_presented("third")
    assert not panel.respond("third", ApprovalDecision.APPROVED)
    panel.request_input(reviewed("fourth", "Write again", "Fresh preview.", 4.0), accept)
    assert not panel.respond("fourth", ApprovalDecision.APPROVED)
    panel.close()
    panel.input_presented("fourth")
    assert not panel.respond("fourth", ApprovalDecision.APPROVED) and replies == [ApprovalDecision.APPROVED, ApprovalDecision.DECLINED]
    panel.paint()


def test_failed_native_creation_never_authorizes_a_projected_approval() -> None:
    jobs: deque[Callable[[], None]] = deque()
    replies: list[Reply] = []
    errors: list[str] = []

    def create(_agent: AgentWindow) -> View:
        raise RuntimeError("Fixture native view unavailable")

    def accept(answer: Reply) -> bool:
        replies.append(answer)
        return True

    panel = AgentWindow(lambda: None, post=jobs.append, create_view=create, on_problem=errors.append)
    panel.request_input(reviewed("approval", "Write the workbook", "Complete preview.", 1.0), accept)
    while jobs:
        jobs.popleft()()
    assert errors and not panel.ready.is_set()
    assert not panel.respond("approval", ApprovalDecision.APPROVED) and not replies
    assert any(isinstance(message, AgentRequest) and pending(message) for message in panel.state.messages)
    panel.close()
    while jobs:
        jobs.popleft()()
