"""Toolbar attention follows unhandled work, independent of bubble visibility."""

from assistant.agent_session import Snapshot, pending
from assistant.feed_items import WorkState, observed


def pending_count(session: Snapshot) -> int:
    """Count inbox items and unanswered prompts, using the feed's grouping policy."""
    return sum(row.state is WorkState.PENDING for row in observed(session)) + sum(pending(message) for message in session.messages)
