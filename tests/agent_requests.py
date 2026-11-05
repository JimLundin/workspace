"""Timeline projections of durable agent questions, and timeline text, for conversation and UI fixtures."""

from assistant.agent_session import AgentRequest, Message, activity_text
from automation.presentation import ToolActivity
from automation.task import Question


def asked(identity: str, text: str, detail: str, at: float) -> AgentRequest:
    return AgentRequest(Question(identity, text, detail), detail, at)


def body(message: Message) -> str:
    """A timeline row's visible text: an action's readable call, otherwise its own text."""
    match message:
        case ToolActivity():
            return activity_text(message)
        case _:
            return message.text
