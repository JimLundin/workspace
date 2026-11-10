"""What the island bar shows: a pure view of Workspace's activity, independent of Qt.

The bar's policy (docs/toolbar-design.md, "What the bar shows"):

- The island is the user's point of attention. Only dictation, live from the
  user, takes it over.
- Activities run concurrently and each keeps one identity wherever it shows:
  a quick job such as transcription (pulsing dots), and a meeting recording
  (a red dot and timer).
- Activities alone join the island, just left of the fixed capsule; at idle it is empty. While you dictate
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
from contracts.recording_state import Phase, RecordingState
from contracts.status import Job
from desktop_ui import ambient
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.components import meaning
from winapi.machine_status import Battery, PowerUnavailable, Speakers, Wifi


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


ELAPSED = sentinel("ELAPSED")
"""A phase that reads as the recording's elapsed time."""


@dataclass(frozen=True, slots=True)
class Phased:
    """How a recording phase shows: its title, or its elapsed time, and whether it can stop or needs you."""

    title: str | ELAPSED
    can_stop: bool = field(kw_only=True)
    attention: bool = field(kw_only=True)


type Phases = frozendict[Phase, Phased | None]
"""Each phase's look; a phase that maps to None doesn't show."""


def capture(recording: RecordingState, phases: Phases) -> Capture | None:
    phased = phases[recording.phase]
    if phased is None:
        return None
    seconds = max(0, int(recording.seconds))
    hours, minutes, rest = seconds // 3600, seconds // 60 % 60, seconds % 60
    clock = f"{hours}:{minutes:02}:{rest:02}" if hours else f"{minutes:02}:{rest:02}"
    title = clock if phased.title is ELAPSED else phased.title
    return Capture(title, can_stop=phased.can_stop, attention=phased.attention)


# ---- the bar's composition's shape: `desktop.bar.ISLAND` declares one ----------------------


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


@dataclass(frozen=True, slots=True, kw_only=True)
class Symbols:
    """The status readings' symbols."""

    keyboard: str
    clock: str
    charger: str
    battery: str
    cpu: str
    memory: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Words:
    """What the island's activities say and show."""

    jobs: frozendict[Job, str]
    phases: Phases
    stop: str
    """The Stop control's symbol."""
    microphone: str
    stop_recording: str
    stop_dictation: str
    listening: str
    """Dictation's accessible name."""
    open_controls: str
    """After a capsule's description: pressing it opens the controls."""
    close_controls: str
    """The expanded status capsule's name."""
    charger: str
    """Said of a connected charger."""
    cpu: str
    memory: str
    unavailable: str
    """Said of a resource not yet read."""


@dataclass(frozen=True, slots=True)
class StatusSpec:
    groups: tuple[tuple[Reading, ...], ...]
    """Left to right; readings in a group sit a part gap apart, groups a slot gap."""
    speakers: frozendict[Speakers, ambient.Reading]
    """The speakers' symbol and words in each state."""
    wifi: frozendict[Wifi, ambient.Reading]
    """Wi-Fi's symbol and words in each state."""
    symbols: Symbols
    low_battery: int
    """The battery percentage at or below which, on its own power, the reading warns."""
    unread: str
    """A reading not yet read, rather than a healthy-looking 0%."""
    mains: str
    """The battery reading on a machine without one."""
    widest_percent: str
    widest_clock: str
    """The widest reading of each kind, which its room keeps, so a changing value never shifts the capsule."""


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
    words: Words


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


def battery_text(ambient: Ambient, status: StatusSpec) -> str:
    match ambient.power:
        case Battery(percent=percent):
            return f"{percent}%"
        case PowerUnavailable.NO_BATTERY:
            return status.mains
        case PowerUnavailable.UNKNOWN:
            return status.unread
        case _:
            assert_never(ambient.power)


def resources(system: SystemStatus, words: Words) -> str:
    """The processor and memory readings, as words."""

    def said(name: str, percent: int | None) -> str:
        return f"{name} {words.unavailable}" if percent is None else f"{name} {percent}%"

    return said(words.cpu, system.cpu) + ", " + said(words.memory, system.memory)


def usage(percent: int | None, status: StatusSpec) -> Text:
    """One resource's value, reserving its widest form so a changing value never shifts the cluster."""
    return Text(status.unread if percent is None else f"{percent}%", reserve=status.widest_percent)


def reading(each: Reading, observed: Observed, status: StatusSpec) -> Slot:
    """One reading's parts. Each reserves its widest form, and power keeps one glyph,
    so a changing reading never shifts the fixed cluster."""
    ambient, system, symbols = observed.ambient, observed.system, status.symbols
    match each:
        case Reading.KEYBOARD:
            return (Glyph(symbols.keyboard),) if observed.plain_keyboard else ()
        case Reading.SPEAKER:
            return (Glyph(status.speakers[system.speakers].icon),)
        case Reading.WIFI:
            return (Glyph(status.wifi[system.wifi].icon),)
        case Reading.CLOCK:
            return (Glyph(symbols.clock), Text(ambient.clock, reserve=status.widest_clock))
        case Reading.POWER:
            match ambient.power:
                case Battery(powered=True) | PowerUnavailable.NO_BATTERY:
                    return (Glyph(symbols.charger),)
                case _:
                    return (Glyph(symbols.battery),)
        case Reading.BATTERY:
            match ambient.power:
                case Battery(percent=percent, powered=False) if percent <= status.low_battery:
                    return (Text(battery_text(ambient, status), meaning.Tone.LOW, reserve=status.widest_percent),)
                case _:
                    return (Text(battery_text(ambient, status), reserve=status.widest_percent),)
        case Reading.CPU:
            return (Glyph(symbols.cpu), usage(system.cpu, status))
        case Reading.MEMORY:
            return (Glyph(symbols.memory), usage(system.memory, status))
        case _:
            assert_never(each)


def devices(system: SystemStatus, status: StatusSpec) -> str:
    return status.speakers[system.speakers].description + ". " + status.wifi[system.wifi].description


def describe(ambient: Ambient, spec: IslandSpec) -> str:
    match ambient.power:
        case Battery(powered=True):
            charger = spec.words.charger
        case _:
            charger = ""
    readings = "  ·  ".join(value for value in (ambient.clock, battery_text(ambient, spec.status)) if value)
    return ". ".join(value for value in (readings, charger) if value)


def recording_slot(recorded: Capture, words: Words, *, hovered: bool) -> Slot:
    tone = meaning.Tone.LOW if recorded.attention else meaning.Tone.INK
    stop = (Control(words.stop, words.stop_recording, Action.STOP_RECORDING),) if hovered and recorded.can_stop else ()
    return (Marker.DOT, Text(recorded.title, tone), *stop)


def island(observed: Observed, spec: IslandSpec, *, hovered: Key | None = None, expanded: bool = False) -> tuple[CapsuleView, ...]:
    """The capsules to show, in left-to-right order, with their contents and press actions.

    The right-hand readings expand into the controls menu (`expanded`), where
    ongoing activities become live rows, so they leave the bar.
    """
    words = spec.words
    job, recorded = observed.job, capture(observed.recording, words.phases)
    detached = observed.dictating and not expanded
    lead: tuple[CapsuleView, ...] = ()
    if detached and job is not None:
        lead += (CapsuleView(Key.JOB, zone(Key.JOB, spec), ((Marker.DOTS,),), words.jobs[job], Action.OPEN_MENU),)
    trail: tuple[CapsuleView, ...] = ()
    if detached and recorded is not None:
        tint = meaning.Tint.ATTENTION if recorded.attention else meaning.Tint.NONE
        slot = recording_slot(recorded, words, hovered=hovered is Key.RECORDING)
        trail += (
            CapsuleView(Key.RECORDING, zone(Key.RECORDING, spec), (slot,), f"{recorded.title} · {words.open_controls}", Action.OPEN_MENU, tint),
        )
    # The readings stay the top row while their capsule expands into the menu; a
    # group whose readings are all absent (a keyboard typing normally) takes no space.
    groups = (tuple(part for each in group for part in reading(each, observed, spec.status)) for group in spec.status.groups)
    readings: tuple[Slot, ...] = tuple(group for group in groups if group)
    persistent = (
        CapsuleView(Key.STATUS, Zone.RIGHT, readings, words.close_controls, Action.CLOSE_MENU)
        if expanded
        else CapsuleView(
            Key.STATUS,
            Zone.RIGHT,
            readings,
            ". ".join((resources(observed.system, words), devices(observed.system, spec.status), describe(observed.ambient, spec)))
            + f" · {words.open_controls}",
            Action.OPEN_MENU,
        ),
    )
    active = observed.dictating or job is not None or recorded is not None
    middle = (centre(observed, recorded, words, hovered=hovered),) if active and not expanded else ()
    ranks = order(spec)
    return tuple(sorted((*lead, *middle, *trail, *persistent), key=lambda view: ranks.index(view.key)))


def centre(observed: Observed, recorded: Capture | None, words: Words, *, hovered: Key | None) -> CapsuleView:
    """Only live activity belongs here; persistent readings have fixed right anchors. `recorded` is the recording as captured."""
    revealed = hovered is Key.ISLAND
    job = observed.job
    if observed.dictating:
        stop: Slot = (Control(words.stop, words.stop_dictation, Action.STOP_DICTATION),) if revealed else ()
        slots: tuple[Slot, ...] = ((Glyph(words.microphone, meaning.Tone.MICROPHONE), Marker.WAVE, *stop),)
        return CapsuleView(Key.ISLAND, Zone.ISLAND, slots, words.listening, Action.STOP_DICTATION)
    leading: tuple[Slot, ...] = ((Marker.DOTS,),) if job is not None else ()
    trailing: tuple[Slot, ...] = (recording_slot(recorded, words, hovered=revealed),) if recorded is not None else ()
    described = (words.jobs[job] if job is not None else "", recorded.title if recorded is not None else "")
    label = ". ".join(value for value in described if value)
    return CapsuleView(Key.ISLAND, Zone.ISLAND, (*leading, *trailing), f"{label} · {words.open_controls}", Action.OPEN_MENU)
