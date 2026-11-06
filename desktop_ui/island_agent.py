"""What the island shows of the agent, read from the live session: its phase, its recent steps and its news.

The phase is the agent's latest public step: the running tool, or the heading of
its latest reasoning summary. Its news is each finished reply and each canvas
finding it announces. The bar owns no agent state of its own; every session
snapshot replaces the reading.
"""

from contracts import action_text
from contracts.agent_session import ChatMessage, Snapshot
from contracts.canvas_session import session_replies
from contracts.presentation import Answer, ToolActivity, ToolStatus
from desktop_ui.agent_progress import Entry, Response, phases
from desktop_ui.island_model import Agent
from desktop_ui.island_moment import Notice
from desktop_ui.plain_text import plain

LENGTH = 40  # The reading's bound before the island elides it to its own width.
STEPS = 3  # Earlier steps the island reveals under the pointer.


def sentence(text: str) -> str:
    """The first line, up to its first sentence end."""
    line = text.split("\n", 1)[0]
    ends = tuple(index + 1 for mark in ".!?" if (index := line.find(mark + " ")) >= 0)
    return line[: min(ends)] if ends else line


def heading(text: str) -> str:
    """A summary's bold heading, else its first sentence, as one bounded line."""
    stripped = text.strip()
    close = stripped.find("**", 2) if stripped.startswith("**") else -1
    line = stripped[2:close] if close > 2 else sentence(stripped)
    return action_text.shortened(" ".join(line.replace("*", "").split()), LENGTH)


def reading(entry: Entry | Response, *, finished: bool = False) -> str | None:
    """A step as one line: a running tool (any tool, once `finished` ones count) or a public update's heading."""
    match entry:
        case Entry(message=ToolActivity(name=name, outcome=outcome)) if finished or outcome is ToolStatus.RUNNING:
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
    found = tuple(text for each in latest for entry in reversed(each.turn.entries) if (text := reading(entry)) is not None)
    phase = found[0] if found else "Thinking"
    taken = tuple(step for each in latest for entry in each.turn.entries if (step := reading(entry, finished=True)) is not None)
    steps = tuple(step for index, step in enumerate(taken) if index == 0 or step != taken[index - 1])
    others = tuple(step for step in steps if step != phase)
    return Agent(phase, waiting=waiting, steps=others[-STEPS:])


def notices(session: Snapshot) -> tuple[Notice, ...]:
    """The agent's news in this session: finished replies and announced canvas findings and questions."""
    replies = tuple(
        Notice(reply.id, " ".join(reply.title.split()), plain(reply.text).text, reply.id, reply.created_at) for reply in session_replies(session)
    )
    found: tuple[Notice, ...] = ()
    for message in session.messages:
        match message:
            case ChatMessage(source=source, created_at=at) if source is not None and source.identity.startswith("canvas:"):
                target = source.identity.removeprefix("canvas:")
                item = next((item for item in session.attention.items if item.identity == target), None)
                text = plain(item.text).text if item is not None else ""
                question = item is not None and item.question is not None
                found = (*found, Notice(f"{source.identity}:{at}", source.title, text, target, at, question=question))
            case _:
                pass
    return tuple(sorted((*replies, *found), key=lambda notice: notice.at))
