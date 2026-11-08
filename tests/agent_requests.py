"""Timeline projections of durable agent questions, and timeline text, for conversation and UI fixtures."""

from contracts.agent_session import AgentRequest, Message
from contracts.presentation import ToolActivity
from contracts.task import Question
from tests.session_text import activity_text


def asked(identity: str, text: str, detail: str, at: float) -> AgentRequest:
    return AgentRequest(Question(identity, text, detail), detail, at)


def body(message: Message) -> str:
    """A timeline row's visible text: an action's readable call, otherwise its own text."""
    match message:
        case ToolActivity():
            return activity_text(message)
        case _:
            return message.text
