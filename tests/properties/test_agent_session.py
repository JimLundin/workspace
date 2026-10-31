"""Replies resolve exactly their pending request; stale and retired replies do nothing."""

from dataclasses import dataclass, field, replace

from hypothesis import strategies

from assistant.agent_session import Cancelled, Resolution, Session, transition
from automation.task import ApprovalDecision, TextAnswer
from tests.agent_requests import asked, reviewed
from tests.properties.generation import cases, property_test


@dataclass(frozen=True, slots=True)
class ReplyCase:
    identity: str
    text: str
    question: bool = field(kw_only=True)
    decision: ApprovalDecision
    stopping: bool = field(kw_only=True)


def reply_cases(draw: strategies.DrawFn) -> ReplyCase:
    return ReplyCase(
        # Requests are validated durable values: their identities contain no NUL.
        draw(strategies.text(min_size=1, max_size=32)).replace("\0", "·"),
        # Replies are validated task answers: some visible text, no NUL.
        "a" + draw(strategies.text(max_size=95)).replace("\0", "·"),
        question=draw(strategies.booleans()),
        decision=draw(strategies.sampled_from(tuple(ApprovalDecision))),
        stopping=draw(strategies.booleans()),
    )


@property_test(cases(reply_cases))
def test_only_the_matching_pending_request_accepts_a_reply(case: ReplyCase) -> None:
    current = "current/" + case.identity
    stale = "stale/" + case.identity
    request = asked(current, "Reply?", "", 1) if case.question else reviewed(current, "Proceed?", "", 1)
    other = asked("other/" + case.identity, "Another request", "", 2)
    session = Session(messages=(other, request), phase="stopping" if case.stopping else "running", status="Waiting")
    for event in (Resolution(stale, TextAnswer(case.text)), Resolution(stale, case.decision), Resolution(stale, Cancelled())):
        assert transition(session, event) == session
    mismatch = Resolution(current, case.decision) if case.question else Resolution(current, TextAnswer(case.text))
    assert transition(session, mismatch) == session

    reply = TextAnswer(case.text) if case.question else case.decision
    updated = transition(session, Resolution(current, reply))
    assert updated == replace(session, messages=(other, replace(request, reply=reply)), status="Stopping…" if case.stopping else "Working…")
    for event in (Resolution(current, TextAnswer(case.text + " later")), Resolution(current, case.decision), Resolution(current, Cancelled())):
        assert transition(updated, event) == updated
    assert session.messages == (other, request)
