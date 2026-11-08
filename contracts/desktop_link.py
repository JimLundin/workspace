"""The messages between the desktop and the assistant: what each tells and asks the other.

The desktop owns Qt, the bar, the tray and window placement; the assistant owns
dictation, meetings and the microphone. Each runs without the other, and these
messages are all that pass between them, over `link`.

Each message is its own frozen dataclass and each direction is a union of them;
the type is the discriminator. Messages to the desktop are states (each replaces
the last of its type, and the assistant replays them when the desktop connects)
or events (delivered once, dropped while no desktop is connected). Messages to
the assistant are commands; while it is down the desktop says so instead.

On the wire a message is its class name, a newline and its JSON (`encode`); the
name exists only there, never as a field a value could contradict.
"""

from dataclasses import dataclass, field
from typing import Final, assert_never

from pydantic import TypeAdapter, ValidationError

from contracts.recording_state import RecordingAction, RecordingState
from contracts.status import Job, State
from protocol import Tool

# ---- to the desktop: states ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VoiceChanged:
    """What the tray shows."""

    state: State


@dataclass(frozen=True, slots=True)
class JobChanged:
    job: Job | None


@dataclass(frozen=True, slots=True)
class RecordingChanged:
    recording: RecordingState


@dataclass(frozen=True, slots=True)
class MicLevel:
    """The microphone's level while it listens, for the bar's trace; None when unobserved."""

    level: float | None

    def __post_init__(self) -> None:
        if self.level is not None and not 0.0 <= self.level <= 1.0:
            raise ValueError(f"A microphone level is from 0 to 1, not {self.level}.")


type DesktopState = VoiceChanged | JobChanged | RecordingChanged | MicLevel

# ---- to the desktop: events ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Notify:
    """A tray notification; a warning also sounds."""

    title: str
    text: str
    warning: bool = field(default=False, kw_only=True)


type ToDesktop = DesktopState | Notify

# ---- to the assistant ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UseTool:
    """A tool chosen in the bar or tray that the assistant owns, such as copying the latest transcript."""

    tool: Tool


@dataclass(frozen=True, slots=True)
class Record:
    action: RecordingAction


type ToAssistant = UseTool | Record

# ---- the wire --------------------------------------------------------------------------

_TO_DESKTOP: Final[frozendict[str, TypeAdapter[ToDesktop]]] = frozendict(
    {kind.__name__: TypeAdapter[ToDesktop](kind) for kind in (VoiceChanged, JobChanged, RecordingChanged, MicLevel, Notify)}
)
_TO_ASSISTANT: Final[frozendict[str, TypeAdapter[ToAssistant]]] = frozendict(
    {kind.__name__: TypeAdapter[ToAssistant](kind) for kind in (UseTool, Record)}
)


class WireError(ValueError):
    """A frame that isn't a message of this direction."""


def _encoded[T](message: T, adapters: frozendict[str, TypeAdapter[T]]) -> bytes:
    name = type(message).__name__
    return name.encode("ascii") + b"\n" + adapters[name].dump_json(message)


def _decoded[T](frame: bytes, adapters: frozendict[str, TypeAdapter[T]]) -> T:
    name, _, body = frame.partition(b"\n")
    adapter = adapters.get(name.decode("ascii", errors="replace"))
    if adapter is None:
        raise WireError(f"Unknown message {name[:64]!r}.")
    try:
        return adapter.validate_json(body)
    except ValidationError as error:
        raise WireError(f"{name.decode('ascii', errors='replace')}: {error.errors()[0]['msg']}") from error


def to_desktop(message: ToDesktop) -> bytes:
    return _encoded(message, _TO_DESKTOP)


def from_assistant(frame: bytes) -> ToDesktop:
    return _decoded(frame, _TO_DESKTOP)


def to_assistant(message: ToAssistant) -> bytes:
    return _encoded(message, _TO_ASSISTANT)


def from_desktop(frame: bytes) -> ToAssistant:
    return _decoded(frame, _TO_ASSISTANT)


def state_key(message: ToDesktop) -> str | None:
    """A state's coalescing key (its type): the latest replaces a waiting one and is replayed
    to a desktop that connects. Events have none."""
    match message:
        case VoiceChanged() | JobChanged() | RecordingChanged() | MicLevel():
            return type(message).__name__
        case Notify():
            return None
        case _:
            assert_never(message)
