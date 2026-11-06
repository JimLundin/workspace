"""What the island bar shows: a pure view of Workspace's activity, independent of Qt.

The bar's policy (docs/toolbar-design.md, "What the bar shows"):

- The island is the user's point of attention. Only a moment takes it over:
  something live from the user (dictation), waiting on the user (a question),
  or news for the user (a notice), in that priority (`island_moment`).
- Activities run concurrently and each keeps one identity wherever it shows:
  agent work (a ring spinner and its current phase), a quick job such as
  transcription (pulsing dots), and a meeting recording (a red dot and timer).
- Activities alone join the centre; at idle it is empty. During a moment
  they detach beside it as compact capsules, phase and all.
- Canvas leads the pinned web apps at the far left (the shell sections own that capsule).
  One fixed capsule anchors right: CPU and memory use, the keyboard while it types plainly,
  volume, Wi-Fi, clock and power. The system tray is in the controls menu.
- That capsule expands into the controls menu; a question or the bell's list expands the centre island.
- Under the pointer, agent work reveals its recent steps below its phase, at the same width.
- Agent work keeps Stop visible; other stoppable activities reveal it under the pointer.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Final, assert_never

from assistant.recording_state import RecordingState
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.components import meaning
from desktop_ui.island_moment import Notice
from winapi.machine_status import Battery, PowerUnavailable


class Key(Enum):
    """Stable capsule identities; the layout owns each zone's ordering."""

    AGENT = auto()
    JOB = auto()
    ISLAND = auto()
    RECORDING = auto()
    INBOX = auto()
    STATUS = auto()


class Zone(Enum):
    LEAD = auto()
    ISLAND = auto()
    TRAIL = auto()
    RIGHT = auto()  # The fixed readings, independent of activity.


class Expansion(Enum):
    """What the bar has opened: the controls menu, a question in the island, or the bell's list there."""

    MENU = auto()
    REQUEST = auto()
    INBOX = auto()


class Action(Enum):
    """What a press does. A capsule has one; each control inside it has its own."""

    OPEN_MENU = auto()
    CLOSE_MENU = auto()
    STOP_DICTATION = auto()
    OPEN_QUESTION = auto()
    OPEN_INBOX = auto()
    OPEN_CANVAS = auto()
    STOP_AGENT = auto()
    STOP_RECORDING = auto()
    OPEN_NOTICE = auto()
    DISMISS_NOTICE = auto()


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
class Detail:
    """Quiet lines under a capsule's row: a notice's reply, or the agent's recent steps."""

    paragraphs: tuple[str, ...]
    rows: int  # Lines each paragraph may wrap to; the last one elides.
    width: float = 0  # The capsule's width; 0 keeps the row's.


@dataclass(frozen=True, slots=True)
class CapsuleView:
    key: Key
    zone: Zone
    slots: tuple[Slot, ...]
    label: str
    action: Action
    tint: meaning.Tint = meaning.Tint.NONE
    detail: Detail | None = field(default=None, kw_only=True)


class Job(Enum):
    """A quick job Workspace runs for you after a key press."""

    TRANSCRIBING = auto()  # speech to text after dictation


@dataclass(frozen=True, slots=True)
class Agent:
    """Agent work in progress: its phase, its steps before it, and whether it waits for an answer from you."""

    phase: str
    waiting: bool = field(kw_only=True)
    steps: tuple[str, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class Observed:
    """Everything the island depends on, each from its own owner."""

    agent: Agent | None
    job: Job | None
    recording: RecordingState
    ambient: Ambient
    system: SystemStatus
    inbox: int  # Waiting questions.
    plain_keyboard: bool = field(default=False, kw_only=True)
    """The layout is off (switched off, or the firmware keyboard is connected): the keyboard types plainly."""
    dictating: bool = field(kw_only=True)
    unread: int = field(default=0, kw_only=True)  # Notices that collapsed into the bell.
    notice: Notice | None = field(default=None, kw_only=True)  # The notice holding the island; `island_moment` decides.


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


PHASE: Final = 28  # The phase's characters in the island before it elides.
TITLE: Final = 44  # A notice title's characters before it elides.
NOTICE_WIDTH: Final = 340


def elided(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def job_label(job: Job) -> str:
    match job:
        case Job.TRANSCRIBING:
            return "Transcribing"
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


def usage(percent: int | None) -> Text:
    """One resource's value, reserving its widest form so a changing value never shifts the cluster."""
    return Text("—" if percent is None else f"{percent}%", reserve="100%")


def resources(system: SystemStatus) -> Slot:
    """The processor and memory, each its symbol then its value."""
    return (Glyph("cpu"), usage(system.cpu), Glyph("memory"), usage(system.memory))


def describe(ambient: Ambient) -> str:
    match ambient.power:
        case Battery(powered=True):
            charger = "Charger connected"
        case _:
            charger = ""
    return ". ".join(value for value in (ambient.text, charger) if value)


def inbox_text(count: int) -> str:
    return "99+" if count > 99 else str(count)


def inbox_label(questions: int, unread: int) -> str:
    asking = f"{questions} {'clarification needs' if questions == 1 else 'clarifications need'} your input" if questions else ""
    news = f"{unread} new from the agent" if unread else ""
    return " · ".join(part for part in (asking, news, "Open inbox · Hold V + T") if part)


def recording_slot(recorded: Capture, *, hovered: bool) -> Slot:
    tone = meaning.Tone.LOW if recorded.attention else meaning.Tone.INK
    stop = (Control("stop", "Stop recording", Action.STOP_RECORDING),) if hovered and recorded.can_stop else ()
    return (Marker.DOT, Text(recorded.title, tone), *stop)


def island(observed: Observed, *, hovered: Key | None = None, expanded: Expansion | None = None) -> tuple[CapsuleView, ...]:
    """The capsules to show, in left-to-right order, with their contents and press actions.

    The right-hand readings expand into the controls menu, where ongoing activities
    become live rows, so they leave the bar; the inbox stays.
    A question expands the centre island instead.
    """
    agent, job, recorded = observed.agent, observed.job, capture(observed.recording)
    asking = agent is not None and agent.waiting
    detached = (observed.dictating or asking or observed.notice is not None) and expanded is None
    lead: tuple[CapsuleView, ...] = ()
    # Dictation and a notice detach the agent; a waiting question already is the island, unless you're dictating.
    if detached and agent is not None and (observed.dictating or not agent.waiting):
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
    # A plain keyboard shows as one more reading, beside the speaker and Wi-Fi.
    # Processor and memory lead, so the device glyphs part their percentages from the battery's.
    keyboard = (Glyph("keyboard"),) if observed.plain_keyboard else ()
    readings: tuple[Slot, ...] = (
        resources(observed.system),
        (*keyboard, Glyph(observed.system.speaker_icon), Glyph(observed.system.wifi_icon)),
        facts(observed.ambient),
    )
    persistent = (
        CapsuleView(Key.STATUS, Zone.RIGHT, readings, "Workspace controls · Escape closes", Action.CLOSE_MENU)
        if expanded is Expansion.MENU
        else CapsuleView(
            Key.STATUS,
            Zone.RIGHT,
            readings,
            ". ".join((observed.system.resource_description, observed.system.description, describe(observed.ambient))) + " · Open Workspace controls",
            Action.OPEN_MENU,
        ),
    )
    count = observed.inbox + observed.unread
    if count > 0:
        label = inbox_label(observed.inbox, observed.unread)
        trail += (CapsuleView(Key.INBOX, Zone.TRAIL, ((Glyph("bell"), Badge(inbox_text(count))),), label, Action.OPEN_INBOX),)
    middle: tuple[CapsuleView, ...]
    match expanded:
        case Expansion.MENU:
            middle = ()
        case Expansion.REQUEST | Expansion.INBOX:
            middle = (CapsuleView(Key.ISLAND, Zone.ISLAND, (), "Workspace controls · Escape closes", Action.CLOSE_MENU),)
        case None:
            active = observed.dictating or observed.notice is not None or agent is not None or job is not None or recorded is not None
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
    if observed.notice is not None:
        return notice_view(observed.notice, revealed=revealed)
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
    # Under the pointer, agent work shows the steps before its phase, without widening.
    steps = Detail(agent.steps, 1) if revealed and agent is not None and agent.steps else None
    return CapsuleView(Key.ISLAND, Zone.ISLAND, (*leading, *trailing), f"{label} · Open Workspace controls", Action.OPEN_MENU, detail=steps)


def notice_view(notice: Notice, *, revealed: bool) -> CapsuleView:
    """The agent's news: its title and up to two lines of it; the pointer reveals Dismiss."""
    dismiss: Slot = (Control("close", "Dismiss", Action.DISMISS_NOTICE),) if revealed else ()
    symbol = Glyph("bell") if notice.question else Glyph("agent")
    slots: tuple[Slot, ...] = ((symbol, Text(elided(notice.title, TITLE), strong=True)), dismiss)
    detail = Detail((notice.text,), 2, NOTICE_WIDTH) if notice.text else None
    tint = meaning.Tint.ATTENTION if notice.question else meaning.Tint.NONE
    label = ": ".join(part for part in (notice.title, notice.text) if part) + " · Open on canvas"
    return CapsuleView(Key.ISLAND, Zone.ISLAND, slots, label, Action.OPEN_NOTICE, tint, detail=detail)
