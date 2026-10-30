"""Card actions: what a rendered card's link or button does, with one `workspace://` encoding.

Builders produce variants and the feed view matches the parsed variant. A link
that is not exactly one of these encodings parses to None and does nothing.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import assert_never
from urllib.parse import parse_qs, urlencode, urlsplit

from assistant.feed_sources import SourceKey, SourceKind

_SCHEME = "workspace"


class Verb(Enum):
    """What the person asks of one rendered feed item; the value is its wire name."""

    DONE = "done"
    REOPEN = "reopen"
    HELP = "help"
    OPEN_CHAT = "open"
    OPEN_SOURCE = "update"
    HIDE_APP = "filter-app"
    REVIEWED = "reviewed"


class Decision(Enum):
    APPROVE = "approve"
    DECLINE = "decline"


@dataclass(frozen=True, slots=True)
class OpenCanvas:
    target: str


@dataclass(frozen=True, slots=True)
class AnswerApproval:
    """Decide the agent's pending approval this card previews."""

    request: str
    decision: Decision


@dataclass(frozen=True, slots=True)
class AnswerConsole:
    """Choose one option of a console request's question by its index."""

    request: str
    question: int
    answer: str


@dataclass(frozen=True, slots=True)
class ItemAction:
    """Name the rendered item, never its source fields: a click acts on what the person saw."""

    verb: Verb
    item: SourceKey


type CardAction = OpenCanvas | AnswerApproval | AnswerConsole | ItemAction


def encode(action: CardAction) -> str:
    match action:
        case OpenCanvas(target=target):
            return _link("canvas", {"target": target})
        case AnswerApproval(request=request, decision=decision):
            return _link("agent-option", {"request": request, "answer": decision.value})
        case AnswerConsole(request=request, question=question, answer=answer):
            return _link("console-option", {"message": request, "question": str(question), "answer": answer})
        case ItemAction(verb=verb, item=SourceKey(kind=kind, identity=identity)):
            return _link(verb.value, {"source": kind.value, "item": identity})
        case _:
            assert_never(action)


def _link(action: str, values: Mapping[str, str]) -> str:
    return _SCHEME + "://" + action + "?" + urlencode(values)


def parse(link: str) -> CardAction | None:
    try:
        url = urlsplit(link)
    except ValueError:
        return None
    fields = parse_qs(url.query, keep_blank_values=True)
    if url.scheme != _SCHEME or url.path or url.fragment or any(len(values) != 1 for values in fields.values()):
        return None
    values = {name: value for name, (value,) in fields.items()}
    match url.netloc, values:
        case "canvas", {"target": str(target)} if len(values) == 1 and target:
            return OpenCanvas(target)
        case "agent-option", {"request": str(request), "answer": str(answer)} if len(values) == 2:
            decision = _member(Decision, answer)
            return AnswerApproval(request, decision) if decision is not None else None
        case "console-option", {"message": str(request), "question": str(index), "answer": str(answer)} if len(values) == 3:
            return AnswerConsole(request, int(index), answer) if index.isascii() and index.isdecimal() else None
        case verb, {"source": str(source), "item": str(identity)} if len(values) == 2 and identity:
            chosen, kind = _member(Verb, verb), _member(SourceKind, source)
            return ItemAction(chosen, SourceKey(kind, identity)) if chosen is not None and kind is not None else None
        case _:
            return None


def _member[E: Enum](kind: type[E], value: str) -> E | None:
    try:
        return kind(value)
    except ValueError:
        return None
