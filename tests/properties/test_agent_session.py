"""Replies resolve exactly their pending request; stale and retired replies do nothing."""

from dataclasses import dataclass, replace
from typing import Literal

from hypothesis import strategies

from assistant.agent_session import (
    Answered,
    Approval,
    ApprovalDecided,
    InputCancelled,
    Message,
    Question,
    QuestionAnswered,
    Resolution,
    Session,
    transition,
)
from tests.properties.generation import cases, property_test


@dataclass(frozen=True, slots=True)
class ReplyCase:
    identity: str
    text: str
    question: bool
    decision: Literal["approved", "declined"]
    stopping: bool


def reply_cases(draw: strategies.DrawFn) -> ReplyCase:
    decisions: tuple[Literal["approved", "declined"], ...] = ("approved", "declined")
    return ReplyCase(draw(strategies.text(min_size=1, max_size=32)), draw(strategies.text(max_size=96)), draw(strategies.booleans()),
                     draw(strategies.sampled_from(decisions)), draw(strategies.booleans()))


@property_test(cases(reply_cases))
def test_only_the_matching_pending_request_accepts_a_reply(case: ReplyCase) -> None:
    current = "current/" + case.identity
    stale = "stale/" + case.identity
    request: Question | Approval = Question(current, "Reply?", "", 1) if case.question else Approval(current, "Proceed?", "", 1)
    other = Question("other/" + case.identity, "Another request", "", 2)
    session = Session(messages=(other, request), phase="stopping" if case.stopping else "running", status="Waiting")
    stale_events: tuple[Resolution, ...] = (QuestionAnswered(stale, case.text), ApprovalDecided(stale, case.decision), InputCancelled(stale))
    for event in stale_events:
        assert transition(session, event) == session
    mismatch: Resolution = ApprovalDecided(current, case.decision) if case.question else QuestionAnswered(current, case.text)
    assert transition(session, mismatch) == session

    reply: Resolution = QuestionAnswered(current, case.text) if case.question else ApprovalDecided(current, case.decision)
    resolved: Message
    match request:
        case Question():
            resolved = replace(request, reply=Answered(case.text))
        case Approval():
            resolved = replace(request, decision=case.decision)
    updated = transition(session, reply)
    assert updated == replace(session, messages=(other, resolved), status="Stopping…" if case.stopping else "Working…")
    retired_events: tuple[Resolution, ...] = (
        QuestionAnswered(current, case.text + " later"), ApprovalDecided(current, case.decision), InputCancelled(current),
    )
    for event in retired_events:
        assert transition(updated, event) == updated
    assert session.messages == (other, request)
