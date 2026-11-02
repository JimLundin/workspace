"""Timeline projections of durable agent requests, for conversation and UI fixtures."""

from assistant.agent_session import AgentRequest
from automation.task import Approval, Question


def asked(identity: str, text: str, detail: str, at: float) -> AgentRequest:
    return AgentRequest(Question(identity, text, detail), detail, at)


def reviewed(identity: str, title: str, review: str, at: float) -> AgentRequest:
    """The person decides on the live review; the durable detail stays redacted."""
    return AgentRequest(Approval(identity, title, "Review the exact operation.", "a" * 64), review, at)
