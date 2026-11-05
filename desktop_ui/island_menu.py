"""The controls menu: a grid of tiles, and keyboard navigation as pure transitions.

The status capsule expands into the menu. Ongoing activities lead as cards with
their Stop; toggles sit beside Workspace's views; then recording, sound, the
desktop tools, the system tray's icons and links. Arrows move to the nearest cell in their direction, and
Up and Down wrap. On the sound slider, Left and Right change the volume. Toggles
and the slider apply in place and keep the menu open; a choice that opens a view
or acts on a window closes it. A letter jumps to the next cell starting with it.
Choosing a window tool or leaving with Escape returns the keyboard to the window
that had it; opening a Workspace view keeps it there, and a tray icon hands it to
its application.
"""

from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Final, assert_never

from assistant.meeting_detection import AutomaticStatus
from desktop_ui.keymap import shortcut, shortcut_hint
from protocol import Tool


class Command(Enum):
    CANVAS = auto()
    RECORD = auto()
    STOP_RECORDING = auto()
    AUTOMATIC_RECORDING = auto()
    STOP_AGENT = auto()
    KEYMAP = auto()
    OVERLAY = auto()
    TASKBAR = auto()
    PLACEMENT = auto()
    DARK_WHEN_AWAY = auto()
    NOTIFICATIONS = auto()
    ALL_CONTROLS = auto()


@dataclass(frozen=True, slots=True)
class ToolChoice:
    """A Tool selected from the menu; window tools retain the window that had the keyboard."""

    tool: Tool


@dataclass(frozen=True, slots=True)
class Volume:
    """A requested speaker level, from 0 to 1."""

    level: float


@dataclass(frozen=True, slots=True)
class TrayChoice:
    """A tray icon's primary click, by its place in the bar's current tray snapshot."""

    slot: int


type Choice = Command | ToolChoice | Volume | TrayChoice


@dataclass(frozen=True, slots=True)
class Item:
    label: str
    icon: str
    choice: Choice
    key: str = ""  # A shortcut hint, shown quietly at the trailing edge.


def tool_item(label: str, icon: str, tool: Tool) -> Item:
    """Tool cells advertise the physical keys from the layout that triggers them."""
    return Item(label, icon, ToolChoice(tool), shortcut_hint(shortcut(tool), compact=True))


@dataclass(frozen=True, slots=True)
class Live:
    """An ongoing activity: its reading (empty while it has none) and its Stop."""

    label: str
    detail: str
    stop: Command


@dataclass(frozen=True, slots=True)
class Toggle:
    """A setting that flips in place; `detail` says its state in words."""

    label: str
    detail: str
    icon: str
    choice: Command
    on: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Slider:
    """The speaker level; None while Windows hasn't reported one."""

    label: str
    level: float | None
    muted: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class TrayIcon:
    """A system tray application, by its place in the bar's tray snapshot; the bar owns its image."""

    label: str
    slot: int


type Entry = Item | Live | Toggle | Slider | TrayIcon


class Face(Enum):
    """How a cell presents its entry."""

    CARD = auto()  # An ongoing activity across the grid, with its Stop.
    TOGGLE = auto()  # A round switch with the setting and its state.
    TILE = auto()  # A large square with its symbol above its label.
    WIDE = auto()  # A full-width tile with its symbol beside its label.
    SLIDER = auto()
    TOOL = auto()  # A small square with its symbol above a caption.
    LINK = auto()  # A quiet line of text.
    ICON = auto()  # A tray application's own image, icon-sized.


# Eight narrow columns: tray icons take one each, the other tiles span pairs.
COLUMNS: Final = 8


@dataclass(frozen=True, slots=True)
class Cell:
    """An entry's place in the grid: columns from the left, tracks from the top."""

    entry: Entry
    face: Face
    column: int
    span: int
    track: int
    tracks: int
    caption: str = ""  # A tile's short name; its entry's label stays its accessible name.


def automatic_toggle(status: AutomaticStatus) -> Toggle:
    match status:
        case AutomaticStatus.OFF:
            return Toggle("Auto-record", "Teams · Off", "mic", Command.AUTOMATIC_RECORDING, on=False)
        case AutomaticStatus.CHECKING:
            return Toggle("Auto-record", "Teams · Connecting…", "mic", Command.AUTOMATIC_RECORDING, on=True)
        case AutomaticStatus.READY:
            return Toggle("Auto-record", "Teams · On", "mic", Command.AUTOMATIC_RECORDING, on=True)
        case AutomaticStatus.UNAVAILABLE:
            return Toggle("Auto-record", "Teams · Check connection", "mic", Command.AUTOMATIC_RECORDING, on=True)
        case _:
            assert_never(status)


@dataclass(frozen=True, slots=True)
class Controls:
    """What the menu reads: running activities' readings, each toggle's state and the speaker's."""

    recording: str | None
    agent: str | None
    automatic: AutomaticStatus = AutomaticStatus.OFF
    overlay: bool = field(default=False, kw_only=True)
    taskbar: bool = field(default=False, kw_only=True)
    placement_paused: bool = field(default=False, kw_only=True)
    dark_when_away: int | None = field(default=None, kw_only=True)
    """Dark when away's idle delay in minutes while it's on; None while it's off."""
    sound: Slider = Slider("Sound", None, muted=False)
    tray: tuple[str, ...] = ()  # Each tray icon's label, in the bar's snapshot order.


def entries(controls: Controls) -> tuple[Cell, ...]:
    """The grid for what's happening now; each cell's tracks include its share of the gutters."""
    live: tuple[Live, ...] = (
        *((Live("Agent working", controls.agent, Command.STOP_AGENT),) if controls.agent is not None else ()),
        *((Live("Recording", controls.recording, Command.STOP_RECORDING),) if controls.recording is not None else ()),
    )
    cards = tuple(Cell(activity, Face.CARD, 0, COLUMNS, 5 * index, 5) for index, activity in enumerate(live))
    top = 5 * len(cards)
    toggles = (
        automatic_toggle(controls.automatic),
        Toggle("Keyboard overlay", "On" if controls.overlay else "Off", "layers", Command.OVERLAY, on=controls.overlay),
        Toggle("Windows taskbar", "Shown" if controls.taskbar else "Hidden", "table", Command.TASKBAR, on=controls.taskbar),
        Toggle("Window placement", "Paused" if controls.placement_paused else "On", "grid", Command.PLACEMENT, on=not controls.placement_paused),
        Toggle(
            "Dark when away",
            "Off" if controls.dark_when_away is None else f"External · {controls.dark_when_away} min idle",
            "lock",
            Command.DARK_WHEN_AWAY,
            on=controls.dark_when_away is not None,
        ),
    )
    modules = (
        Cell(toggles[0], Face.TOGGLE, 0, 4, top, 4),
        Cell(Item("Your work canvas", "canvas", Command.CANVAS), Face.TILE, 4, 4, top, 4, "Canvas"),
        Cell(toggles[1], Face.TOGGLE, 0, 4, top + 4, 4),
        Cell(toggles[2], Face.TOGGLE, 4, 4, top + 4, 4),
        Cell(toggles[3], Face.TOGGLE, 0, 4, top + 8, 4),
        Cell(toggles[4], Face.TOGGLE, 4, 4, top + 8, 4),
    )
    top += 12
    record = () if controls.recording is not None else (Cell(Item("Record a meeting", "mic", Command.RECORD), Face.WIDE, 0, COLUMNS, top, 5),)
    top += 5 * len(record)
    sound = Cell(controls.sound, Face.SLIDER, 0, COLUMNS, top, 6)
    top += 6
    captioned: tuple[tuple[Entry, str], ...] = (
        (tool_item("Switch windows", "search", Tool.WINDOW_SWITCHER), "Switch"),
        (tool_item("Copy latest transcript", "doc", Tool.COPY_TRANSCRIPT), "Transcript"),
        (Item("Keyboard map", "keyboard", Command.KEYMAP), "Key map"),
    )
    tools = tuple(Cell(entry, Face.TOOL, 2 * column, 2, top, 7, caption) for column, (entry, caption) in enumerate(captioned))
    top += 7
    tray = tuple(Cell(TrayIcon(name, slot), Face.ICON, slot % COLUMNS, 1, top + 4 * (slot // COLUMNS), 4) for slot, name in enumerate(controls.tray))
    top += 4 * ((len(tray) + COLUMNS - 1) // COLUMNS)
    links = (
        Cell(Item("Windows notification settings", "bell", Command.NOTIFICATIONS), Face.LINK, 0, COLUMNS, top, 3),
        Cell(Item("All Workspace controls…", "more", Command.ALL_CONTROLS), Face.LINK, 0, COLUMNS, top + 3, 3),
    )
    return (*cards, *modules, *record, sound, *tools, *tray, *links)


@dataclass(frozen=True, slots=True)
class Menu:
    """The open menu: its grid and the cell under the keyboard or pointer."""

    cells: tuple[Cell, ...]
    selected: int | None = None


def label(entry: Entry) -> str:
    match entry:
        case Item(label=text) | Live(label=text) | Toggle(label=text) | Slider(label=text) | TrayIcon(label=text):
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
    """A choice that closes the menu."""

    choice: Choice


@dataclass(frozen=True, slots=True)
class Applied:
    """A choice applied in place: the menu stays open to show its new state."""

    choice: Choice


class Dismissed(Enum):
    ESCAPE = auto()


type Outcome = Menu | Chosen | Applied | Dismissed

VOLUME_STEP: Final = 0.05


def current(menu: Menu) -> Cell | None:
    cells = menu.cells
    return cells[menu.selected] if menu.selected is not None and menu.selected < len(cells) else None


def towards(cells: tuple[Cell, ...], index: int, key: Key) -> int | None:
    """The nearest cell in an arrow's direction that shares the selected cell's row or column."""
    here = cells[index]

    def gap(cell: Cell) -> int | None:
        across = cell.column < here.column + here.span and here.column < cell.column + cell.span
        along = cell.track < here.track + here.tracks and here.track < cell.track + cell.tracks
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
        # Centres in half units, so odd spans compare exactly.
        if key in (Key.UP, Key.DOWN):
            return abs(2 * cell.column + cell.span - 2 * here.column - here.span)
        return abs(2 * cell.track + cell.tracks - 2 * here.track - here.tracks)

    ranked = sorted((distance, offset(cell), position) for position, cell in enumerate(cells) if (distance := gap(cell)) is not None)
    return ranked[0][2] if ranked else None


def move(menu: Menu, key: Key) -> Menu:
    cells = menu.cells
    if not cells:
        return menu
    if menu.selected is None or menu.selected >= len(cells):
        return replace(menu, selected=0 if key in (Key.DOWN, Key.RIGHT) else len(cells) - 1)
    target = towards(cells, menu.selected, key)
    if target is None and key in (Key.DOWN, Key.UP):
        target = 0 if key is Key.DOWN else len(cells) - 1  # Up and Down wrap; Left and Right stop at the edge.
    return menu if target is None else replace(menu, selected=target)


def sideways(menu: Menu, entry: Entry | None, key: Key) -> Outcome:
    """Left and Right change the volume on the slider and otherwise move."""
    match entry:
        case Slider(level=float() as level):
            step = VOLUME_STEP if key is Key.RIGHT else -VOLUME_STEP
            return Applied(Volume(min(1.0, max(0.0, round(level + step, 2)))))
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
            return Dismissed.ESCAPE
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
        case Slider() | None:
            return menu
        case _:
            assert_never(entry)


def jump(menu: Menu, character: str) -> Menu:
    cells = menu.cells
    start = menu.selected if menu.selected is not None else -1
    order = tuple((start + offset) % len(cells) for offset in range(1, len(cells) + 1))
    target = next((index for index in order if label(cells[index].entry).casefold().startswith(character.casefold())), None)
    return menu if target is None else replace(menu, selected=target)


def restores_focus(choice: Choice) -> bool:
    """Window tools and quiet toggles hand the keyboard back; Workspace's own views keep it."""
    match choice:
        case ToolChoice() | Volume():
            return True
        case (
            Command.OVERLAY
            | Command.TASKBAR
            | Command.PLACEMENT
            | Command.DARK_WHEN_AWAY
            | Command.RECORD
            | Command.STOP_RECORDING
            | Command.STOP_AGENT
            | Command.AUTOMATIC_RECORDING
        ):
            return True
        case Command.CANVAS | Command.KEYMAP | Command.NOTIFICATIONS | Command.ALL_CONTROLS | TrayChoice():
            return False
        case _:
            assert_never(choice)
