"""Teams call observations and automatic recording decisions, without effects."""

from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Annotated

from pydantic import Field, TypeAdapter

from assistant.recording_state import RecordingState


class AutomaticStatus(Enum):
    OFF = auto()
    CHECKING = auto()
    READY = auto()
    UNAVAILABLE = auto()


@dataclass(frozen=True, slots=True)
class AutomaticPreference:
    enabled: Annotated[bool, Field(strict=True)] = field(default=False, kw_only=True)


PREFERENCE = TypeAdapter(AutomaticPreference)


@dataclass(frozen=True, slots=True)
class Call:
    identity: str
    title: str


@dataclass(frozen=True, slots=True)
class Calls:
    active: tuple[Call, ...]


class ObservationFailure(Enum):
    UNAVAILABLE = auto()


type Observation = Calls | ObservationFailure


class Ownership(Enum):
    AUTOMATIC = auto()
    SUPPRESSED = auto()
    FAILED = auto()


class Idle(Enum):
    WAITING = auto()
    STOPPED = auto()


@dataclass(frozen=True, slots=True)
class Watching:
    call: Call
    ownership: Ownership
    last_seen: float
    absent_since: float | None = None


type Watch = Idle | Watching


class Effect(Enum):
    NONE = auto()
    STOP = auto()


@dataclass(frozen=True, slots=True)
class Start:
    call: Call


@dataclass(frozen=True, slots=True)
class Decision:
    watch: Watch
    effect: Start | Effect = Effect.NONE


@dataclass(frozen=True, slots=True)
class Sample:
    calls: Observation
    recording: RecordingState
    at: float


def suppressed(watch: Watch) -> Watch:
    """A manual command or failed capture must not restart in this same call."""
    match watch:
        case Watching():
            return replace(watch, ownership=Ownership.SUPPRESSED)
        case Idle():
            return Idle.STOPPED


def decide(watch: Watch, sample: Sample) -> Decision:
    """Debounce departures for 10s; stop owned capture after 30s without evidence.

    Failure is not departure. Suppression lasts until a confirmed departure,
    including after the browser connection recovers. Manual capture is never stopped.
    """
    match watch, sample.calls:
        case Idle(), Calls(active=active) if active:
            call = active[0]
            ownership = Ownership.SUPPRESSED if sample.recording.capturing or watch is Idle.STOPPED else Ownership.AUTOMATIC
            return Decision(Watching(call, ownership, sample.at), Start(call) if ownership is Ownership.AUTOMATIC else Effect.NONE)
        case Idle.STOPPED, Calls(active=()):
            return Decision(Idle.WAITING)
        case Watching() as current, Calls(active=active):
            if not sample.recording.capturing and current.ownership is Ownership.AUTOMATIC:
                current = replace(current, ownership=Ownership.SUPPRESSED)
            if any(call.identity == current.call.identity for call in active):
                return Decision(replace(current, last_seen=sample.at, absent_since=None))
            absent = current.absent_since if current.absent_since is not None else sample.at
            if sample.at - absent < 10:
                return Decision(replace(current, absent_since=absent))
            return Decision(Idle.WAITING, Effect.STOP if current.ownership is Ownership.AUTOMATIC else Effect.NONE)
        case Watching() as current, ObservationFailure.UNAVAILABLE if sample.at - current.last_seen >= 30:
            stop = current.ownership is Ownership.AUTOMATIC and sample.recording.capturing
            return Decision(suppressed(current), Effect.STOP if stop else Effect.NONE)
        case _:
            return Decision(watch)
