import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Final, Literal


class Origin(IntEnum):
    LAYOUT = 0x4D49_5250
    """The layout's own output."""
    DESKTOP = 0x4D49_524F
    """Text the desktop types, such as dictation."""


class Message(IntEnum):
    CLOSE = 0x0010
    """Windows' own WM_CLOSE: the gateway and the desktop take it as quit."""
    REQUEST = 0x8000 + 1
    """Layout -> desktop: a key went down (lparam 1) or up (lparam 0); wparam is `encode(request)`, a tool or a slot."""
    LAYOUT_STATE = 0x8000 + 2
    """Layout -> desktop: wparam is a `LayoutState` value."""
    QUIT_LAYOUT = 0x8000 + 3
    """Launcher -> layout: release held keys, then exit cleanly."""
    INDICATOR = 0x8000 + 4
    """Layout -> desktop: what the layer indicator shows; wparam is `encode_indicator(...)`."""
    TOGGLE_LAYOUT = 0x8000 + 5
    """Desktop -> layout: toggle on/off, as if the escape key was tapped."""
    QUERY_LAYOUT_STATE = 0x8000 + 6
    """Desktop -> layout: reply with the layout, layer and physically held keys."""
    KEY_STATE = 0x8000 + 7
    """Layout -> desktop: physical scancode in wparam, down/up in lparam (1/0).
    Scancode 0 clears the held keys, before a state replay or when the layout stops."""
    CHORD = 0x8000 + 8
    """Layout -> desktop: wparam is 1 while either keyboard holds its Apps key, else 0."""


type Component = Literal["gateway", "layout", "desktop"]


@dataclass(frozen=True, slots=True)
class Window:
    title: str
    window_class: str | None
    """None matches any class: the program uses a system class, not its own."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Entry:
    name: Component
    module: str
    """Started as `python -m <module>`."""
    window: Window
    quit_message: Message
    """Posted to `window` to ask for a clean exit; the layout lets go of held keys first."""
    shutdown_s: float
    """How long the launcher waits for a clean exit before ending the process."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Programs:
    gateway: Entry
    layout: Entry
    desktop: Entry
    switcher: str
    """The window switcher's title; the layout passes Esc, Enter and Tab to it while it has focus."""
    state_variable: str
    """The environment variable naming the launcher's state folder, which it passes to every program."""

    @property
    def catalogue(self) -> frozendict[Component, Entry]:
        return frozendict(
            {
                entry.name: entry
                for entry in (self.gateway, self.layout, self.desktop)
            }
        )


def interpreter(root: Path) -> Path:
    return root / ".venv" / "Scripts" / "pythonw.exe"


@dataclass(frozen=True, slots=True)
class Places:
    directory: Path
    """Logs, remembered preferences and meeting transcripts."""
    state: Path | None
    """The launcher's state folder, which it names in each program's environment; None outside the launcher."""

    @classmethod
    def of(cls, environ: Mapping[str, str], programs: Programs) -> Places:
        directory = (
            Path(environ.get("LOCALAPPDATA") or tempfile.gettempdir())
            / "workspace"
        )
        state = environ.get(programs.state_variable)
        return cls(directory, Path(state) if state else None)

    @property
    def gateway_endpoint(self) -> Path | None:
        return self.state / "endpoint-gateway" if self.state else None


class LayoutState(Enum):
    OFF = 0
    """Switched off with the escape key or tray toggle: the keyboard is plain."""
    ON = 1
    QUIT = 2


class Tool(Enum):
    DICTATE = 1
    """Hold and speak: the words are typed as said."""
    MEETING_TOGGLE = 33
    COPY_TRANSCRIPT = 35
    WINDOW_SWITCHER = 36
    DICTATE_TOGGLE = 37
    ZOOM = 42
    """Fill the focused window's monitor until pressed again or focus leaves it."""
    FOCUS_LEFT = 50
    """Focus the nearest placed window in that direction, across monitors."""
    FOCUS_DOWN = 51
    FOCUS_UP = 52
    FOCUS_RIGHT = 53
    LAYER_DOWN = 54
    """Bring up the layer below the focused window's, in a place stacked in layers; from the bottom, the top."""
    LAYER_UP = 55
    PLACEMENT_PAUSE = 58
    """Pause or resume automatic window placement."""
    PLACE_NOW = 59
    """Put every window back where it belongs now."""
    DESKTOP_1 = 60
    DESKTOP_2 = 61
    DESKTOP_3 = 62
    DESKTOP_4 = 63
    DESKTOP_5 = 64


@dataclass(frozen=True, slots=True)
class Installed:
    exe: str
    """The program's file name, as Task Manager shows it: `WindowsTerminal.exe`."""
    command: str
    """How to start it: anything the Run dialog (Win+R) accepts."""


@dataclass(frozen=True, slots=True)
class PinnedWeb:
    slot: Literal["outlook", "teams"]


@dataclass(frozen=True, slots=True)
class App:
    name: str
    target: Installed | PinnedWeb


@dataclass(frozen=True, slots=True)
class Slot:
    index: int


type Request = Tool | Slot
"""What a key asks of the desktop, as the layout sends it."""

type Target = Tool | App
"""What a request reaches on the desktop: a tool, or the app in a slot."""


_SLOT_BASE: Final = 1000


def encode(request: Request) -> int:
    match request:
        case Tool():
            value: int = request.value
            return value
        case Slot(index=index):
            return _SLOT_BASE + index


def decode(code: int) -> Request | None:
    if code >= _SLOT_BASE:
        return Slot(code - _SLOT_BASE)
    try:
        return Tool(code)
    except ValueError:
        return None


def reaching(request: Request, apps: Sequence[App]) -> Target | None:
    match request:
        case Tool():
            return request
        case Slot(index=index):
            return apps[index] if 0 <= index < len(apps) else None


def encode_indicator(layer: int, *, caps_word: bool) -> int:
    return layer | caps_word << 4


def decode_indicator(code: int) -> tuple[int, bool]:
    return code & 0xF, bool(code & 0x10)
