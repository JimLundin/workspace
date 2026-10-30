"""The answer and optional steps of a conversation bubble, without UI effects."""

from dataclasses import dataclass, replace
from textwrap import shorten

from assistant import feed_items, tool_text
from assistant.action_text import readable
from assistant.agent_session import AgentRequest, ChatMessage, pending
from assistant.feed_items import WorkItem, action_spans, expanded_spans, link
from assistant.feed_triage import Assessment
from assistant.notifications import Content, Entry, Response, Turn, body, heading, plain, results, steps
from assistant.rich_text import Span, formatted
from automation.presentation import Answer, ToolActivity
from automation.task import Approval


def answer(content: Content | None) -> Answer | None:
    match content:
        case Entry(message=Answer() as message):
            return message
        case Turn():
            return next((entry.message for entry in results(content) if isinstance(entry, Entry) and isinstance(entry.message, Answer)), None)
        case _:
            return None


def expandable(content: Content) -> bool:
    return (isinstance(content, WorkItem) and isinstance(content.item, Assessment)) or (isinstance(content, Turn) and bool(steps(content)))


def spans(content: Content, *, expanded: bool = True) -> tuple[Span, ...]:
    if isinstance(content, WorkItem):
        if isinstance(content.item, Assessment):
            if not expanded:
                preview = shorten(content.item.suggestion, width=280, placeholder="…")
                return (Span(content.title + "\n", ("bold", "feed", "feed_title")), *formatted(preview))
            return expanded_spans(content)
        return feed_items.body_spans(content)
    if isinstance(content, Turn):
        parts = [
            spans(entry)
            for entry in results(content)
            if not (
                content.origin is not None and isinstance(entry, Entry) and isinstance(entry.message, ChatMessage) and entry.message.speaker == "You"
            )
        ]
        return tuple(span for index, part in enumerate(parts) for span in ((Span("\n\n"),) if index else ()) + part)
    text = body(content)
    if not (isinstance(content, Entry) and isinstance(content.message, ChatMessage) and content.message.speaker == "You"):
        text = readable(text)
    return ((Span(text),) if plain(content) else tuple(formatted(text))) if text else ()


@dataclass(frozen=True, slots=True)
class BubbleText:
    body: tuple[Span, ...]
    canvas_actions: tuple[Span, ...]


def bubble_text(values: tuple[Span, ...]) -> BubbleText:
    """Workspace's canvas redirects are persistent controls beside the text."""
    actions = tuple(
        frozendict((span.link, span) for span in values if span.text == "Open on canvas" and span.link.startswith("workspace://canvas?")).values()
    )
    if not actions:
        return BubbleText(values, ())
    links = frozenset(span.link for span in actions)
    body = tuple(span for span in values if span.link not in links)
    last = next((index for index in reversed(range(len(body))) if body[index].text.rstrip()), None)
    body = (*body[:last], replace(body[last], text=body[last].text.rstrip())) if last is not None else ()
    return BubbleText(body, actions)


@dataclass(frozen=True, slots=True)
class HistoryStep:
    identity: str
    spans: tuple[Span, ...]


type Step = tool_text.Call | HistoryStep


def step_blocks(content: Content, *, expanded: bool = True) -> tuple[Step, ...]:
    match content:
        case Entry(message=ToolActivity() as activity):
            return (tool_text.presentation(activity, expanded=expanded),)
        case Turn():
            entries = steps(content)
        case _:
            return ()
    if not expanded:
        selected: tuple[Entry, ...] = ()
        for entry in reversed(entries):
            match entry:
                case Entry(message=ToolActivity()):
                    selected = (entry,)
                    break
                case _:
                    pass
        entries = selected
    return tuple(step_block(entry, expanded=expanded) for entry in entries)


def details(content: Content, *, expanded: bool = True) -> tuple[Span, ...]:
    parts = tuple(block_spans(block) for block in step_blocks(content, expanded=expanded))
    return tuple(span for index, part in enumerate(parts) for span in ((Span("\n\n"),) if index else ()) + part)


def step_block(entry: Entry | Response, *, expanded: bool) -> Step:
    match entry:
        case Entry(message=ToolActivity() as activity):
            return tool_text.presentation(activity, expanded=expanded)
        case Entry(index=index) | Response(index=index):
            return HistoryStep(f"{heading(entry)}:{index}", (Span(heading(entry) + "\n", ("bold", "step")), *spans(entry)))


def block_spans(block: Step) -> tuple[Span, ...]:
    match block:
        case tool_text.Call():
            return tuple(tool_text.call_spans(block))
        case HistoryStep(spans=values):
            return values


def options(content: Content) -> tuple[Span, ...]:
    if isinstance(content, WorkItem):
        return tuple(span for span in action_spans(content) if span.link)
    entries = results(content) if isinstance(content, Turn) else (content,) if isinstance(content, Entry) else ()
    for entry in entries:
        if (
            isinstance(entry, Entry)
            and isinstance(entry.message, AgentRequest)
            and isinstance(entry.message.request, Approval)
            and pending(entry.message)
        ):
            return tuple(link("agent-option", label, {"request": entry.message.id, "answer": label.casefold()}) for label in ("Approve", "Decline"))
    return ()


def title_text(content: Content) -> str:
    if isinstance(content, Turn):
        if content.origin is not None:
            return content.origin.title
        for entry in content.entries:
            if isinstance(entry, Entry) and isinstance(entry.message, ChatMessage) and entry.message.speaker == "You":
                return entry.message.text
    return heading(content)
