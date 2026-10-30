"""Literal, bounded tool-call blocks derived from real invocation events."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import assert_never

from assistant import action_text
from assistant.rich_text import Span
from automation.presentation import Failed, Succeeded, ToolActivity, ToolStatus


class State(Enum):
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


@dataclass(frozen=True, slots=True)
class Call:
    identity: str
    name: str
    label: str
    state: State
    symbol: str
    argument: str
    result: str
    copy_text: str


def presentation(activity: ToolActivity, *, expanded: bool) -> Call:
    match activity.outcome:
        case Succeeded(text):
            symbol, state, result = "✓", State.SUCCEEDED, text
        case Failed(text):
            symbol, state, result = "!", State.FAILED, text
        case ToolStatus.CANCELLED:
            symbol, state, result = "\u2013", State.CANCELLED, ""
        case ToolStatus.RUNNING:
            symbol, state, result = "·", State.RUNNING, ""
        case _:
            assert_never(activity.outcome)
    copy_text = action_text.arguments(activity.name, activity.detail) if activity.detail else ""
    argument = action_text.shortened(copy_text, 0 if expanded else 160)
    result = action_text.result(activity.name, result) if result and (expanded or activity.name == "get_current_time") else ""
    return Call(activity.identity, activity.name, action_text.title(activity.name), state, symbol, argument, result, copy_text or result)


def spans(activity: ToolActivity, *, expanded: bool) -> Iterator[Span]:
    yield from call_spans(presentation(activity, expanded=expanded))


def call_spans(call: Call) -> Iterator[Span]:
    style = "step_error" if call.state is State.FAILED else "step"
    yield Span(f"{call.symbol}  {call.label} · {call.state.value}\n", ("bold", style, "tool_call"))
    yield Span(call.name + "\n", ("code", "step_detail", "tool_call"))
    if call.argument:
        yield Span(call.argument + "\n", ("code", "codeblock", "step_detail", "tool_input"))
    if call.result:
        yield Span("Result\n", ("bold", style))
        yield Span(call.result, ("code", "codeblock", "step_detail", "tool_output"))
