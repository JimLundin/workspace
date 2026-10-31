"""Card actions: what a bubble's link or button does, with one `workspace://` encoding.

Bubbles direct the person to the canvas or decide the agent's approvals; app
arrivals never become cards. A link that is not exactly one of these encodings
parses to None and does nothing.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import assert_never
from urllib.parse import parse_qs, urlencode, urlsplit

from automation.task import ApprovalDecision

_SCHEME = "workspace"
# The link's wire words for each decision; parsing accepts exactly these.
_DECISIONS: Mapping[ApprovalDecision, str] = frozendict({ApprovalDecision.APPROVED: "approve", ApprovalDecision.DECLINED: "decline"})


@dataclass(frozen=True, slots=True)
class OpenCanvas:
    target: str


@dataclass(frozen=True, slots=True)
class AnswerApproval:
    """Decide the agent's pending approval this card previews."""

    request: str
    decision: ApprovalDecision


type CardAction = OpenCanvas | AnswerApproval


def encode(action: CardAction) -> str:
    match action:
        case OpenCanvas(target=target):
            return _link("canvas", {"target": target})
        case AnswerApproval(request=request, decision=decision):
            return _link("agent-option", {"request": request, "answer": _DECISIONS[decision]})
        case _:
            assert_never(action)


def _link(action: str, values: Mapping[str, str]) -> str:
    return _SCHEME + "://" + action + "?" + urlencode(values)


def parse(link: str) -> CardAction | None:
    try:
        url = urlsplit(link)
    except ValueError:
        return None
    fields = parse_qs(url.query)
    if url.scheme != _SCHEME or url.path or url.fragment or any(len(values) != 1 for values in fields.values()):
        return None
    values = {name: value for name, (value,) in fields.items()}
    match url.netloc, values:
        case "canvas", {"target": str(target)} if len(values) == 1 and target:
            return OpenCanvas(target)
        case "agent-option", {"request": str(request), "answer": str(answer)} if len(values) == 2:
            decision = next((decision for decision, word in _DECISIONS.items() if word == answer), None)
            return AnswerApproval(request, decision) if decision is not None else None
        case _:
            return None
