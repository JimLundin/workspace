"""The messages between the desktop and the assistant: what each tells and asks the other.

The desktop owns Qt, the bar, the canvas views, the tray and window placement; the
assistant owns the agent, its work, the canvas document, meetings and the
microphone. Each runs without the other, and these messages are all that pass
between them, over `link`.

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

from contracts.agent_session import Session
from contracts.canvas_activity import CanvasRequest, CanvasRun
from contracts.meeting_detection import AutomaticStatus
from contracts.recording_state import RecordingAction, RecordingState
from contracts.status import Job, State
from contracts.task import TextAnswer
from contracts.work_canvas_contracts import CanvasPublication
from contracts.work_canvas_edits import UserEdit
from contracts.work_commands import WorkViewCommand
from contracts.work_snapshot import WorkSnapshot
from protocol import Tool
from winapi.system_notices import Observed

# ---- to the desktop: states ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionChanged:
    """The agent conversation, as the bar, inbox and canvas show it."""

    session: Session


@dataclass(frozen=True, slots=True)
class WorkChanged:
    snapshot: WorkSnapshot


@dataclass(frozen=True, slots=True)
class CanvasChanged:
    publication: CanvasPublication


@dataclass(frozen=True, slots=True)
class VoiceChanged:
    """What the tray shows, and whether the held key speaks to the agent."""

    state: State
    agent_speaking: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class JobChanged:
    job: Job | None


@dataclass(frozen=True, slots=True)
class RecordingChanged:
    recording: RecordingState


@dataclass(frozen=True, slots=True)
class AutomaticChanged:
    status: AutomaticStatus


type DesktopState = SessionChanged | WorkChanged | CanvasChanged | VoiceChanged | JobChanged | RecordingChanged | AutomaticChanged

# ---- to the desktop: events ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShowWork:
    """Open the canvas: the agent's session asked to be seen."""

    focus: bool = False


@dataclass(frozen=True, slots=True)
class RouteSpeech:
    """Spoken words for the agent: the desktop sends them where its focus says (a waiting
    question, the canvas's instruction, or the conversation as `SpeakToAgent`)."""

    text: str


@dataclass(frozen=True, slots=True)
class Notify:
    """A tray notification; a warning also sounds."""

    title: str
    text: str
    warning: bool = field(default=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class OpenReference:
    """A work source's original document or page, for the desktop's shell to open."""

    url: str


@dataclass(frozen=True, slots=True)
class ReplyFailed:
    """A spoken reply to a canvas question could not be delivered."""


type DesktopEvent = ShowWork | RouteSpeech | Notify | OpenReference | ReplyFailed
type ToDesktop = DesktopState | DesktopEvent

# ---- to the assistant ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UseTool:
    """A tool chosen in the bar or tray that the assistant owns (stop, type a task, copy)."""

    tool: Tool


@dataclass(frozen=True, slots=True)
class Record:
    action: RecordingAction


@dataclass(frozen=True, slots=True)
class WorkCommand:
    command: WorkViewCommand


@dataclass(frozen=True, slots=True)
class EditCanvas:
    """A user edit the desktop has already applied to its copy; the assistant's is the record."""

    edit: UserEdit


@dataclass(frozen=True, slots=True)
class StartRun:
    run: CanvasRun


@dataclass(frozen=True, slots=True)
class ContinueWork:
    work_id: str


@dataclass(frozen=True, slots=True)
class AnswerCanvas:
    request: CanvasRequest
    answer: TextAnswer


@dataclass(frozen=True, slots=True)
class SelectAttention:
    request: CanvasRequest | None


@dataclass(frozen=True, slots=True)
class CanvasNoticed:
    """A canvas finding interrupted the user; the session announces it once."""

    title: str
    target: str


@dataclass(frozen=True, slots=True)
class SpeakToAgent:
    """Spoken words the desktop routed to the conversation."""

    text: str


@dataclass(frozen=True, slots=True)
class NoticesObserved:
    """Windows notifications the desktop observed, for the assistant's inbox triage."""

    observed: Observed


@dataclass(frozen=True, slots=True)
class WorkShown:
    """The canvas opened; the assistant refreshes what it shows."""


type ToAssistant = (
    UseTool
    | Record
    | WorkCommand
    | EditCanvas
    | StartRun
    | ContinueWork
    | AnswerCanvas
    | SelectAttention
    | CanvasNoticed
    | SpeakToAgent
    | NoticesObserved
    | WorkShown
)

# ---- the wire --------------------------------------------------------------------------

_TO_DESKTOP: Final[frozendict[str, TypeAdapter[ToDesktop]]] = frozendict(
    {
        kind.__name__: TypeAdapter[ToDesktop](kind)
        for kind in (
            SessionChanged,
            WorkChanged,
            CanvasChanged,
            VoiceChanged,
            JobChanged,
            RecordingChanged,
            AutomaticChanged,
            ShowWork,
            RouteSpeech,
            Notify,
            OpenReference,
            ReplyFailed,
        )
    }
)
_TO_ASSISTANT: Final[frozendict[str, TypeAdapter[ToAssistant]]] = frozendict(
    {
        kind.__name__: TypeAdapter[ToAssistant](kind)
        for kind in (
            UseTool,
            Record,
            WorkCommand,
            EditCanvas,
            StartRun,
            ContinueWork,
            AnswerCanvas,
            SelectAttention,
            CanvasNoticed,
            SpeakToAgent,
            NoticesObserved,
            WorkShown,
        )
    }
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
        case SessionChanged() | WorkChanged() | CanvasChanged() | VoiceChanged() | JobChanged() | RecordingChanged() | AutomaticChanged():
            return type(message).__name__
        case ShowWork() | RouteSpeech() | Notify() | OpenReference() | ReplyFailed():
            return None
        case _:
            assert_never(message)
