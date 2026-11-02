"""The island's controls menu: its entries, and keyboard navigation as pure transitions.

The menu is the island expanded. Ongoing activities come first as live rows with
their Stop; then Workspace's places, keyboard and desktop tools. Window tiling
discloses its items in place. Arrows wrap and skip separators; Right or Enter
opens tiling and Left or Escape closes it; a letter jumps to the next entry
starting with it. Choosing a window tool or leaving with Escape returns the
keyboard to the window that had it; opening a Workspace view keeps it there.
"""

from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Final, assert_never

from assistant.meeting_detection import AutomaticStatus
from desktop_ui.keymap import shortcut, shortcut_hint
from protocol import Tool


class Command(Enum):
    CANVAS = auto()
    FEED = auto()
    RECORD = auto()
    STOP_RECORDING = auto()
    AUTOMATIC_RECORDING = auto()
    STOP_AGENT = auto()
    KEYMAP = auto()
    OVERLAY = auto()
    TASKBAR = auto()
    NOTIFICATIONS = auto()
    ALL_CONTROLS = auto()


@dataclass(frozen=True, slots=True)
class ToolChoice:
    """A Tool selected from the menu; window tools retain the window that had the keyboard."""

    tool: Tool


type Choice = Command | ToolChoice


@dataclass(frozen=True, slots=True)
class Item:
    label: str
    icon: str  # Empty for a disclosed item: it reads under its group's symbol.
    choice: Choice
    key: str = ""  # A shortcut hint, shown quietly at the trailing edge.


def tool_item(label: str, icon: str, tool: Tool) -> Item:
    """Top-level Tool rows advertise the physical keys from the layout that triggers them."""
    return Item(label, icon, ToolChoice(tool), shortcut_hint(shortcut(tool), compact=True))


@dataclass(frozen=True, slots=True)
class Live:
    """An ongoing activity: its reading (empty while it has none) and its Stop."""

    label: str
    detail: str
    stop: Command


class Rule(Enum):
    SEPARATOR = auto()


@dataclass(frozen=True, slots=True)
class Disclosure:
    label: str
    icon: str
    items: tuple[Item, ...]


type Entry = Item | Live | Rule | Disclosure

TILING: Final = Disclosure(
    "Window tiling",
    "grid",
    (
        # Disclosed labels fill the fixed menu width; the longest tiling label
        # overlaps its derived hint in the native preview, so hints stay above.
        Item("Spread windows across screens", "", ToolChoice(Tool.TILE_BALANCE)),
        Item("Focus left", "", ToolChoice(Tool.TILE_FOCUS_LEFT)),
        Item("Focus right", "", ToolChoice(Tool.TILE_FOCUS_RIGHT)),
        Item("Previous workspace", "", ToolChoice(Tool.TILE_PREVIOUS_WORKSPACE)),
        Item("Next workspace", "", ToolChoice(Tool.TILE_NEXT_WORKSPACE)),
        Item("Float or tile the active window", "", ToolChoice(Tool.TILE_FLOAT)),
        Item("Change split direction", "", ToolChoice(Tool.TILE_DIRECTION)),
        Item("Pause or resume automatic tiling", "", ToolChoice(Tool.TILE_PAUSE)),
    ),
)


def automatic_label(status: AutomaticStatus) -> str:
    match status:
        case AutomaticStatus.OFF:
            return "Auto-record Teams: Off"
        case AutomaticStatus.CHECKING:
            return "Auto-record Teams: Connecting…"
        case AutomaticStatus.READY:
            return "Auto-record Teams: On"
        case AutomaticStatus.UNAVAILABLE:
            return "Auto-record Teams: Check connection"
        case _:
            assert_never(status)


def entries(*, recording: str | None, agent: str | None, automatic: AutomaticStatus = AutomaticStatus.OFF) -> tuple[Entry, ...]:
    """The menu for what's happening now: `recording` and `agent` are their readings while they run."""
    live: tuple[Live, ...] = (
        *((Live("Agent working", agent, Command.STOP_AGENT),) if agent is not None else ()),
        *((Live("Recording", recording, Command.STOP_RECORDING),) if recording is not None else ()),
    )
    return (
        *live,
        *((Rule.SEPARATOR,) if live else ()),
        Item("Your work canvas", "canvas", Command.CANVAS),
        Item("Your work feed", "chat", Command.FEED),
        *(() if recording is not None else (Item("Record a meeting", "mic", Command.RECORD),)),
        Item(automatic_label(automatic), "mic", Command.AUTOMATIC_RECORDING),
        Rule.SEPARATOR,
        Item("Keyboard map", "keyboard", Command.KEYMAP),
        Item("Keyboard overlay", "layers", Command.OVERLAY),
        Item("Windows taskbar", "table", Command.TASKBAR),
        Rule.SEPARATOR,
        tool_item("Switch windows", "search", Tool.WINDOW_SWITCHER),
        tool_item("Copy latest transcript", "doc", Tool.COPY_TRANSCRIPT),
        TILING,
        Item("Windows notification settings", "bell", Command.NOTIFICATIONS),
        Rule.SEPARATOR,
        Item("All Workspace controls…", "more", Command.ALL_CONTROLS),
    )


@dataclass(frozen=True, slots=True)
class Menu:
    """The open menu: its entries, a reading beside its heading, the row under the keyboard
    or pointer, and whether tiling is open."""

    entries: tuple[Entry, ...]
    detail: str
    selected: int | None = None
    disclosed: bool = field(default=False, kw_only=True)


def opened(entry: Entry, *, disclosed: bool) -> tuple[Entry, ...]:
    match entry:
        case Disclosure(items=items) if disclosed:
            return (entry, *items)
        case Item() | Live() | Rule() | Disclosure():
            return (entry,)
        case _:
            assert_never(entry)


def rows(menu: Menu) -> tuple[Entry, ...]:
    """The rows on screen: tiling's items follow it while it's open."""
    return tuple(row for entry in menu.entries for row in opened(entry, disclosed=menu.disclosed))


def selectable(row: Entry) -> bool:
    match row:
        case Rule.SEPARATOR:
            return False
        case Item() | Live() | Disclosure():
            return True
        case _:
            assert_never(row)


def label(row: Entry) -> str:
    match row:
        case Item(label=text) | Live(label=text) | Disclosure(label=text):
            return text
        case Rule.SEPARATOR:
            return ""
        case _:
            assert_never(row)


def heads(row: Entry | None) -> bool:
    """Whether a row is tiling's own row."""
    match row:
        case Disclosure():
            return True
        case _:
            return False


def within(row: Entry | None) -> bool:
    """Whether a row is one of tiling's items."""
    match row:
        case Item() if row in TILING.items:
            return True
        case _:
            return False


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


class Dismissed(Enum):
    ESCAPE = auto()


type Outcome = Menu | Chosen | Dismissed


def current(menu: Menu) -> Entry | None:
    shown = rows(menu)
    return shown[menu.selected] if menu.selected is not None and menu.selected < len(shown) else None


def step(menu: Menu, offset: int) -> Menu:
    candidates = tuple(index for index, row in enumerate(rows(menu)) if selectable(row))
    if not candidates:
        return menu
    if menu.selected not in candidates:
        return replace(menu, selected=candidates[0 if offset > 0 else -1])
    return replace(menu, selected=candidates[(candidates.index(menu.selected) + offset) % len(candidates)])


def disclose(menu: Menu, *, open_: bool) -> Menu:
    """Open tiling with its first item selected, or close it back onto its own row."""
    row, after = current(menu), rows(replace(menu, disclosed=open_))
    head = next(index for index, entry in enumerate(after) if heads(entry))
    if open_ and heads(row):
        selected: int | None = head + 1
    elif not open_ and within(row):
        selected = head
    else:
        selected = next((index for index, entry in enumerate(after) if entry == row), None)
    return replace(menu, disclosed=open_, selected=selected)


def press(menu: Menu, key: Press) -> Outcome:
    row = current(menu)
    match key:
        case Key.DOWN:
            return step(menu, 1)
        case Key.UP:
            return step(menu, -1)
        case Key.RIGHT if heads(row):
            return disclose(menu, open_=True)
        case Key.LEFT | Key.ESCAPE if menu.disclosed:
            return disclose(menu, open_=False)
        case Key.ESCAPE:
            return Dismissed.ESCAPE
        case Key.ENTER:
            return choose(menu, row)
        case Letter(character=character):
            return jump(menu, character)
        case Key.LEFT | Key.RIGHT:
            return menu
        case _:
            assert_never(key)


def choose(menu: Menu, row: Entry | None) -> Outcome:
    match row:
        case Item(choice=choice):
            return Chosen(choice)
        case Live(stop=stop):
            return Chosen(stop)
        case Disclosure():
            return disclose(menu, open_=not menu.disclosed)
        case Rule.SEPARATOR | None:
            return menu
        case _:
            assert_never(row)


def jump(menu: Menu, character: str) -> Menu:
    shown = rows(menu)
    start = menu.selected if menu.selected is not None else -1
    order = tuple((start + offset) % len(shown) for offset in range(1, len(shown) + 1))
    target = next((index for index in order if selectable(shown[index]) and label(shown[index]).casefold().startswith(character.casefold())), None)
    return menu if target is None else replace(menu, selected=target)


def restores_focus(choice: Choice) -> bool:
    """Window tools and quiet toggles hand the keyboard back; Workspace's own views keep it."""
    match choice:
        case ToolChoice():
            return True
        case Command.OVERLAY | Command.TASKBAR | Command.RECORD | Command.STOP_RECORDING | Command.STOP_AGENT | Command.AUTOMATIC_RECORDING:
            return True
        case Command.CANVAS | Command.FEED | Command.KEYMAP | Command.NOTIFICATIONS | Command.ALL_CONTROLS:
            return False
        case _:
            assert_never(choice)
