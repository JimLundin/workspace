"""What a work run publishes for its presentation: progress, results and live rows.

The automation process produces these values and the assistant's timeline
consumes them; how they are rendered belongs to the assistant. Each variant
carries its wire `kind` and each payload-free variant a string value, so the
process bridge sends these records directly.
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


@dataclass(frozen=True, slots=True)
class Finished:
    kind: Literal["finished"] = "finished"
