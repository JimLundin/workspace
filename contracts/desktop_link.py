"""The messages between the desktop and the assistant: what each tells and asks the other.

The desktop owns Qt, the bar, the tray and window placement; the assistant owns
dictation, meetings and the microphone, on its own thread in the same process.
These messages are all that pass between them.

Each message is its own frozen dataclass and each direction is a union of them;
the type is the discriminator. Messages to the desktop are states (each replaces
the last of its type) or notices; messages to the assistant are commands.
"""

from dataclasses import dataclass, field

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
