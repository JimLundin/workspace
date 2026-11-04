"""Feed refusals retain useful recovery evidence without persisting private text."""

from assistant.agent_tools import Output
from assistant.feed_agent_tools import feed_outcome
from assistant.feed_contracts import FeedRejected, QueuedHandoff
from assistant.work_bridge_contracts import BRIDGE_RESPONSE
from automation.task import ActionNotApplied, ActionVerified


def test_feed_refusal_records_exact_safe_diagnostic() -> None:
    reason = "That proposal has changed. Read the feed again before rejecting it."
    reply = BRIDGE_RESPONSE.dump_json(FeedRejected(reason)).decode()
    outcome = feed_outcome(Output(reply, ok=False))
    assert isinstance(outcome, ActionNotApplied)
    assert outcome.reason.endswith(reason)


def test_feed_refusal_does_not_journal_arbitrary_error_text() -> None:
    reply = BRIDGE_RESPONSE.dump_json(FeedRejected("Private source text: confidential message")).decode()
    outcome = feed_outcome(Output(reply, ok=False))
    assert isinstance(outcome, ActionNotApplied)
    assert "confidential" not in outcome.reason
    assert "details withheld" in outcome.reason


def test_feed_accepted_handoff_remains_verified() -> None:
    reply = BRIDGE_RESPONSE.dump_json(QueuedHandoff("task", "item", "decision")).decode()
    assert isinstance(feed_outcome(Output(reply)), ActionVerified)
