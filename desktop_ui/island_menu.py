"""The status capsule's panels: grids of tiles, and keyboard navigation as pure transitions.

The status capsule expands into the panel of the reading pressed: the speaker's
sound, or Workspace's own controls. In those, ongoing activities lead as cards
with their Stop; toggles sit beside Workspace's views; then recording, sound, the
desktop tools, the system tray's icons and links. Arrows move to the nearest cell in their direction, and
Up and Down wrap. On the sound slider, Left and Right change the volume. Toggles
and the slider apply in place and keep the menu open; a choice that opens a view
or acts on a window closes it. A letter jumps to the next cell starting with it.
Choosing a window tool or leaving with Escape returns the keyboard to the window
that had it; opening a Workspace view keeps it there, and a tray icon hands it to
its application.
"""

from dataclasses import dataclass, field, replace
from enum import Enum, StrEnum, auto
from itertools import accumulate, chain
from typing import Final, assert_never

from protocol import Tool


class Command(Enum):
    RECORD = auto()
    STOP_RECORDING = auto()
    KEYMAP = auto()
    OVERLAY = auto()
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


def tool_item(label: str, icon: str, tool: Tool, hints: frozendict[Tool, str]) -> Item:
    """Tool cells advertise the physical keys from the layout that triggers them."""
    return Item(label, icon, ToolChoice(tool), hints.get(tool, ""))


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


class Face(StrEnum):
    """How a cell presents its entry."""

    CARD = auto()  # An ongoing activity across the grid, with its Stop.
    TOGGLE = auto()  # A round switch with the setting and its state.
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


@dataclass(frozen=True, slots=True)
class Controls:
    """What the menu reads: running activities' readings, each toggle's state and the speaker's."""

    recording: str | None
    overlay: bool = field(default=False, kw_only=True)
    placement_paused: bool = field(default=False, kw_only=True)
    dark_when_away: bool = field(default=False, kw_only=True)
    sound: Slider = Slider("", None, muted=False)
    tray: tuple[str, ...] = ()  # Each tray icon's label, in the bar's snapshot order.
    hints: frozendict[Tool, str] = field(default=frozendict(), kw_only=True)
    """Each tool's keys on the layout, at a tool cell's trailing edge."""


# ---- the panels' shape: `desktop.bar.CONTROLS` declares them --------------------------------


class Panel(StrEnum):
    """A grid the status capsule expands into; each reading opens one."""

    WORKSPACE = auto()  # Workspace's own controls, its activities and the tray.
    SOUND = auto()


class EntryId(StrEnum):
    """The entries a spec can place. What each does, and any wording that follows
    state, stays here; the spec gives its place, look, label and symbol."""

    OVERLAY = auto()
    PLACEMENT = auto()
    DARK_WHEN_AWAY = auto()
    RECORD = auto()
    SOUND = auto()
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
    """Cells left to right; one whose entry is absent now (Record while recording)
    gives its place to the next, and a row with none takes no space."""

    tracks: int
    cells: tuple[CellSpec, ...]


@dataclass(frozen=True, slots=True)
class ActivitiesRow:
    """A full-width card for each running activity, `tracks` tall each."""

    tracks: int


@dataclass(frozen=True, slots=True)
class TrayRow:
    """The system tray's icons, a column each, wrapping onto lines `tracks` tall."""

    tracks: int


type RowSpec = CellsRow | ActivitiesRow | TrayRow


@dataclass(frozen=True, slots=True, kw_only=True)
class MenuWords:
    """What the menu's entries say beyond their labels."""

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


@dataclass(frozen=True, slots=True)
class ControlsSpec:
    """Each panel's rows, top to bottom, and the panels' wording."""

    panels: frozendict[Panel, tuple[RowSpec, ...]]
    words: MenuWords


def toggle(spec: CellSpec, detail: str, choice: Command, *, on: bool) -> Toggle:
    return Toggle(spec.label, detail, spec.icon, choice, on=on)


def entry(spec: CellSpec, controls: Controls, menu: ControlsSpec) -> Entry | None:
    """The entry `spec` places, as it reads now; None while it doesn't apply."""
    words = menu.words
    match spec.entry:
        case EntryId.OVERLAY:
            return toggle(spec, words.on if controls.overlay else words.off, Command.OVERLAY, on=controls.overlay)
        case EntryId.PLACEMENT:
            paused = controls.placement_paused
            return toggle(spec, words.paused if paused else words.on, Command.PLACEMENT, on=not paused)
        case EntryId.DARK_WHEN_AWAY:
            away = controls.dark_when_away
            return toggle(spec, words.on if away else words.off, Command.DARK_WHEN_AWAY, on=away)
        case EntryId.RECORD:
            return None if controls.recording is not None else Item(spec.label, spec.icon, Command.RECORD)
        case EntryId.SOUND:
            return controls.sound
        case EntryId.SWITCH_WINDOWS:
            return tool_item(spec.label, spec.icon, Tool.WINDOW_SWITCHER, controls.hints)
        case EntryId.COPY_TRANSCRIPT:
            return tool_item(spec.label, spec.icon, Tool.COPY_TRANSCRIPT, controls.hints)
        case EntryId.KEYMAP:
            return Item(spec.label, spec.icon, Command.KEYMAP)
        case EntryId.NOTIFICATIONS:
            return Item(spec.label, spec.icon, Command.NOTIFICATIONS)
        case EntryId.ALL_CONTROLS:
            return Item(spec.label, spec.icon, Command.ALL_CONTROLS)
        case _:
            assert_never(spec.entry)


def activities(controls: Controls, words: MenuWords) -> tuple[Live, ...]:
    return (Live(words.recording, controls.recording, Command.STOP_RECORDING),) if controls.recording is not None else ()


def present_cells(controls: Controls, specs: tuple[CellSpec, ...], menu: ControlsSpec) -> tuple[tuple[CellSpec, Entry], ...]:
    """A row's cells that show now, in order: a cell whose entry is absent leaves no gap."""
    return tuple((each, present) for each in specs if (present := entry(each, controls, menu)))


def height(row: RowSpec, controls: Controls, spec: ControlsSpec) -> int:
    """The tracks `row` takes now: an empty row takes none."""
    match row:
        case ActivitiesRow(tracks=tracks):
            return tracks * len(activities(controls, spec.words))
        case TrayRow(tracks=tracks):
            return tracks * ((len(controls.tray) + COLUMNS - 1) // COLUMNS)
        case CellsRow(tracks=tracks, cells=specs):
            return tracks if present_cells(controls, specs, spec) else 0
        case _:
            assert_never(row)


def row_cells(row: RowSpec, controls: Controls, top: int, spec: ControlsSpec) -> tuple[Cell, ...]:
    """`row`'s cells from `top`, each following the one before it."""
    match row:
        case ActivitiesRow(tracks=tracks):
            cards = enumerate(activities(controls, spec.words))
            return tuple(Cell(activity, Face.CARD, 0, COLUMNS, top + tracks * index, tracks) for index, activity in cards)
        case TrayRow(tracks=tracks):
            return tuple(
                Cell(TrayIcon(name, slot), Face.ICON, slot % COLUMNS, 1, top + tracks * (slot // COLUMNS), tracks)
                for slot, name in enumerate(controls.tray)
            )
        case CellsRow(tracks=tracks, cells=specs):
            shown = present_cells(controls, specs, spec)
            columns = accumulate((each.span for each, _ in shown), initial=0)
            return tuple(
                Cell(present, each.face, column, each.span, top, tracks, each.caption)
                for (each, present), column in zip(shown, columns, strict=False)
            )
        case _:
            assert_never(row)


def entries(controls: Controls, spec: ControlsSpec, panel: Panel) -> tuple[Cell, ...]:
    """`panel`'s grid for what's happening now, flowed from its rows: each row
    starts below the one before it, so no two cells overlap. Tracks include the gutters."""
    rows = spec.panels[panel]
    tops = accumulate((height(row, controls, spec) for row in rows), initial=0)
    return tuple(chain.from_iterable(row_cells(row, controls, top, spec) for row, top in zip(rows, tops, strict=False)))


@dataclass(frozen=True, slots=True)
class Menu:
    """The open panel: which it is, its grid and the cell under the keyboard or pointer."""

    panel: Panel
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


DISMISSED = sentinel("DISMISSED")
"""Escape closed the menu."""


type Outcome = Menu | Chosen | Applied | DISMISSED


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


VOLUME_STEP: Final = 0.05


def sideways(menu: Menu, entry: Entry | None, key: Key) -> Outcome:
    """Left and Right change the volume on the slider and otherwise move."""
    match entry:
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
        case Command.OVERLAY | Command.PLACEMENT | Command.DARK_WHEN_AWAY | Command.RECORD | Command.STOP_RECORDING:
            return True
        case Command.KEYMAP | Command.NOTIFICATIONS | Command.ALL_CONTROLS | TrayChoice():
            return False
        case _:
            assert_never(choice)
