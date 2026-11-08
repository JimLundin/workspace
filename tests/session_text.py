"""The text a test reads off an agent session: each message's speaker, words and outcome."""

from typing import assert_never

from contracts import action_text
from contracts.agent_session import (
    AgentRequest,
    Answer,
    Cancelled,
    ChatMessage,
    Failed,
    MeetingMessage,
    Message,
    Pending,
    ReasoningSummary,
    RequestReply,
    Session,
    Succeeded,
    TextAnswer,
    ToolActivity,
    ToolStatus,
)


def all_text(session: Session) -> str:
    return "\n\n".join(message_text(message) for message in session.messages)


def message_text(message: Message) -> str:
    parts: tuple[str, ...]
    match message:
        case ChatMessage(speaker, text):
            parts = (speaker, text)
        case Answer(text=text):
            parts = ("Workspace", text)
        case ReasoningSummary(text=text):
            parts = ("Reasoning summary", text)
        case ToolActivity(name=name):
            parts = (name, activity_text(message))
        case MeetingMessage(text=text):
            parts = ("Meeting", text)
        case AgentRequest(detail=detail, reply=TextAnswer(answer)):
            parts = ("You", message.text, detail, "answered", answer)
        case AgentRequest(detail=detail, reply=reply):
            parts = ("You", message.text, detail, reply_text(reply))
        case _:
            assert_never(message)
    return "\n".join(part for part in parts if part)


def reply_text(reply: RequestReply) -> str:
    match reply:
        case Pending():
            return "pending"
        case TextAnswer(text):
            return text
        case Cancelled():
            return "cancelled"
        case _:
            assert_never(reply)


def activity_text(activity: ToolActivity) -> str:
    detail = action_text.arguments(activity.name, activity.detail)
    match activity.outcome:
        case ToolStatus.RUNNING | ToolStatus.CANCELLED:
            return detail
        case Succeeded(text):
            return "\n".join(part for part in (detail, action_text.result(activity.name, text)) if part)
        case Failed(text):
            return "\n".join(part for part in (detail, action_text.readable(text)) if part)
        case _:
            assert_never(activity.outcome)
