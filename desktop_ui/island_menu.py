from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum, StrEnum, auto
from itertools import accumulate, chain
from typing import Final, assert_never

from desktop_ui.ambient import History
from desktop_ui.month import Month
from protocol import Tool
from winapi.machine_status import (
    LOCATION_OFF,
    Battery,
    Listing,
    Network,
    Power,
    PowerUnavailable,
)


class Command(Enum):
    RECORD = auto()
    STOP_RECORDING = auto()
    KEYMAP = auto()
    LAYOUT = auto()
    OVERLAY = auto()
    PLACEMENT = auto()
    DARK_WHEN_AWAY = auto()
    MUTE = auto()
    THIS_MONTH = auto()
    NOTIFICATIONS = auto()
    WIFI_SETTINGS = auto()
    LOCATION_SETTINGS = auto()
    POWER_SETTINGS = auto()
    ALL_CONTROLS = auto()


@dataclass(frozen=True, slots=True)
class ToolChoice:
    tool: Tool


@dataclass(frozen=True, slots=True)
class Volume:
    level: float


@dataclass(frozen=True, slots=True)
class TrayChoice:
    slot: int


@dataclass(frozen=True, slots=True)
class Page:
    months: int


@dataclass(frozen=True, slots=True)
class Join:
    profile: str


type Choice = Command | ToolChoice | Volume | TrayChoice | Page | Join


@dataclass(frozen=True, slots=True)
class Item:
    label: str
    icon: str
    choice: Choice
    key: str = ""


def tool_item(
    label: str, icon: str, tool: Tool, hints: frozendict[Tool, str]
) -> Item:
    return Item(label, icon, ToolChoice(tool), hints.get(tool, ""))


@dataclass(frozen=True, slots=True)
class Live:
    label: str
    detail: str
    stop: Command


@dataclass(frozen=True, slots=True)
class Toggle:
    label: str
    detail: str
    icon: str
    choice: Command
    on: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Slider:
    label: str
    level: float | None
    muted: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class TrayIcon:
    label: str
    slot: int


@dataclass(frozen=True, slots=True)
class Calendar:
    label: str
    month: Month
    today: date


@dataclass(frozen=True, slots=True)
class Trace:
    shares: tuple[float | None, ...]
    capacity: int
    """How many samples the graph spans; a younger history fills it from the right."""
    reading: str


NO_TRACE: Final = Trace((), 1, "")


def traced(history: History, ceiling: int | None, reading: str) -> Trace:
    shares = tuple(
        None
        if sample is None or ceiling is None or ceiling <= 0
        else min(1.0, max(0.0, sample / ceiling))
        for sample in history.samples
    )
    return Trace(shares, history.capacity, reading)


@dataclass(frozen=True, slots=True)
class Graph:
    label: str
    trace: Trace


@dataclass(frozen=True, slots=True)
class Nearby:
    label: str
    network: Network
    detail: str


@dataclass(frozen=True, slots=True)
class Fact:
    label: str
    icon: str
    value: str
    detail: str


type Entry = (
    Item | Live | Toggle | Slider | TrayIcon | Calendar | Graph | Nearby | Fact
)


class Face(StrEnum):
    CARD = auto()
    TOGGLE = auto()
    WIDE = auto()
    SLIDER = auto()
    TOOL = auto()
    LINK = auto()
    ICON = auto()
    CALENDAR = auto()
    GRAPH = auto()
    NETWORK = auto()
    FACT = auto()


COLUMNS: Final = 8


@dataclass(frozen=True, slots=True)
class Cell:
    entry: Entry
    face: Face
    column: int
    span: int
    track: int
    tracks: int
    caption: str = ""


@dataclass(frozen=True, slots=True)
class Controls:
    recording: str | None
    layout: bool = field(default=True, kw_only=True)
    """The keyboard layout is on, rather than typing plainly."""
    overlay: bool = field(default=False, kw_only=True)
    placement_paused: bool = field(default=False, kw_only=True)
    dark_when_away: bool = field(default=False, kw_only=True)
    sound: Slider = Slider("", None, muted=False)
    tray: tuple[str, ...] = ()
    today: date | None = field(default=None, kw_only=True)
    networks: Listing = field(default=(), kw_only=True)
    power: Power = field(default=PowerUnavailable.UNKNOWN, kw_only=True)
    cpu: Trace = field(default=NO_TRACE, kw_only=True)
    memory: Trace = field(default=NO_TRACE, kw_only=True)
    month: Month | None = field(default=None, kw_only=True)
    """The month the calendar shows."""
    hints: frozendict[Tool, str] = field(default=frozendict(), kw_only=True)
    """Each tool's keys on the layout, at a tool cell's trailing edge."""


class Panel(StrEnum):
    WORKSPACE = auto()
    KEYBOARD = auto()
    SOUND = auto()
    NETWORK = auto()
    CALENDAR = auto()
    PROCESSOR = auto()
    MEMORY = auto()
    POWER = auto()


class EntryId(StrEnum):
    LAYOUT = auto()
    OVERLAY = auto()
    PLACEMENT = auto()
    DARK_WHEN_AWAY = auto()
    RECORD = auto()
    SOUND = auto()
    MUTE = auto()
    CALENDAR = auto()
    CPU_GRAPH = auto()
    MEMORY_GRAPH = auto()
    LOCATION = auto()
    WIFI_SETTINGS = auto()
    BATTERY = auto()
    POWER_SETTINGS = auto()
    SWITCH_WINDOWS = auto()
    COPY_TRANSCRIPT = auto()
    KEYMAP = auto()
    NOTIFICATIONS = auto()
    ALL_CONTROLS = auto()


@dataclass(frozen=True, slots=True)
class CellSpec:
    entry: EntryId
    face: Face
    span: int
    label: str = ""
    """The accessible name; the sound slider takes Windows' own."""
    icon: str = ""
    caption: str = ""
    """A tile's short name under its symbol."""


@dataclass(frozen=True, slots=True)
class CellsRow:
    tracks: int
    cells: tuple[CellSpec, ...]


@dataclass(frozen=True, slots=True)
class ActivitiesRow:
    tracks: int


@dataclass(frozen=True, slots=True)
class NetworksRow:
    tracks: int
    most: int


@dataclass(frozen=True, slots=True)
class TrayRow:
    tracks: int


type RowSpec = CellsRow | ActivitiesRow | TrayRow | NetworksRow


@dataclass(frozen=True, slots=True, kw_only=True)
class MenuWords:
    on: str
    off: str
    paused: str
    recording: str
    """A recording's card."""
    sound: str
    """The sound slider's name."""
    unread: str
    """The speaker level before Windows reports one."""
    muted: str
    month: str
    """The calendar's heading, a `strftime` format."""
    weekday: str
    """The calendar's column headings, a `strftime` format."""
    connected: str
    saved: str
    """A network Windows has a profile for."""
    secured: str
    open: str
    charging: str
    plugged_in: str
    """On mains power with the battery not charging, as when it is full."""
    on_battery: str
    """On its own power, before Windows estimates what is left."""
    hours_left: str
    """What is left, a format with `hours` and `minutes`..."""
    minutes_left: str
    """...and, under an hour, with `minutes` alone."""
    mains: str
    """A machine without a battery."""


@dataclass(frozen=True, slots=True)
class PanelSpec:
    least: float
    rows: tuple[RowSpec, ...]


@dataclass(frozen=True, slots=True)
class ControlsSpec:
    panels: frozendict[Panel, PanelSpec]
    words: MenuWords
    first_weekday: int = field(kw_only=True)
    """The calendar's first column: 0 is Monday, 6 Sunday."""


def toggle(spec: CellSpec, detail: str, choice: Command, *, on: bool) -> Toggle:
    return Toggle(spec.label, detail, spec.icon, choice, on=on)


def entry(
    spec: CellSpec, controls: Controls, menu: ControlsSpec
) -> Entry | None:
    words = menu.words
    match spec.entry:
        case EntryId.LAYOUT:
            return toggle(
                spec,
                words.on if controls.layout else words.off,
                Command.LAYOUT,
                on=controls.layout,
            )
        case EntryId.OVERLAY:
            return toggle(
                spec,
                words.on if controls.overlay else words.off,
                Command.OVERLAY,
                on=controls.overlay,
            )
        case EntryId.PLACEMENT:
            paused = controls.placement_paused
            return toggle(
                spec,
                words.paused if paused else words.on,
                Command.PLACEMENT,
                on=not paused,
            )
        case EntryId.DARK_WHEN_AWAY:
            away = controls.dark_when_away
            return toggle(
                spec,
                words.on if away else words.off,
                Command.DARK_WHEN_AWAY,
                on=away,
            )
        case EntryId.RECORD:
            return (
                None
                if controls.recording is not None
                else Item(spec.label, spec.icon, Command.RECORD)
            )
        case EntryId.SOUND:
            return controls.sound
        case EntryId.MUTE:
            muted = controls.sound.muted
            return toggle(
                spec, words.on if muted else words.off, Command.MUTE, on=muted
            )
        case EntryId.CPU_GRAPH:
            return Graph(spec.label, controls.cpu)
        case EntryId.MEMORY_GRAPH:
            return Graph(spec.label, controls.memory)
        case EntryId.CALENDAR:
            return (
                Calendar(spec.label, controls.month or Month.of(today), today)
                if (today := controls.today)
                else None
            )
        case EntryId.SWITCH_WINDOWS:
            return tool_item(
                spec.label, spec.icon, Tool.WINDOW_SWITCHER, controls.hints
            )
        case EntryId.COPY_TRANSCRIPT:
            return tool_item(
                spec.label, spec.icon, Tool.COPY_TRANSCRIPT, controls.hints
            )
        case EntryId.KEYMAP:
            return Item(spec.label, spec.icon, Command.KEYMAP)
        case EntryId.NOTIFICATIONS:
            return Item(spec.label, spec.icon, Command.NOTIFICATIONS)
        case EntryId.WIFI_SETTINGS:
            return Item(spec.label, spec.icon, Command.WIFI_SETTINGS)
        case EntryId.POWER_SETTINGS:
            return Item(spec.label, spec.icon, Command.POWER_SETTINGS)
        case EntryId.BATTERY:
            return battery(spec, controls.power, words)
        case EntryId.LOCATION:
            return (
                Item(spec.label, spec.icon, Command.LOCATION_SETTINGS)
                if controls.networks is LOCATION_OFF
                else None
            )
        case EntryId.ALL_CONTROLS:
            return Item(spec.label, spec.icon, Command.ALL_CONTROLS)
        case _:
            assert_never(spec.entry)


def activities(controls: Controls, words: MenuWords) -> tuple[Live, ...]:
    return (
        (Live(words.recording, controls.recording, Command.STOP_RECORDING),)
        if controls.recording is not None
        else ()
    )


def left(seconds: int, words: MenuWords) -> str:
    hours, minutes = seconds // 3600, seconds // 60 % 60
    return (
        words.hours_left.format(hours=hours, minutes=minutes)
        if hours
        else words.minutes_left.format(minutes=minutes)
    )


def battery(spec: CellSpec, power: Power, words: MenuWords) -> Fact | None:
    match power:
        case Battery(charging=True, percent=percent):
            return Fact(spec.label, spec.icon, f"{percent}%", words.charging)
        case Battery(powered=True, percent=percent):
            return Fact(spec.label, spec.icon, f"{percent}%", words.plugged_in)
        case Battery(remaining=int() as seconds, percent=percent):
            return Fact(
                spec.label, spec.icon, f"{percent}%", left(seconds, words)
            )
        case Battery(percent=percent):
            return Fact(spec.label, spec.icon, f"{percent}%", words.on_battery)
        case PowerUnavailable.NO_BATTERY:
            return Fact(spec.label, spec.icon, words.mains, "")
        case PowerUnavailable.UNKNOWN:
            return None
        case _:
            assert_never(power)


def heard(
    controls: Controls, row: NetworksRow, words: MenuWords
) -> tuple[Nearby, ...]:
    if controls.networks is LOCATION_OFF:
        return ()

    def detail(network: Network) -> str:
        if network.connected:
            return words.connected
        if network.profile is not None:
            return words.saved
        return words.secured if network.secured else words.open

    return tuple(
        Nearby(network.ssid, network, detail(network))
        for network in controls.networks[: row.most]
    )


def present_cells(
    controls: Controls, specs: tuple[CellSpec, ...], menu: ControlsSpec
) -> tuple[tuple[CellSpec, Entry], ...]:
    return tuple(
        (each, present)
        for each in specs
        if (present := entry(each, controls, menu))
    )


def height(row: RowSpec, controls: Controls, spec: ControlsSpec) -> int:
    match row:
        case ActivitiesRow(tracks=tracks):
            return tracks * len(activities(controls, spec.words))
        case TrayRow(tracks=tracks):
            return tracks * ((len(controls.tray) + COLUMNS - 1) // COLUMNS)
        case NetworksRow(tracks=tracks):
            return tracks * len(heard(controls, row, spec.words))
        case CellsRow(tracks=tracks, cells=specs):
            return tracks if present_cells(controls, specs, spec) else 0
        case _:
            assert_never(row)


def row_cells(
    row: RowSpec, controls: Controls, top: int, spec: ControlsSpec
) -> tuple[Cell, ...]:
    match row:
        case ActivitiesRow(tracks=tracks):
            cards = enumerate(activities(controls, spec.words))
            return tuple(
                Cell(
                    activity,
                    Face.CARD,
                    0,
                    COLUMNS,
                    top + tracks * index,
                    tracks,
                )
                for index, activity in cards
            )
        case TrayRow(tracks=tracks):
            return tuple(
                Cell(
                    TrayIcon(name, slot),
                    Face.ICON,
                    slot % COLUMNS,
                    1,
                    top + tracks * (slot // COLUMNS),
                    tracks,
                )
                for slot, name in enumerate(controls.tray)
            )
        case NetworksRow(tracks=tracks):
            lines = enumerate(heard(controls, row, spec.words))
            return tuple(
                Cell(
                    network,
                    Face.NETWORK,
                    0,
                    COLUMNS,
                    top + tracks * index,
                    tracks,
                )
                for index, network in lines
            )
        case CellsRow(tracks=tracks, cells=specs):
            shown = present_cells(controls, specs, spec)
            columns = accumulate((each.span for each, _ in shown), initial=0)
            return tuple(
                Cell(
                    present,
                    each.face,
                    column,
                    each.span,
                    top,
                    tracks,
                    each.caption,
                )
                for (each, present), column in zip(shown, columns, strict=False)
            )
        case _:
            assert_never(row)


def entries(
    controls: Controls, spec: ControlsSpec, panel: Panel
) -> tuple[Cell, ...]:
    rows = spec.panels[panel].rows
    tops = accumulate((height(row, controls, spec) for row in rows), initial=0)
    return tuple(
        chain.from_iterable(
            row_cells(row, controls, top, spec)
            for row, top in zip(rows, tops, strict=False)
        )
    )


@dataclass(frozen=True, slots=True)
class Menu:
    panel: Panel
    cells: tuple[Cell, ...]
    selected: int | None = None
    month: Month | None = None
    """The month the calendar was turned to; None shows today's."""
    anchor: int | None = None
    """The status capsule's slot the panel hangs under: the reading pressed; None, the first that opens it."""


def label(entry: Entry) -> str:
    match entry:
        case (
            Item(label=text)
            | Live(label=text)
            | Toggle(label=text)
            | Slider(label=text)
            | TrayIcon(label=text)
            | Calendar(label=text)
            | Graph(label=text)
            | Nearby(label=text)
            | Fact(label=text)
        ):
            return text
        case _:
            assert_never(entry)


class Key(Enum):
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    ENTER = auto()
    ESCAPE = auto()


@dataclass(frozen=True, slots=True)
class Letter:
    character: str


type Press = Key | Letter


@dataclass(frozen=True, slots=True)
class Chosen:
    choice: Choice


@dataclass(frozen=True, slots=True)
class Applied:
    choice: Choice


DISMISSED = sentinel("DISMISSED")
"""Escape closed the menu."""


type Outcome = Menu | Chosen | Applied | DISMISSED


def current(menu: Menu) -> Cell | None:
    cells = menu.cells
    return (
        cells[menu.selected]
        if menu.selected is not None and menu.selected < len(cells)
        else None
    )


def towards(cells: tuple[Cell, ...], index: int, key: Key) -> int | None:
    here = cells[index]

    def gap(cell: Cell) -> int | None:
        across = (
            cell.column < here.column + here.span
            and here.column < cell.column + cell.span
        )
        along = (
            cell.track < here.track + here.tracks
            and here.track < cell.track + cell.tracks
        )
        match key:
            case Key.DOWN if across and cell.track >= here.track + here.tracks:
                return cell.track - here.track - here.tracks
            case Key.UP if across and cell.track + cell.tracks <= here.track:
                return here.track - cell.track - cell.tracks
            case Key.RIGHT if along and cell.column >= here.column + here.span:
                return cell.column - here.column - here.span
            case Key.LEFT if along and cell.column + cell.span <= here.column:
                return here.column - cell.column - cell.span
            case _:
                return None

    def offset(cell: Cell) -> int:
        if key in (Key.UP, Key.DOWN):
            return abs(
                2 * cell.column + cell.span - 2 * here.column - here.span
            )
        return abs(2 * cell.track + cell.tracks - 2 * here.track - here.tracks)

    ranked = sorted(
        (distance, offset(cell), position)
        for position, cell in enumerate(cells)
        if (distance := gap(cell)) is not None
    )
    return ranked[0][2] if ranked else None


def move(menu: Menu, key: Key) -> Menu:
    cells = menu.cells
    if not cells:
        return menu
    if menu.selected is None or menu.selected >= len(cells):
        return replace(
            menu, selected=0 if key in (Key.DOWN, Key.RIGHT) else len(cells) - 1
        )
    target = towards(cells, menu.selected, key)
    if target is None and key in (Key.DOWN, Key.UP):
        target = 0 if key is Key.DOWN else len(cells) - 1
    return menu if target is None else replace(menu, selected=target)


VOLUME_STEP: Final = 0.05


def sideways(menu: Menu, entry: Entry | None, key: Key) -> Outcome:
    match entry:
        case Calendar():
            return Applied(Page(1 if key is Key.RIGHT else -1))
        case Slider(level=float() as level):
            change = VOLUME_STEP if key is Key.RIGHT else -VOLUME_STEP
            return Applied(Volume(min(1.0, max(0.0, round(level + change, 2)))))
        case Slider(level=None):
            return menu
        case _:
            return move(menu, key)


def press(menu: Menu, key: Press) -> Outcome:
    cell = current(menu)
    entry = cell.entry if cell is not None else None
    match key:
        case Key.LEFT | Key.RIGHT:
            return sideways(menu, entry, key)
        case Key.UP | Key.DOWN:
            return move(menu, key)
        case Key.ESCAPE:
            return DISMISSED
        case Key.ENTER:
            return choose(menu, entry)
        case Letter(character=character):
            return jump(menu, character)
        case _:
            assert_never(key)


def choose(menu: Menu, entry: Entry | None) -> Outcome:
    match entry:
        case Item(choice=choice):
            return Chosen(choice)
        case Live(stop=stop):
            return Chosen(stop)
        case Toggle(choice=choice):
            return Applied(choice)
        case TrayIcon(slot=slot):
            return Chosen(TrayChoice(slot))
        case Calendar():
            return Applied(Command.THIS_MONTH)
        case Nearby(network=Network(connected=True)):
            return menu
        case Nearby(network=Network(profile=str() as profile)):
            return Applied(Join(profile))
        case Nearby():
            return Chosen(Command.WIFI_SETTINGS)
        case Slider() | Graph() | Fact() | None:
            return menu
        case _:
            assert_never(entry)


def jump(menu: Menu, character: str) -> Menu:
    cells = menu.cells
    start = menu.selected if menu.selected is not None else -1
    order = tuple(
        (start + offset) % len(cells) for offset in range(1, len(cells) + 1)
    )
    target = next(
        (
            index
            for index in order
            if label(cells[index].entry)
            .casefold()
            .startswith(character.casefold())
        ),
        None,
    )
    return menu if target is None else replace(menu, selected=target)


def restores_focus(choice: Choice) -> bool:
    match choice:
        case ToolChoice() | Volume() | Page() | Join():
            return True
        case (
            Command.LAYOUT
            | Command.OVERLAY
            | Command.PLACEMENT
            | Command.DARK_WHEN_AWAY
            | Command.MUTE
            | Command.THIS_MONTH
            | Command.RECORD
            | Command.STOP_RECORDING
        ):
            return True
        case (
            Command.KEYMAP
            | Command.NOTIFICATIONS
            | Command.WIFI_SETTINGS
            | Command.LOCATION_SETTINGS
            | Command.POWER_SETTINGS
            | Command.ALL_CONTROLS
            | TrayChoice()
        ):
            return False
        case _:
            assert_never(choice)
