"""What the island bar shows: a pure view of Workspace's activity, independent of Qt.

The bar's policy (docs/toolbar-design.md, "What the bar shows"):

- The island is the user's point of attention. Only a moment takes it over:
  something live from the user (dictation) or waiting on the user (a question).
- Activities run concurrently and each keeps one identity wherever it shows:
  agent work (a ring spinner and its current phase), a quick job such as
  transcription (pulsing dots), and a meeting recording (a red dot and timer).
- At rest the activities join the island's slots around the time and battery.
  During a moment they detach beside it as compact capsules, phase and all.
- Only temporary or active things sit beside the island: the keyboard layer
  before it, the inbox after it while items wait. Nothing persistent.
- Agent work keeps Stop visible; other stoppable activities reveal it under the pointer.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Final, assert_never

from assistant.recording_state import RecordingState
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.components import meaning
from winapi.machine_status import Battery


class Key(Enum):
    """Capsules, in their left-to-right order."""

    LAYER = auto()
    AGENT = auto()
    JOB = auto()
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
    CLOSE_MENU = auto()
    STOP_DICTATION = auto()
    OPEN_QUESTION = auto()
    OPEN_INBOX = auto()
    OPEN_CANVAS = auto()
    OPEN_KEYMAP = auto()
    STOP_AGENT = auto()
    STOP_RECORDING = auto()


class Marker(Enum):
    """Live indicators without a payload."""

    WAVE = auto()
    DOT = auto()
    DOTS = auto()  # A quick job in progress.


@dataclass(frozen=True, slots=True)
class Text:
    text: str
    tone: meaning.Tone = meaning.Tone.INK
    strong: bool = field(default=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class Glyph:
    name: str
    tone: meaning.Tone = meaning.Tone.INK


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
    tint: meaning.Tint = meaning.Tint.NONE


class Job(Enum):
    """A quick job Workspace runs for you after a key press."""

    TRANSCRIBING = auto()  # speech to text after dictation
    ANSWERING = auto()  # a rewrite, a question about the selection or the screen


@dataclass(frozen=True, slots=True)
class Agent:
    """Agent work in progress: its phase, and whether it waits for an answer from you."""

    phase: str
    waiting: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Observed:
    """Everything the island depends on, each from its own owner."""

    agent: Agent | None
    job: Job | None
    recording: RecordingState
    ambient: Ambient
    system: SystemStatus
    inbox: int
    keyboard: str | None
    dictating: bool = field(kw_only=True)


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


PHASE: Final = 28  # The phase's characters in the island before it elides.


def elided(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def job_label(job: Job) -> str:
    match job:
        case Job.TRANSCRIBING:
            return "Transcribing"
        case Job.ANSWERING:
            return "Answering"
        case _:
            assert_never(job)


def agent_slot(agent: Agent, *, compact: bool) -> Slot:
    """The agent's spinner and phase; compact capsules keep the phase for their label."""
    stop = (Control("stop", "Stop agent work", Action.STOP_AGENT),) if not agent.waiting else ()
    phase = () if compact else (Text(elided(agent.phase, PHASE)),)
    return (Spinner("Agent: " + agent.phase), *phase, *stop)


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
            battery = (Text(ambient.battery_text, meaning.Tone.LOW),)
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
    return f"{count} {'clarification needs' if count == 1 else 'clarifications need'} your input · Review request · Hold V + T"


def recording_slot(recorded: Capture, *, hovered: bool) -> Slot:
    tone = meaning.Tone.LOW if recorded.attention else meaning.Tone.INK
    stop = (Control("stop", "Stop recording", Action.STOP_RECORDING),) if hovered and recorded.can_stop else ()
    return (Marker.DOT, Text(recorded.title, tone), *stop)


def island(observed: Observed, *, hovered: Key | None = None, expanded: bool = False) -> tuple[CapsuleView, ...]:
    """The capsules to show, in left-to-right order, with their contents and press actions.

    While `expanded`, the island is the controls menu: ongoing activities move into
    its live rows, so they leave the bar; the layer and the inbox stay.
    """
    agent, job, recorded = observed.agent, observed.job, capture(observed.recording)
    asking = agent is not None and agent.waiting
    detached = (observed.dictating or asking) and not expanded
    lead: tuple[CapsuleView, ...] = ()
    if observed.keyboard is not None:
        lead += (
            CapsuleView(
                Key.LAYER, Zone.LEAD, ((Glyph("keyboard"), Text(observed.keyboard)),), f"{observed.keyboard} · Open key map", Action.OPEN_KEYMAP
            ),
        )
    # Dictation detaches the agent; a waiting question already is the island, unless you're dictating.
    if detached and agent is not None and observed.dictating:
        tint = meaning.Tint.ATTENTION if agent.waiting else meaning.Tint.NONE
        slot = agent_slot(agent, compact=True)
        action = Action.OPEN_QUESTION if agent.waiting else Action.OPEN_MENU
        lead += (CapsuleView(Key.AGENT, Zone.LEAD, (slot,), f"Agent · {agent.phase}", action, tint),)
    if detached and job is not None:
        lead += (CapsuleView(Key.JOB, Zone.LEAD, ((Marker.DOTS,),), job_label(job), Action.OPEN_MENU),)
    trail: tuple[CapsuleView, ...] = ()
    if detached and recorded is not None:
        tint = meaning.Tint.ATTENTION if recorded.attention else meaning.Tint.NONE
        slot = recording_slot(recorded, hovered=hovered is Key.RECORDING)
        trail += (CapsuleView(Key.RECORDING, Zone.TRAIL, (slot,), f"{recorded.title} · Open canvas", Action.OPEN_CANVAS, tint),)
    if observed.inbox > 0:
        trail += (
            CapsuleView(Key.INBOX, Zone.TRAIL, ((Glyph("bell"), Badge(inbox_text(observed.inbox))),), inbox_label(observed.inbox), Action.OPEN_INBOX),
        )
    menu = CapsuleView(Key.ISLAND, Zone.ISLAND, (), "Workspace controls · Escape closes", Action.CLOSE_MENU)
    return (*lead, menu if expanded else centre(observed, hovered=hovered), *trail)


def centre(observed: Observed, *, hovered: Key | None) -> CapsuleView:
    """The island itself: a moment takes it over; otherwise the activities join its slots."""
    revealed = hovered is Key.ISLAND
    agent, job, recorded = observed.agent, observed.job, capture(observed.recording)
    if observed.dictating:
        stop: Slot = (Control("stop", "Stop dictation", Action.STOP_DICTATION),) if revealed else ()
        slots: tuple[Slot, ...] = ((Glyph("mic.fill", meaning.Tone.MICROPHONE), Marker.WAVE, *stop),)
        return CapsuleView(Key.ISLAND, Zone.ISLAND, slots, "Listening · press to stop", Action.STOP_DICTATION)
    if agent is not None and agent.waiting:
        slots = ((Text("Needs you", strong=True), Glyph("down")),)
        return CapsuleView(
            Key.ISLAND, Zone.ISLAND, slots, f"An agent question needs you: {agent.phase} · open it", Action.OPEN_QUESTION, meaning.Tint.ATTENTION
        )
    leading: tuple[Slot, ...] = (
        *((agent_slot(agent, compact=False),) if agent is not None else ()),
        *(((Marker.DOTS,),) if job is not None else ()),
    )
    trailing: tuple[Slot, ...] = (recording_slot(recorded, hovered=revealed),) if recorded is not None else ()
    described = (
        f"Agent: {agent.phase}" if agent is not None else "",
        job_label(job) if job is not None else "",
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
