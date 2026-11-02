"""Where desktop attention goes, decided from immutable owner observations.

These are Workspace policies; no general-purpose state-machine dependency can
choose our speech, inbox, interruption or request-identity rules. Qt and delivery
effects remain with the views and Ui.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import assert_never

from assistant.canvas_activity import CanvasQuestion, CanvasRequest, SessionRequest, TaskRequest
from assistant.work_commands import AnswerTask
from automation.task import TextAnswer
from desktop_ui.work_canvas import Announcement


@dataclass(frozen=True, slots=True, kw_only=True)
class CanvasFocus:
    selected: str | None
    visible: bool
    active: bool


@dataclass(frozen=True, slots=True)
class AnswerQuestion:
    request: CanvasRequest


class Speech(Enum):
    INSTRUCT = "instruct"
    CONVERSATION = "conversation"


type SpeechTarget = AnswerQuestion | Speech


def speech_target(waiting: Sequence[CanvasQuestion], focus: CanvasFocus | None) -> SpeechTarget:
    """Only a selected waiting question consumes a reply; hidden canvases yield speech."""
    match focus:
        case None | CanvasFocus(visible=False):
            return Speech.CONVERSATION
        case CanvasFocus(selected=selected):
            question = next((item for item in waiting if item.id == selected), None)
            return AnswerQuestion(question.request) if question is not None else Speech.INSTRUCT
        case _:
            assert_never(focus)


@dataclass(frozen=True, slots=True)
class OpenQuestion:
    identity: str


class Inbox(Enum):
    WORK = "work"
    CONVERSATION = "conversation"


type InboxTarget = OpenQuestion | Inbox


def inbox_target(waiting: Sequence[CanvasQuestion], *, work_open: bool) -> InboxTarget:
    """The first waiting question precedes the existing work window and conversation."""
    if waiting:
        return OpenQuestion(waiting[0].id)
    return Inbox.WORK if work_open else Inbox.CONVERSATION


def interrupts(notice: Announcement | None, focus: CanvasFocus | None) -> Announcement | None:
    """The active canvas already presents its changes without a desktop announcement."""
    match focus:
        case CanvasFocus(active=True):
            return None
        case None | CanvasFocus():
            return notice
        case _:
            assert_never(focus)


@dataclass(frozen=True, slots=True)
class ToSession:
    session_id: str
    request_id: str


@dataclass(frozen=True, slots=True)
class ToTask:
    command: AnswerTask


class Undeliverable(Enum):
    STALE = "stale"


type Delivery = ToSession | ToTask | Undeliverable


def delivery(request: CanvasRequest, answer: TextAnswer, session: str | None) -> Delivery:
    """A conversation reply must still belong to the observed session."""
    match request:
        case SessionRequest(session_id=identity, request_id=key):
            return ToSession(identity, key) if identity == session else Undeliverable.STALE
        case TaskRequest(task_id=task, request_id=key):
            return ToTask(AnswerTask(task, key, answer))
        case _:
            assert_never(request)
