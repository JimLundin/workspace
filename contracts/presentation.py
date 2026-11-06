"""Shared presentation values: progress, results and live rows.

The worker publishes live updates straight to the assistant's observer, which
synthesizes Done and Finished from durable task outcomes and renders
the timeline. Each variant carries its presentation `kind`.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class StreamState(Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class Answer:
    identity: str
    text: str
    created_at: float
    state: StreamState = StreamState.RUNNING
    kind: Literal["answer"] = "answer"


@dataclass(frozen=True, slots=True)
class ReasoningSummary:
    identity: str
    text: str
    created_at: float
    state: StreamState = StreamState.RUNNING
    kind: Literal["reasoning"] = "reasoning"


class ToolStatus(Enum):
    RUNNING = "running"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Succeeded:
    text: str
    kind: Literal["succeeded"] = "succeeded"


@dataclass(frozen=True, slots=True)
class Failed:
    text: str
    kind: Literal["failed"] = "failed"


type ToolOutcome = ToolStatus | Succeeded | Failed


@dataclass(frozen=True, slots=True)
class ToolActivity:
    identity: str
    name: str
    detail: str
    created_at: float
    outcome: ToolOutcome = ToolStatus.RUNNING
    kind: Literal["tool"] = "tool"


type LiveMessage = Answer | ReasoningSummary | ToolActivity


@dataclass(frozen=True, slots=True)
class Progress:
    text: str
    kind: Literal["progress"] = "progress"


@dataclass(frozen=True, slots=True)
class Said:
    text: str
    at: float
    kind: Literal["said"] = "said"


@dataclass(frozen=True, slots=True)
class Done:
    text: str
    at: float
    kind: Literal["done"] = "done"


@dataclass(frozen=True, slots=True)
class Problem:
    text: str
    at: float
    kind: Literal["problem"] = "problem"


type PresentationEvent = Progress | Said | Problem | LiveMessage
"""What a run publishes live; the assistant derives Done and Finished from the journal."""


@dataclass(frozen=True, slots=True)
class Finished:
    kind: Literal["finished"] = "finished"
