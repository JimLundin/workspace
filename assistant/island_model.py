"""What the island bar shows: a pure view of Workspace's state, independent of Qt.

At rest the island holds the time, battery and system alerts. Processing (transcription
or agent work) takes the island's leading slot, and a meeting recording its trailing
slot. A moment (dictation, or a question waiting for an answer) takes the island over;
processing and recording then detach as capsules beside it. Only temporary or active
things sit beside the island: the keyboard layer before it, and the inbox, while items
wait, after it. Hovering the island reveals Stop beside each activity that can stop.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import assert_never

from assistant.ambient import Ambient, SystemStatus
from assistant.icons import State
from assistant.recording_state import RecordingState
from winapi.machine_status import Battery


class Key(Enum):
    """Capsules, in their left-to-right order."""

    LAYER = auto()
    AGENT = auto()
    ISLAND = auto()
    RECORDING = auto()
    INBOX = auto()


class Zone(Enum):
    LEAD = auto()
    ISLAND = auto()
    TRAIL = auto()


class Action(Enum):
    """What a press does. A capsule has one; each control inside it has its own."""

    OPEN_MENU = auto()
    STOP_DICTATION = auto()
    OPEN_QUESTION = auto()
    OPEN_INBOX = auto()
    OPEN_CANVAS = auto()
    OPEN_KEYMAP = auto()
    STOP_AGENT = auto()
    STOP_RECORDING = auto()


class Tone(Enum):
    INK = auto()
    QUIET = auto()
    MICROPHONE = auto()
    LOW = auto()


class Tint(Enum):
    NONE = auto()
    ATTENTION = auto()


class Marker(Enum):
    """Live indicators without a payload."""

    WAVE = auto()
    DOT = auto()


@dataclass(frozen=True, slots=True)
class Text:
    text: str
    tone: Tone = Tone.INK
    strong: bool = field(default=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class Glyph:
    name: str
    tone: Tone = Tone.INK


@dataclass(frozen=True, slots=True)
class Spinner:
    label: str


@dataclass(frozen=True, slots=True)
class Badge:
    text: str


@dataclass(frozen=True, slots=True)
class Control:
    icon: str
    label: str
    action: Action


type Part = Text | Glyph | Spinner | Badge | Control | Marker
type Slot = tuple[Part, ...]


@dataclass(frozen=True, slots=True)
class CapsuleView:
    key: Key
    zone: Zone
    slots: tuple[Slot, ...]
    label: str
    action: Action
    tint: Tint = Tint.NONE


@dataclass(frozen=True, slots=True)
class Observed:
    """Everything the island depends on, observed by the bar's owner."""

    state: State
    recording: RecordingState
    ambient: Ambient
    system: SystemStatus
    inbox: int
    keyboard: str | None


@dataclass(frozen=True, slots=True)
class Capture:
    """A recording phase as the bar shows it: its reading and whether it can still stop."""

    title: str
    can_stop: bool = field(kw_only=True)
    attention: bool = field(kw_only=True)


def capture(recording: RecordingState) -> Capture | None:
    seconds = max(0, int(recording.seconds))
    hours, minutes, rest = seconds // 3600, seconds // 60 % 60, seconds % 60
    clock = f"{hours}:{minutes:02}:{rest:02}" if hours else f"{minutes:02}:{rest:02}"
    match recording.phase:
        case "starting":
            return Capture("Starting…", can_stop=True, attention=False)
        case "recording":
            return Capture(clock, can_stop=True, attention=False)
        case "stopping":
            return Capture("Stopping…", can_stop=False, attention=False)
        case "finishing":
            return Capture("Saving…", can_stop=False, attention=False)
        case "paused" | "interrupted":
            return Capture("Check recording", can_stop=False, attention=True)
        case "idle" | "saved":
            return None
        case _:
            assert_never(recording.phase)


def keyboard(*, enabled: bool, layer: str | None) -> str | None:
    """Only a temporary layer, or the layout switched off, earns a capsule."""
    return "Colemak" if not enabled else layer


def processing(state: State) -> Spinner | None:
    match state:
        case State.WORKING:
            return Spinner("Transcribing")
        case State.AGENT:
            return Spinner("Agent working")
        case State.READY | State.LAYOUT_OFF | State.LISTENING | State.RECORDING | State.NEEDS_INPUT:
            return None
        case _:
            assert_never(state)


def facts(ambient: Ambient, system: SystemStatus) -> Slot:
    """Alerts, the clock, the charger while plugged in, and the battery level when it's worth reading."""
    match ambient.power:
        case Battery(powered=True):
            charger: Slot = (Glyph("charger"),)
        case _:
            charger = ()
    match ambient.power:
        case _ if not ambient.battery_text:
            battery: Slot = ()
        case Battery(percent=percent, powered=False) if percent <= 20:
            battery = (Text(ambient.battery_text, Tone.LOW),)
        case _:
            battery = (Text(ambient.battery_text),)
    return (*(Glyph(alert) for alert in system.alerts), Text(ambient.clock), *charger, *battery)


def describe(ambient: Ambient, system: SystemStatus) -> str:
    match ambient.power:
        case Battery(powered=True):
            charger = "Charger connected"
        case _:
            charger = ""
    return ". ".join(value for value in (ambient.text, charger, system.description) if value)


def inbox_text(count: int) -> str:
    return "99+" if count > 99 else str(count)


def inbox_label(count: int) -> str:
    return f"{count} {'clarification needs' if count == 1 else 'clarifications need'} your input · open canvas · Hold V + T"


def recording_slot(recorded: Capture, *, hovered: bool) -> Slot:
    tone = Tone.LOW if recorded.attention else Tone.INK
    stop = (Control("stop", "Stop recording", Action.STOP_RECORDING),) if hovered and recorded.can_stop else ()
    return (Marker.DOT, Text(recorded.title, tone), *stop)


def island(observed: Observed, *, hovered: Key | None = None) -> tuple[CapsuleView, ...]:
    """The capsules to show, in left-to-right order, with their contents and press actions."""
    spinner = processing(observed.state)
    recorded = capture(observed.recording)
    listening, asking = observed.state is State.LISTENING, observed.state is State.NEEDS_INPUT
    moment = listening or asking
    lead: tuple[CapsuleView, ...] = ()
    if observed.keyboard is not None:
        lead += (
            CapsuleView(
                Key.LAYER, Zone.LEAD, ((Glyph("keyboard"), Text(observed.keyboard)),), f"{observed.keyboard} · Open key map", Action.OPEN_KEYMAP
            ),
        )
    if moment and spinner is not None:
        lead += (CapsuleView(Key.AGENT, Zone.LEAD, ((spinner,),), spinner.label, Action.OPEN_MENU),)
    trail: tuple[CapsuleView, ...] = ()
    if moment and recorded is not None:
        tint = Tint.ATTENTION if recorded.attention else Tint.NONE
        slot = recording_slot(recorded, hovered=hovered is Key.RECORDING)
        trail += (CapsuleView(Key.RECORDING, Zone.TRAIL, (slot,), f"{recorded.title} · Open canvas", Action.OPEN_CANVAS, tint),)
    if observed.inbox > 0:
        trail += (
            CapsuleView(Key.INBOX, Zone.TRAIL, ((Glyph("bell"), Badge(inbox_text(observed.inbox))),), inbox_label(observed.inbox), Action.OPEN_INBOX),
        )
    return (*lead, centre(observed, hovered=hovered), *trail)


def centre(observed: Observed, *, hovered: Key | None) -> CapsuleView:
    """The island itself: a moment takes it over; otherwise processing and recording join its slots."""
    revealed = hovered is Key.ISLAND
    if observed.state is State.LISTENING:
        stop: Slot = (Control("stop", "Stop dictation", Action.STOP_DICTATION),) if revealed else ()
        slots: tuple[Slot, ...] = ((Glyph("mic.fill", Tone.MICROPHONE), Marker.WAVE, *stop),)
        return CapsuleView(Key.ISLAND, Zone.ISLAND, slots, "Listening · press to stop", Action.STOP_DICTATION)
    if observed.state is State.NEEDS_INPUT:
        slots = ((Text("Needs you", strong=True), Glyph("down")),)
        return CapsuleView(Key.ISLAND, Zone.ISLAND, slots, "An agent question needs you · open it", Action.OPEN_QUESTION, Tint.ATTENTION)
    spinner, recorded = processing(observed.state), capture(observed.recording)
    stop = (Control("stop", "Stop agent work", Action.STOP_AGENT),) if revealed and observed.state is State.AGENT else ()
    leading: tuple[Slot, ...] = ((spinner, *stop),) if spinner is not None else ()
    trailing: tuple[Slot, ...] = (recording_slot(recorded, hovered=revealed),) if recorded is not None else ()
    described = (
        spinner.label if spinner is not None else "",
        describe(observed.ambient, observed.system),
        recorded.title if recorded is not None else "",
    )
    label = ". ".join(value for value in described if value)
    return CapsuleView(
        Key.ISLAND,
        Zone.ISLAND,
        (*leading, facts(observed.ambient, observed.system), *trailing),
        f"{label} · Open Workspace controls",
        Action.OPEN_MENU,
    )
