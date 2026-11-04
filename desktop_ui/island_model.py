"""What the island bar shows: a pure view of Workspace's activity, independent of Qt.

The bar's policy (docs/toolbar-design.md, "What the bar shows"):

- The island is the user's point of attention. Only a moment takes it over:
  something live from the user (dictation) or waiting on the user (a question).
- Activities run concurrently and each keeps one identity wherever it shows:
  agent work (a ring spinner and its current phase), a quick job such as
  transcription (pulsing dots), and a meeting recording (a red dot and timer).
- Activities alone join the centre; at idle it is empty. During a moment
  they detach beside it as compact capsules, phase and all.
- Canvas anchors at the far left before apps; temporary keyboard and the
  clock/power capsule anchor right. The tray toggle precedes them and expands left.
- That capsule expands into the controls menu; a question expands the centre island.
- Agent work keeps Stop visible; other stoppable activities reveal it under the pointer.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Final, assert_never

from assistant.recording_state import RecordingState
from desktop_ui.ambient import Ambient
from desktop_ui.components import meaning
from winapi.machine_status import Battery, PowerUnavailable


class Key(Enum):
    """Stable capsule identities; the layout owns each zone's ordering."""

    LAYER = auto()
    AGENT = auto()
    JOB = auto()
    ISLAND = auto()
    RECORDING = auto()
    INBOX = auto()
    CANVAS = auto()
    STATUS = auto()


class Zone(Enum):
    LEAD = auto()
    ISLAND = auto()
    TRAIL = auto()
    LEFT = auto()  # Canvas precedes the application strip at the screen's left edge.
    RIGHT = auto()  # Fixed keyboard and readings, independent of activity.


class Expansion(Enum):
    """What the bar has opened: the controls menu, or a question in the island."""

    MENU = auto()
    REQUEST = auto()


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
    reserve: str = field(default="", kw_only=True)  # Representative widest reading; never painted.


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


def facts(ambient: Ambient) -> Slot:
    """Reserve the widest readings and one power glyph so the fixed cluster never shifts."""
    match ambient.power:
        case Battery(powered=True) | PowerUnavailable.NO_BATTERY:
            power = Glyph("charger")
        case _:
            power = Glyph("battery")
    match ambient.power:
        case Battery(percent=percent, powered=False) if percent <= 20:
            battery = Text(ambient.battery_text, meaning.Tone.LOW, reserve="100%")
        case _:
            battery = Text(ambient.battery_text, reserve="100%")
    return (Text(ambient.clock, reserve="00:00"), power, battery)


def describe(ambient: Ambient) -> str:
    match ambient.power:
        case Battery(powered=True):
            charger = "Charger connected"
        case _:
            charger = ""
    return ". ".join(value for value in (ambient.text, charger) if value)


def inbox_text(count: int) -> str:
    return "99+" if count > 99 else str(count)


def inbox_label(count: int) -> str:
    return f"{count} {'clarification needs' if count == 1 else 'clarifications need'} your input · Review request · Hold V + T"


def recording_slot(recorded: Capture, *, hovered: bool) -> Slot:
    tone = meaning.Tone.LOW if recorded.attention else meaning.Tone.INK
    stop = (Control("stop", "Stop recording", Action.STOP_RECORDING),) if hovered and recorded.can_stop else ()
    return (Marker.DOT, Text(recorded.title, tone), *stop)


def island(observed: Observed, *, hovered: Key | None = None, expanded: Expansion | None = None) -> tuple[CapsuleView, ...]:
    """The capsules to show, in left-to-right order, with their contents and press actions.

    The right-hand readings expand into the controls menu, where ongoing activities
    become live rows, so they leave the bar; Canvas, the layer and the inbox stay.
    A question expands the centre island instead.
    """
    agent, job, recorded = observed.agent, observed.job, capture(observed.recording)
    asking = agent is not None and agent.waiting
    detached = (observed.dictating or asking) and expanded is None
    layer: tuple[CapsuleView, ...] = ()
    if observed.keyboard is not None:
        layer = (CapsuleView(Key.LAYER, Zone.RIGHT, ((Glyph("keyboard"),),), f"{observed.keyboard} · Open key map", Action.OPEN_KEYMAP),)
    lead: tuple[CapsuleView, ...] = ()
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
    # The readings stay the top row while their capsule expands into the menu.
    readings: tuple[Slot, ...] = (facts(observed.ambient),)
    persistent = (
        CapsuleView(Key.CANVAS, Zone.LEFT, ((Glyph("canvas"),),), "Canvas · Open your work canvas", Action.OPEN_CANVAS),
        *layer,
        CapsuleView(Key.STATUS, Zone.RIGHT, readings, "Workspace controls · Escape closes", Action.CLOSE_MENU)
        if expanded is Expansion.MENU
        else CapsuleView(Key.STATUS, Zone.RIGHT, readings, describe(observed.ambient) + " · Open Workspace controls", Action.OPEN_MENU),
    )
    if observed.inbox > 0:
        trail += (
            CapsuleView(Key.INBOX, Zone.TRAIL, ((Glyph("bell"), Badge(inbox_text(observed.inbox))),), inbox_label(observed.inbox), Action.OPEN_INBOX),
        )
    middle: tuple[CapsuleView, ...]
    match expanded:
        case Expansion.MENU:
            middle = ()
        case Expansion.REQUEST:
            middle = (CapsuleView(Key.ISLAND, Zone.ISLAND, (), "Workspace controls · Escape closes", Action.CLOSE_MENU),)
        case None:
            active = observed.dictating or agent is not None or job is not None or recorded is not None
            middle = (centre(observed, hovered=hovered),) if active else ()
        case _:
            assert_never(expanded)
    return (*lead, *middle, *trail, *persistent)


def centre(observed: Observed, *, hovered: Key | None) -> CapsuleView:
    """Only live activity belongs here; persistent readings have fixed right anchors."""
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
        recorded.title if recorded is not None else "",
    )
    label = ". ".join(value for value in described if value)
    return CapsuleView(
        Key.ISLAND,
        Zone.ISLAND,
        (*leading, *trailing),
        f"{label} · Open Workspace controls",
        Action.OPEN_MENU,
    )
