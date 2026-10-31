"""What a work run publishes for its presentation: progress, results and live rows.

The automation process produces these values and the assistant's timeline
consumes them; how they are rendered belongs to the assistant.
"""

from dataclasses import dataclass
from enum import Enum, auto


class StreamState(Enum):
    RUNNING = auto()
    COMPLETE = auto()
    INTERRUPTED = auto()


@dataclass(frozen=True, slots=True)
class Answer:
    identity: str
    text: str
    created_at: float
    state: StreamState = StreamState.RUNNING


@dataclass(frozen=True, slots=True)
class ReasoningSummary:
    identity: str
    text: str
    created_at: float
    state: StreamState = StreamState.RUNNING


class ToolStatus(Enum):
    RUNNING = auto()
    CANCELLED = auto()


@dataclass(frozen=True, slots=True)
class Succeeded:
    text: str


@dataclass(frozen=True, slots=True)
class Failed:
    text: str


type ToolOutcome = ToolStatus | Succeeded | Failed


@dataclass(frozen=True, slots=True)
class ToolActivity:
    identity: str
    name: str
    detail: str
    created_at: float
    outcome: ToolOutcome = ToolStatus.RUNNING


type LiveMessage = Answer | ReasoningSummary | ToolActivity


@dataclass(frozen=True, slots=True)
class Progress:
    text: str


@dataclass(frozen=True, slots=True)
class Said:
    text: str
    at: float


@dataclass(frozen=True, slots=True)
class Done:
    text: str
    at: float


@dataclass(frozen=True, slots=True)
class Problem:
    text: str
    at: float


@dataclass(frozen=True, slots=True)
class Finished:
    pass
