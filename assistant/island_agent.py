"""What the island shows of the agent: its current phase, read from the live session.

The phase is the agent's latest public step: the running tool, or the heading of
its latest reasoning summary. The bar owns no agent state of its own; every
session snapshot replaces the reading.
"""

import re

from assistant import action_text
from assistant.agent_progress import phases
from assistant.agent_session import ChatMessage, Snapshot
from assistant.island_model import Agent
from assistant.notifications import Entry, Response
from automation.presentation import Answer, ToolActivity, ToolStatus

LENGTH = 40  # The reading's bound before the island elides it to its own width.


def heading(text: str) -> str:
    """A summary's bold heading, else its first sentence, as one bounded line."""
    bold = re.match(r"\s*\*\*(.+?)\*\*", text)
    line = bold.group(1) if bold is not None else re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0]
    return action_text.shortened(" ".join(line.replace("*", "").split()), LENGTH)


def reading(entry: Entry | Response) -> str | None:
    match entry:
        case Entry(message=ToolActivity(name=name, outcome=ToolStatus.RUNNING)):
            return action_text.title(name)
        case Entry(message=ChatMessage(speaker="Workspace", text=text) | Answer(text=text)) | Response(text=text) if text.strip():
            return heading(text)
        case _:
            return None


def activity(session: Snapshot) -> Agent | None:
    """The agent's activity while it runs or waits for you; None at rest."""
    waiting = session.waiting
    if not session.busy and not waiting:
        return None
    if session.stopping:
        return Agent("Stopping…", waiting=False)
    latest = tuple(phases(session))[-1:]
    found = tuple(text for phase in latest for entry in reversed(phase.turn.entries) if (text := reading(entry)) is not None)
    return Agent(found[0] if found else "Thinking", waiting=waiting)
