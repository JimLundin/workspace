"""What the island bar shows: a pure view of Workspace's activity, independent of Qt.

The bar's policy (docs/toolbar-design.md, "What the bar shows"):

- The island is the user's point of attention. Only dictation, live from the
  user, takes it over.
- Activities run concurrently and each keeps one identity wherever it shows:
  a quick job such as transcription (pulsing dots), and a meeting recording
  (a red dot and timer).
- Activities alone join the centre; at idle it is empty. While you dictate
  they detach beside it as compact capsules.
- The pinned web apps sit at the far left (the shell sections own that capsule).
  One fixed capsule anchors right: CPU and memory use, the keyboard while it types plainly,
  volume, Wi-Fi, clock and power. The system tray is in the controls menu.
- That capsule expands into the controls menu.
- Stoppable activities reveal Stop under the pointer.
"""

from dataclasses import dataclass, field
from enum import Enum, StrEnum, auto
from typing import Final, assert_never

from contracts.members import every_member
from contracts.recording_state import RecordingState
from contracts.status import TRANSCRIBING, Job
from desktop_ui.ambient import SPEAKERS, WIFI, Ambient, SystemStatus
from desktop_ui.components import meaning
from winapi.machine_status import Battery, PowerUnavailable


class Key(Enum):
    """Stable capsule identities; the layout owns each zone's ordering."""

    JOB = auto()
    ISLAND = auto()
    RECORDING = auto()
    STATUS = auto()


class Zone(Enum):
    LEAD = auto()
    ISLAND = auto()
    TRAIL = auto()
    RIGHT = auto()  # The fixed readings, independent of activity.


class Action(Enum):
    """What a press does. A capsule has one; each control inside it has its own."""

    OPEN_MENU = auto()
    CLOSE_MENU = auto()
    STOP_DICTATION = auto()
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
    reserve: str = field(default="", kw_only=True)  # Representative widest reading; never painted.


@dataclass(frozen=True, slots=True)
class Glyph:
    name: str
    tone: meaning.Tone = meaning.Tone.INK


@dataclass(frozen=True, slots=True)
class Control:
    icon: str
    label: str
    action: Action


type Part = Text | Glyph | Control | Marker
type Slot = tuple[Part, ...]


@dataclass(frozen=True, slots=True)
class CapsuleView:
    key: Key
    zone: Zone
    slots: tuple[Slot, ...]
    label: str
    action: Action
    tint: meaning.Tint = meaning.Tint.NONE


@dataclass(frozen=True, slots=True)
class Observed:
    """Everything the island depends on, each from its own owner."""

    job: Job | None
    recording: RecordingState
    ambient: Ambient
    system: SystemStatus
    plain_keyboard: bool = field(default=False, kw_only=True)
    """The layout is off (switched off, or the firmware keyboard is connected): the keyboard types plainly."""
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


# ---- the bar's composition as data: `ISLAND` ---------------------------------------------


class Reading(StrEnum):
    """A reading the status capsule can show; what each shows stays here."""

    KEYBOARD = auto()  # Only while the keyboard types plainly.
    SPEAKER = auto()
    WIFI = auto()
    CLOCK = auto()
    POWER = auto()
    BATTERY = auto()
    CPU = auto()
    MEMORY = auto()


class Activity(StrEnum):
    """A capsule beside the island; when each shows stays here."""

    JOB = auto()
    RECORDING = auto()


@dataclass(frozen=True, slots=True)
class StatusSpec:
    groups: tuple[tuple[Reading, ...], ...]
    """Left to right; readings in a group sit a part gap apart, groups a slot gap."""


@dataclass(frozen=True, slots=True)
class ActivitiesSpec:
    lead: tuple[Activity, ...]
    """Left of the island, left to right."""
    trail: tuple[Activity, ...]
    """Right of the island, left to right."""


@dataclass(frozen=True, slots=True)
class IslandSpec:
    """What the status capsule shows and where activities step aside to."""

    status: StatusSpec
    activities: ActivitiesSpec


ISLAND: Final = IslandSpec(
    # The fixed capsule at the screen's right edge, which opens the controls menu:
    # its readings left to right, in groups. Readings in a group sit close together;
    # groups sit further apart. Leave a reading out to hide it. The keyboard shows
    # only while it types plainly.
    status=StatusSpec(
        (
            (Reading.KEYBOARD, Reading.SPEAKER, Reading.WIFI),
            (Reading.POWER, Reading.BATTERY, Reading.CPU, Reading.MEMORY, Reading.CLOCK),
        )
    ),
    # Where activities sit beside the centre island, left to right. A transcription
    # and a recording step out of the island while you dictate. Each activity is
    # placed exactly once.
    activities=ActivitiesSpec(lead=(Activity.JOB,), trail=(Activity.RECORDING,)),
)
"""The island bar's composition."""


ACTIVITY_KEYS: Final = every_member(Activity, {Activity.JOB: Key.JOB, Activity.RECORDING: Key.RECORDING})


def order(spec: IslandSpec) -> tuple[Key, ...]:
    """Every capsule left to right: the lead, the island, the trail, then the status capsule."""
    lead = tuple(ACTIVITY_KEYS[each] for each in spec.activities.lead)
    trail = tuple(ACTIVITY_KEYS[each] for each in spec.activities.trail)
    return (*lead, Key.ISLAND, *trail, Key.STATUS)


def zone(key: Key, spec: IslandSpec) -> Zone:
    match key:
        case Key.ISLAND:
            return Zone.ISLAND
        case Key.STATUS:
            return Zone.RIGHT
        case Key.JOB | Key.RECORDING:
            return Zone.LEAD if any(ACTIVITY_KEYS[each] is key for each in spec.activities.lead) else Zone.TRAIL
        case _:
            assert_never(key)


def job_label(job: Job) -> str:
    return {TRANSCRIBING: "Transcribing"}[job]


def usage(percent: int | None) -> Text:
    """One resource's value, reserving its widest form so a changing value never shifts the cluster."""
    return Text("—" if percent is None else f"{percent}%", reserve="100%")


def reading(each: Reading, observed: Observed) -> Slot:
    """One reading's parts. Each reserves its widest form, and power keeps one glyph,
    so a changing reading never shifts the fixed cluster."""
    ambient, system = observed.ambient, observed.system
    match each:
        case Reading.KEYBOARD:
            return (Glyph("keyboard"),) if observed.plain_keyboard else ()
        case Reading.SPEAKER:
            return (Glyph(SPEAKERS[system.speakers].icon),)
        case Reading.WIFI:
            return (Glyph(WIFI[system.wifi].icon),)
        case Reading.CLOCK:
            return (Glyph("clock"), Text(ambient.clock, reserve="00:00"))
        case Reading.POWER:
            match ambient.power:
                case Battery(powered=True) | PowerUnavailable.NO_BATTERY:
                    return (Glyph("charger"),)
                case _:
                    return (Glyph("battery"),)
        case Reading.BATTERY:
            match ambient.power:
                case Battery(percent=percent, powered=False) if percent <= 20:
                    return (Text(ambient.battery_text, meaning.Tone.LOW, reserve="100%"),)
                case _:
                    return (Text(ambient.battery_text, reserve="100%"),)
        case Reading.CPU:
            return (Glyph("cpu"), usage(system.cpu))
        case Reading.MEMORY:
            return (Glyph("memory"), usage(system.memory))
        case _:
            assert_never(each)


def describe(ambient: Ambient) -> str:
    match ambient.power:
        case Battery(powered=True):
            charger = "Charger connected"
        case _:
            charger = ""
    return ". ".join(value for value in (ambient.text, charger) if value)


def recording_slot(recorded: Capture, *, hovered: bool) -> Slot:
    tone = meaning.Tone.LOW if recorded.attention else meaning.Tone.INK
    stop = (Control("stop", "Stop recording", Action.STOP_RECORDING),) if hovered and recorded.can_stop else ()
    return (Marker.DOT, Text(recorded.title, tone), *stop)


def island(observed: Observed, spec: IslandSpec, *, hovered: Key | None = None, expanded: bool = False) -> tuple[CapsuleView, ...]:
    """The capsules to show, in left-to-right order, with their contents and press actions.

    The right-hand readings expand into the controls menu (`expanded`), where
    ongoing activities become live rows, so they leave the bar.
    """
    job, recorded = observed.job, capture(observed.recording)
    detached = observed.dictating and not expanded
    lead: tuple[CapsuleView, ...] = ()
    if detached and job is not None:
        lead += (CapsuleView(Key.JOB, zone(Key.JOB, spec), ((Marker.DOTS,),), job_label(job), Action.OPEN_MENU),)
    trail: tuple[CapsuleView, ...] = ()
    if detached and recorded is not None:
        tint = meaning.Tint.ATTENTION if recorded.attention else meaning.Tint.NONE
        slot = recording_slot(recorded, hovered=hovered is Key.RECORDING)
        trail += (
            CapsuleView(Key.RECORDING, zone(Key.RECORDING, spec), (slot,), f"{recorded.title} · Open Workspace controls", Action.OPEN_MENU, tint),
        )
    # The readings stay the top row while their capsule expands into the menu; a
    # group whose readings are all absent (a keyboard typing normally) takes no space.
    groups = (tuple(part for each in group for part in reading(each, observed)) for group in spec.status.groups)
    readings: tuple[Slot, ...] = tuple(group for group in groups if group)
    persistent = (
        CapsuleView(Key.STATUS, Zone.RIGHT, readings, "Workspace controls · Escape closes", Action.CLOSE_MENU)
        if expanded
        else CapsuleView(
            Key.STATUS,
            Zone.RIGHT,
            readings,
            ". ".join((observed.system.resource_description, observed.system.description, describe(observed.ambient))) + " · Open Workspace controls",
            Action.OPEN_MENU,
        ),
    )
    active = observed.dictating or job is not None or recorded is not None
    middle = (centre(observed, recorded, hovered=hovered),) if active and not expanded else ()
    ranks = order(spec)
    return tuple(sorted((*lead, *middle, *trail, *persistent), key=lambda view: ranks.index(view.key)))


def centre(observed: Observed, recorded: Capture | None, *, hovered: Key | None) -> CapsuleView:
    """Only live activity belongs here; persistent readings have fixed right anchors. `recorded` is the recording as captured."""
    revealed = hovered is Key.ISLAND
    job = observed.job
    if observed.dictating:
        stop: Slot = (Control("stop", "Stop dictation", Action.STOP_DICTATION),) if revealed else ()
        slots: tuple[Slot, ...] = ((Glyph("mic.fill", meaning.Tone.MICROPHONE), Marker.WAVE, *stop),)
        return CapsuleView(Key.ISLAND, Zone.ISLAND, slots, "Listening · press to stop", Action.STOP_DICTATION)
    leading: tuple[Slot, ...] = ((Marker.DOTS,),) if job is not None else ()
    trailing: tuple[Slot, ...] = (recording_slot(recorded, hovered=revealed),) if recorded is not None else ()
    described = (job_label(job) if job is not None else "", recorded.title if recorded is not None else "")
    label = ". ".join(value for value in described if value)
    return CapsuleView(Key.ISLAND, Zone.ISLAND, (*leading, *trailing), f"{label} · Open Workspace controls", Action.OPEN_MENU)
