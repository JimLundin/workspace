"""Desktop attention policy from immutable observations, without native views."""

from dataclasses import replace

from assistant.canvas_activity import Attention, CanvasQuestion, SessionRequest, TaskRequest
from assistant.work_commands import AnswerTask
from automation.task import TextAnswer
from desktop_ui.desktop_attention import (
    AnswerQuestion,
    CanvasFocus,
    Inbox,
    OpenQuestion,
    Speech,
    ToSession,
    ToTask,
    Undeliverable,
    delivery,
    inbox_target,
    interrupts,
    speech_target,
)
from desktop_ui.work_canvas import Announcement


def questions() -> tuple[CanvasQuestion, CanvasQuestion]:
    return (
        CanvasQuestion("question:first", "First", "Which sheet?", 1, SessionRequest("session", "first"), Attention.WAITING),
        CanvasQuestion("question:second", "Second", "Which owner?", 2, TaskRequest("task", "second"), Attention.WAITING),
    )


def test_speech_answers_only_the_selected_waiting_question_and_yields_when_hidden() -> None:
    # Defect: speech answers a different waiting question, loses a selected task
    # request, or instructs a hidden/uncreated canvas instead of the conversation.
    waiting = questions()
    focus = CanvasFocus(selected=waiting[1].id, visible=True, active=False)
    assert speech_target(waiting, focus) == AnswerQuestion(waiting[1].request)
    assert speech_target(waiting, replace(focus, selected=waiting[0].id)) == AnswerQuestion(waiting[0].request)
    assert speech_target(waiting, replace(focus, selected="work:one")) is Speech.INSTRUCT
    assert speech_target(waiting, replace(focus, selected=None)) is Speech.INSTRUCT
    assert speech_target((), focus) is Speech.INSTRUCT
    assert speech_target(waiting, replace(focus, visible=False)) is Speech.CONVERSATION
    assert speech_target(waiting, None) is Speech.CONVERSATION


def test_inbox_opens_the_first_question_before_existing_work_or_conversation() -> None:
    # Defect: inbox chooses the later question, ignores questions before work
    # exists, or opens the conversation despite an existing work window.
    waiting = questions()
    assert inbox_target(waiting, work_open=True) == OpenQuestion(waiting[0].id)
    assert inbox_target(waiting, work_open=False) == OpenQuestion(waiting[0].id)
    assert inbox_target(tuple(reversed(waiting)), work_open=True) == OpenQuestion(waiting[1].id)
    assert inbox_target((), work_open=True) is Inbox.WORK
    assert inbox_target((), work_open=False) is Inbox.CONVERSATION


def test_notices_interrupt_only_when_the_canvas_is_not_active() -> None:
    # Defect: an active canvas duplicates its change with a desktop notice,
    # or a visible but inactive canvas suppresses an interruption it must show.
    notice = Announcement("Ready", "result:task")
    focus = CanvasFocus(selected=None, visible=True, active=True)
    assert interrupts(notice, focus) is None
    assert interrupts(notice, replace(focus, active=False)) == notice
    assert interrupts(notice, replace(focus, visible=False, active=False)) == notice
    assert interrupts(notice, None) == notice
    assert interrupts(None, None) is None


def test_answers_preserve_task_identity_and_reject_an_earlier_conversation() -> None:
    # Defect: an earlier session's request reaches the current conversation,
    # or task delivery changes the request/task identity or answer payload.
    answer = TextAnswer("Revenue")
    request = SessionRequest("session", "first")
    assert delivery(request, answer, "session") == ToSession("session", "first")
    assert delivery(request, answer, "later") is Undeliverable.STALE
    assert delivery(request, answer, None) is Undeliverable.STALE
    assert delivery(TaskRequest("task", "second"), answer, None) == ToTask(AnswerTask("task", "second", answer))
    assert delivery(TaskRequest("task", "second"), answer, "session") == ToTask(AnswerTask("task", "second", answer))
