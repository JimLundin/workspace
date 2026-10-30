"""The answer and optional steps of a conversation bubble, without UI effects."""

from dataclasses import dataclass, replace
from textwrap import shorten

from assistant import feed_items, tool_text
from assistant.action_text import readable
from assistant.agent_session import AgentRequest, Answer, ChatMessage, ToolActivity, pending
from assistant.card_actions import AnswerApproval, Decision, OpenCanvas, parse
from assistant.feed_items import WorkItem, action_spans, expanded_spans, link
from assistant.feed_triage import Assessment
from assistant.notifications import Content, Entry, Response, Turn, body, heading, plain, results, steps
from assistant.rich_text import Span, formatted
from automation.task import Approval


def answer(content: Content | None) -> Answer | None:
    match content:
        case Entry(message=Answer() as message):
            return message
        case Turn():
            return next((answer for answer in map(_answer, results(content)) if answer is not None), None)
        case _:
            return None


def _answer(entry: Entry | Response) -> Answer | None:
    match entry:
        case Entry(message=Answer() as message):
            return message
        case _:
            return None


def _yours(content: Content) -> bool:
    """The person's own words, shown as typed rather than as agent prose."""
    match content:
        case Entry(message=ChatMessage(speaker="You")):
            return True
        case _:
            return False


def expandable(content: Content) -> bool:
    match content:
        case WorkItem(item=Assessment()):
            return True
        case Turn():
            return bool(steps(content))
        case _:
            return False


def spans(content: Content, *, expanded: bool = True) -> tuple[Span, ...]:
    match content:
        case WorkItem(item=Assessment(suggestion=suggestion), title=title) if not expanded:
            preview = shorten(suggestion, width=280, placeholder="…")
            return (Span(title + "\n", ("bold", "feed", "feed_title")), *formatted(preview))
        case WorkItem(item=Assessment()):
            return expanded_spans(content)
        case WorkItem():
            return feed_items.body_spans(content)
        case Turn(origin=origin):
            parts = [spans(entry) for entry in results(content) if not (origin is not None and _yours(entry))]
            return tuple(span for index, part in enumerate(parts) for span in ((Span("\n\n"),) if index else ()) + part)
        case _:
            pass
    text = body(content)
    if not _yours(content):
        text = readable(text)
    return ((Span(text),) if plain(content) else tuple(formatted(text))) if text else ()


@dataclass(frozen=True, slots=True)
class BubbleText:
    body: tuple[Span, ...]
    canvas_actions: tuple[Span, ...]


def bubble_text(values: tuple[Span, ...]) -> BubbleText:
    """Workspace's canvas redirects are persistent controls beside the text."""
    actions = tuple(frozendict((span.link, span) for span in values if span.text == "Open on canvas" and canvas_link(span)).values())
    if not actions:
        return BubbleText(values, ())
    links = frozenset(span.link for span in actions)
    body = tuple(span for span in values if span.link not in links)
    last = next((index for index in reversed(range(len(body))) if body[index].text.rstrip()), None)
    body = (*body[:last], replace(body[last], text=body[last].text.rstrip())) if last is not None else ()
    return BubbleText(body, actions)


def canvas_link(span: Span) -> bool:
    match parse(span.link):
        case OpenCanvas():
            return True
        case _:
            return False


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
    match content:
        case WorkItem():
            return tuple(span for span in action_spans(content) if span.link)
        case Turn():
            entries = results(content)
        case Entry():
            entries = (content,)
        case _:
            return ()
    for entry in entries:
        match entry:
            case Entry(message=AgentRequest(request=Approval()) as message) if pending(message):
                return (
                    link("Approve", AnswerApproval(message.id, Decision.APPROVE)),
                    link("Decline", AnswerApproval(message.id, Decision.DECLINE)),
                )
            case _:
                pass
    return ()


def title_text(content: Content) -> str:
    match content:
        case Turn(origin=origin) if origin is not None:
            return origin.title
        case Turn(entries=entries):
            for entry in entries:
                match entry:
                    case Entry(message=ChatMessage(speaker="You", text=text)):
                        return text
                    case _:
                        pass
        case _:
            pass
    return heading(content)
