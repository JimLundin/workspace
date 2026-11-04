"""Timeline projections of durable agent questions, for conversation and UI fixtures."""

from assistant.agent_session import AgentRequest
from automation.task import Question


def asked(identity: str, text: str, detail: str, at: float) -> AgentRequest:
    return AgentRequest(Question(identity, text, detail), detail, at)
