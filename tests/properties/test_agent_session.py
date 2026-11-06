"""Replies resolve exactly their pending request; stale and retired replies do nothing."""

from dataclasses import dataclass, field, replace

from hypothesis import strategies

from contracts.agent_session import Cancelled, Resolution, Session, transition
from contracts.task import TextAnswer
from tests.agent_requests import asked
from tests.properties.generation import cases, property_test


@dataclass(frozen=True, slots=True)
class ReplyCase:
    identity: str
    text: str
    stopping: bool = field(kw_only=True)


def reply_cases(draw: strategies.DrawFn) -> ReplyCase:
    return ReplyCase(
        # Requests are validated durable values: their identities contain no NUL.
        draw(strategies.text(min_size=1, max_size=32)).replace("\0", "·"),
        # Replies are validated task answers: some visible text, no NUL.
        "a" + draw(strategies.text(max_size=95)).replace("\0", "·"),
        stopping=draw(strategies.booleans()),
    )


@property_test(cases(reply_cases))
def test_only_the_matching_pending_request_accepts_a_reply(case: ReplyCase) -> None:
    current = "current/" + case.identity
    stale = "stale/" + case.identity
    request = asked(current, "Reply?", "", 1)
    other = asked("other/" + case.identity, "Another request", "", 2)
    # The request precedes another, so resolving it must keep later messages.
    session = Session(messages=(request, other), phase="stopping" if case.stopping else "running", status="Waiting")
    for event in (Resolution(stale, TextAnswer(case.text)), Resolution(stale, Cancelled())):
        assert transition(session, event) == session

    reply = TextAnswer(case.text)
    updated = transition(session, Resolution(current, reply))
    assert updated == replace(session, messages=(replace(request, reply=reply), other), status="Stopping…" if case.stopping else "Working…")
    for event in (Resolution(current, TextAnswer(case.text + " later")), Resolution(current, Cancelled())):
        assert transition(updated, event) == updated
    assert session.messages == (request, other)
