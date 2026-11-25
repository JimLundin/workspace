from dataclasses import dataclass, field
from enum import Enum, StrEnum, auto
from typing import Final, assert_never

from contracts.members import every_member
from contracts.recording_state import Phase, RecordingState
from contracts.status import Job
from desktop_ui import ambient
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.components import meaning
from desktop_ui.island_menu import Panel
from winapi.machine_status import (
    Battery,
    Memory,
    PowerUnavailable,
    Speakers,
    Wifi,
)


class Key(Enum):
    JOB = auto()
    ISLAND = auto()
    RECORDING = auto()
    STATUS = auto()
    PANEL = auto()


class Zone(Enum):
    LEAD = auto()
    ISLAND = auto()
    TRAIL = auto()
    RIGHT = auto()
    PANEL = auto()


class Action(Enum):
    OPEN_MENU = auto()
    CLOSE_MENU = auto()
    STOP_DICTATION = auto()
    STOP_RECORDING = auto()


class Marker(Enum):
    WAVE = auto()
    DOT = auto()
    DOTS = auto()


@dataclass(frozen=True, slots=True)
class Text:
    text: str
    tone: meaning.Tone = meaning.Tone.INK
    reserve: str = field(default="", kw_only=True)


@dataclass(frozen=True, slots=True)
class Glyph:
    name: str
    tone: meaning.Tone = meaning.Tone.INK


@dataclass(frozen=True, slots=True)
class Control:
    icon: str
    label: str
    action: Action


@dataclass(frozen=True, slots=True)
class Charge:
    percent: int | None
    """None while the battery hasn't been read: the symbol stays empty."""
    powered: bool = field(kw_only=True)
    tone: meaning.Tone = meaning.Tone.INK


type Part = Text | Glyph | Control | Charge | Marker
type Slot = tuple[Part, ...]


@dataclass(frozen=True, slots=True)
class CapsuleView:
    key: Key
    zone: Zone
    slots: tuple[Slot, ...]
    label: str
    action: Action
    tint: meaning.Tint = meaning.Tint.NONE
    panels: tuple[Panel, ...] = field(default=(), kw_only=True)
    """The panel each slot opens, slot for slot; a capsule without them acts as a whole."""
    tips: tuple[str, ...] = field(default=(), kw_only=True)
    """What each slot reads as under the pointer, slot for slot; a capsule without them has one tip, its label."""


@dataclass(frozen=True, slots=True)
class Observed:
    job: Job | None
    recording: RecordingState
    ambient: Ambient
    system: SystemStatus
    plain_keyboard: bool = field(default=False, kw_only=True)
    """The layout is off (switched off, or the firmware keyboard is connected): the keyboard types plainly."""
    dictating: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Capture:
    title: str
    can_stop: bool = field(kw_only=True)
    attention: bool = field(kw_only=True)


ELAPSED = sentinel("ELAPSED")
"""A phase that reads as the recording's elapsed time."""


@dataclass(frozen=True, slots=True)
class Phased:
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
    clock = (
        f"{hours}:{minutes:02}:{rest:02}"
        if hours
        else f"{minutes:02}:{rest:02}"
    )
    title = clock if phased.title is ELAPSED else phased.title
    return Capture(title, can_stop=phased.can_stop, attention=phased.attention)


class Reading(StrEnum):
    WORKSPACE = auto()
    KEYBOARD = auto()
    SPEAKER = auto()
    WIFI = auto()
    CLOCK = auto()
    BATTERY = auto()
    CPU = auto()
    MEMORY = auto()


class Activity(StrEnum):
    JOB = auto()
    RECORDING = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class Symbols:
    workspace: str
    keyboard: str
    charger: str
    """Power on a machine without a battery."""
    cpu: str
    memory: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Words:
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
    """After a capsule's description: pressing it opens the controls; Workspace's own reading says it alone."""
    close_controls: str
    """The expanded status capsule's name."""
    keyboard: str
    """Said of the keyboard while it types plainly."""
    battery: str
    """Before the battery's charge."""
    charger: str
    """Said of a connected charger, and of a machine without a battery."""
    cpu: str
    memory: str
    of: str
    """Between memory in use and installed."""
    unavailable: str
    """Said of a resource not yet read."""


@dataclass(frozen=True, slots=True)
class StatusSpec:
    readings: tuple[Reading, ...]
    """Left to right, each its own slot, so every two sit the same gap apart."""
    speakers: frozendict[Speakers, ambient.Reading]
    """The speakers' symbol and words in each state."""
    wifi: frozendict[Wifi, ambient.Reading]
    """Wi-Fi's symbol and words in each state."""
    symbols: Symbols
    opens: frozendict[Reading, Panel]
    """The panel each reading expands into when pressed."""
    low_battery: int
    """The battery percentage at or below which, on its own power, the reading warns."""
    unread: str
    """A reading not yet read, rather than a healthy-looking 0%."""
    mains: str
    """The battery reading on a machine without one."""
    gigabytes: str
    """After an amount of memory."""
    widest_percent: str
    widest_memory: str
    widest_clock: str
    clock: str
    """The clock's `strftime` format: the day and date before the time, as a menu bar shows them."""
    """The widest reading of each kind, which its room keeps, so a changing value never shifts the capsule."""


@dataclass(frozen=True, slots=True)
class ActivitiesSpec:
    lead: tuple[Activity, ...]
    """Left of the island, left to right."""
    trail: tuple[Activity, ...]
    """Right of the island, left to right."""


@dataclass(frozen=True, slots=True)
class IslandSpec:
    status: StatusSpec
    activities: ActivitiesSpec
    words: Words


ACTIVITY_KEYS: Final = every_member(
    Activity, {Activity.JOB: Key.JOB, Activity.RECORDING: Key.RECORDING}
)


def order(spec: IslandSpec) -> tuple[Key, ...]:
    lead = tuple(ACTIVITY_KEYS[each] for each in spec.activities.lead)
    trail = tuple(ACTIVITY_KEYS[each] for each in spec.activities.trail)
    return (*lead, Key.ISLAND, *trail, Key.STATUS, Key.PANEL)


def zone(key: Key, spec: IslandSpec) -> Zone:
    match key:
        case Key.ISLAND:
            return Zone.ISLAND
        case Key.STATUS:
            return Zone.RIGHT
        case Key.PANEL:
            return Zone.PANEL
        case Key.JOB | Key.RECORDING:
            return (
                Zone.LEAD
                if any(
                    ACTIVITY_KEYS[each] is key for each in spec.activities.lead
                )
                else Zone.TRAIL
            )
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


GIBIBYTE: Final = 1 << 30
"""What Windows calls a gigabyte."""


def gigabytes(count: int, status: StatusSpec) -> str:
    return f"{count / GIBIBYTE:.1f} {status.gigabytes}"


def power_symbol(
    ambient: Ambient, symbols: Symbols, tone: meaning.Tone
) -> Part:
    match ambient.power:
        case Battery(percent=percent, powered=powered):
            return Charge(percent, powered=powered, tone=tone)
        case PowerUnavailable.NO_BATTERY:
            return Glyph(symbols.charger)
        case PowerUnavailable.UNKNOWN:
            return Charge(None, powered=False)
        case _:
            assert_never(ambient.power)


def battery_tone(ambient: Ambient, status: StatusSpec) -> meaning.Tone:
    match ambient.power:
        case Battery(percent=percent, powered=False) if (
            percent <= status.low_battery
        ):
            return meaning.Tone.LOW
        case _:
            return meaning.Tone.INK


def usage(percent: int | None, status: StatusSpec) -> Text:
    return Text(
        status.unread if percent is None else f"{percent}%",
        reserve=status.widest_percent,
    )


def memory_used(memory: Memory | None, status: StatusSpec) -> Text:
    return Text(
        status.unread if memory is None else gigabytes(memory.used, status),
        reserve=status.widest_memory,
    )


def reading(each: Reading, observed: Observed, status: StatusSpec) -> Slot:
    ambient, system, symbols = observed.ambient, observed.system, status.symbols
    match each:
        case Reading.WORKSPACE:
            return (Glyph(symbols.workspace),)
        case Reading.KEYBOARD:
            return (Glyph(symbols.keyboard),) if observed.plain_keyboard else ()
        case Reading.SPEAKER:
            return (Glyph(status.speakers[system.speakers].icon),)
        case Reading.WIFI:
            return (Glyph(status.wifi[system.wifi].icon),)
        case Reading.CLOCK:
            return (Text(ambient.clock, reserve=status.widest_clock),)
        case Reading.BATTERY:
            tone = battery_tone(ambient, status)
            return (
                Text(
                    battery_text(ambient, status),
                    tone,
                    reserve=status.widest_percent,
                ),
                power_symbol(ambient, symbols, tone),
            )
        case Reading.CPU:
            return (usage(system.cpu, status), Glyph(symbols.cpu))
        case Reading.MEMORY:
            return (memory_used(system.memory, status), Glyph(symbols.memory))
        case _:
            assert_never(each)


def tip(each: Reading, observed: Observed, spec: IslandSpec) -> str:
    ambient, system, words, status = (
        observed.ambient,
        observed.system,
        spec.words,
        spec.status,
    )
    match each:
        case Reading.WORKSPACE:
            return words.open_controls
        case Reading.KEYBOARD:
            return words.keyboard
        case Reading.SPEAKER:
            return status.speakers[system.speakers].description
        case Reading.WIFI:
            return status.wifi[system.wifi].description
        case Reading.CLOCK:
            return ambient.clock
        case Reading.BATTERY:
            match ambient.power:
                case Battery(percent=percent, powered=powered):
                    return f"{words.battery} {percent}%" + (
                        f". {words.charger}" if powered else ""
                    )
                case PowerUnavailable.NO_BATTERY:
                    return words.charger
                case PowerUnavailable.UNKNOWN:
                    return f"{words.battery} {words.unavailable}"
                case _:
                    assert_never(ambient.power)
        case Reading.CPU:
            return f"{words.cpu} {words.unavailable if system.cpu is None else f'{system.cpu}%'}"
        case Reading.MEMORY:
            match system.memory:
                case Memory(used=used, total=total):
                    return f"{words.memory} {gigabytes(used, status)} {words.of} {gigabytes(total, status)}"
                case None:
                    return f"{words.memory} {words.unavailable}"
                case _:
                    assert_never(system.memory)
        case _:
            assert_never(each)


def recording_slot(recorded: Capture, words: Words, *, hovered: bool) -> Slot:
    tone = meaning.Tone.LOW if recorded.attention else meaning.Tone.INK
    stop = (
        (Control(words.stop, words.stop_recording, Action.STOP_RECORDING),)
        if hovered and recorded.can_stop
        else ()
    )
    return (Marker.DOT, Text(recorded.title, tone), *stop)


def island(
    observed: Observed,
    spec: IslandSpec,
    *,
    hovered: Key | None = None,
    expanded: bool = False,
) -> tuple[CapsuleView, ...]:
    words = spec.words
    job, recorded = observed.job, capture(observed.recording, words.phases)
    detached = observed.dictating and not expanded
    lead: tuple[CapsuleView, ...] = ()
    if detached and job is not None:
        lead += (
            CapsuleView(
                Key.JOB,
                zone(Key.JOB, spec),
                ((Marker.DOTS,),),
                words.jobs[job],
                Action.OPEN_MENU,
            ),
        )
    trail: tuple[CapsuleView, ...] = ()
    if detached and recorded is not None:
        tint = (
            meaning.Tint.ATTENTION if recorded.attention else meaning.Tint.NONE
        )
        slot = recording_slot(recorded, words, hovered=hovered is Key.RECORDING)
        trail += (
            CapsuleView(
                Key.RECORDING,
                zone(Key.RECORDING, spec),
                (slot,),
                f"{recorded.title} · {words.open_controls}",
                Action.OPEN_MENU,
                tint,
            ),
        )
    shown = tuple(
        (each, slot)
        for each in spec.status.readings
        if (slot := reading(each, observed, spec.status))
    )
    readings = tuple(slot for _, slot in shown)
    panels = tuple(spec.status.opens[each] for each, _ in shown)
    tips = tuple(tip(each, observed, spec) for each, _ in shown)
    label, action = (
        (words.close_controls, Action.CLOSE_MENU)
        if expanded
        else (". ".join(tips), Action.OPEN_MENU)
    )
    persistent = (
        CapsuleView(
            Key.STATUS,
            Zone.RIGHT,
            readings,
            label,
            action,
            panels=panels,
            tips=tips,
        ),
    )
    panel = (
        (
            CapsuleView(
                Key.PANEL,
                Zone.PANEL,
                (),
                words.close_controls,
                Action.CLOSE_MENU,
            ),
        )
        if expanded
        else ()
    )
    active = observed.dictating or job is not None or recorded is not None
    middle = (
        (centre(observed, recorded, words, hovered=hovered),)
        if active and not expanded
        else ()
    )
    ranks = order(spec)
    return tuple(
        sorted(
            (*lead, *middle, *trail, *persistent, *panel),
            key=lambda view: ranks.index(view.key),
        )
    )


def centre(
    observed: Observed,
    recorded: Capture | None,
    words: Words,
    *,
    hovered: Key | None,
) -> CapsuleView:
    revealed = hovered is Key.ISLAND
    job = observed.job
    if observed.dictating:
        stop: Slot = (
            (Control(words.stop, words.stop_dictation, Action.STOP_DICTATION),)
            if revealed
            else ()
        )
        slots: tuple[Slot, ...] = (
            (
                Glyph(words.microphone, meaning.Tone.MICROPHONE),
                Marker.WAVE,
                *stop,
            ),
        )
        return CapsuleView(
            Key.ISLAND,
            Zone.ISLAND,
            slots,
            words.listening,
            Action.STOP_DICTATION,
        )
    leading: tuple[Slot, ...] = ((Marker.DOTS,),) if job is not None else ()
    trailing: tuple[Slot, ...] = (
        (recording_slot(recorded, words, hovered=revealed),)
        if recorded is not None
        else ()
    )
    described = (
        words.jobs[job] if job is not None else "",
        recorded.title if recorded is not None else "",
    )
    label = ". ".join(value for value in described if value)
    return CapsuleView(
        Key.ISLAND,
        Zone.ISLAND,
        (*leading, *trailing),
        f"{label} · {words.open_controls}",
        Action.OPEN_MENU,
    )
