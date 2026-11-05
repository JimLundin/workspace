"""How the workspace's two programs talk. The layout (miryoku) owns the keyboard;
the assistant does everything slow. Keys on the layout send the assistant
requests, as window messages: they are queued, ordered, cost the layout nothing
to send, and need no admin rights. Plain Python: importable anywhere.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, Literal

LAYOUT_MAGIC: Final = 0x4D49_5250
"""Layout output: bypass remapping without invalidating its own snippet history."""

MAGIC: Final = 0x4D49_524F
"""Tags input the workspace sends, so the layout's hook lets it through untouched."""

SWITCHER_TITLE: Final = "Workspace window switcher"
"""The assistant's window switcher; the layout passes Esc, Enter and Tab to it while it has focus."""


_WM_APP: Final = 0x8000
WM_REQUEST: Final = _WM_APP + 1
"""Layout -> assistant: a key went down (lparam 1) or up (lparam 0); wparam is `encode(request)`."""
WM_LAYOUT_STATE: Final = _WM_APP + 2
"""Layout -> assistant: wparam is a `LayoutState` value."""
WM_QUIT_LAYOUT: Final = _WM_APP + 3
"""Keeper -> layout: release held keys, then exit cleanly."""
WM_INDICATOR: Final = _WM_APP + 4
"""Layout -> assistant: what the layer indicator shows; wparam is `encode_indicator(...)`."""
WM_TOGGLE_LAYOUT: Final = _WM_APP + 5
"""Assistant -> layout: toggle on/off, as if the escape key was tapped."""
WM_QUERY_LAYOUT_STATE: Final = _WM_APP + 6
"""Assistant -> layout: reply with the layout, layer and physically held keys."""
WM_KEY_STATE: Final = _WM_APP + 7
"""Layout -> assistant: physical scancode in wparam, down/up in lparam (1/0).
Scancode 0 clears the held keys, before a state replay or when the layout stops."""
WM_CHORD: Final = _WM_APP + 8
"""Layout -> assistant: wparam is 1 while the firmware keyboard holds Ctrl+Alt+Shift, else 0."""


class LayoutState(Enum):
    OFF = 0
    """Switched off with the escape key or tray toggle: the keyboard is plain."""
    ON = 1
    QUIT = 2


class Tool(Enum):
    """What a tool key asks the assistant to do. Hold-to-talk tools use the key's
    press and release; the rest act on press."""

    DICTATE = 1
    """Hold and speak: the words are typed as said."""
    DICTATE_CLEAN = 2
    """Hold and speak: typed tidied up (no filler words, proper punctuation)."""
    DICTATE_COMMAND = 3
    """Hold and describe a command: the PowerShell command is typed, not run."""
    AGENT_VOICE = 30
    """Hold and say a task for the agent."""
    AGENT_TYPED = 31
    """Type a task for the agent in a box."""
    STOP = 32
    """Stop the agent."""
    MEETING_TOGGLE = 33
    AGENT_VOICE_TOGGLE = 34
    COPY_TRANSCRIPT = 35
    WINDOW_SWITCHER = 36
    DICTATE_TOGGLE = 37
    OPEN_INBOX = 38
    ZOOM = 42
    """Fill the focused window's monitor until pressed again or focus leaves it."""
    MINIMIZE = 43
    FOCUS_LEFT = 50
    """Focus the nearest placed window in that direction, across monitors."""
    FOCUS_DOWN = 51
    FOCUS_UP = 52
    FOCUS_RIGHT = 53
    PLACEMENT_PAUSE = 58
    """Pause or resume automatic window placement."""
    PLACE_NOW = 59
    """Put every window back where it belongs now."""
    DESKTOP_1 = 60
    DESKTOP_2 = 61
    DESKTOP_3 = 62
    DESKTOP_4 = 63


@dataclass(frozen=True, slots=True)
class Installed:
    """A program started from its command."""

    exe: str
    """The program's file name, as Task Manager shows it: `WindowsTerminal.exe`."""
    command: str
    """How to start it: anything the Run dialog (Win+R) accepts."""


@dataclass(frozen=True, slots=True)
class PinnedWeb:
    """One of the toolbar's pinned web apps, opened as an Edge app window like its slot."""

    slot: Literal["outlook", "teams"]


@dataclass(frozen=True, slots=True)
class App:
    """An application an app key goes to: its placed window, the next one while it's
    already in front, or starting it when it isn't running."""

    name: str
    target: Installed | PinnedWeb


type Request = Tool | App

_APP_BASE: Final = 1000


def encode(request: Request, apps: Sequence[App]) -> int:
    """The request as a message's wparam. Apps are sent by their place in the list."""
    match request:
        case Tool():
            value: int = request.value
            return value
        case App():
            return _APP_BASE + apps.index(request)  # ValueError if it isn't in the list


def decode(code: int, apps: Sequence[App]) -> Request | None:
    if code >= _APP_BASE:
        index = code - _APP_BASE
        return apps[index] if index < len(apps) else None
    try:
        return Tool(code)
    except ValueError:
        return None


def encode_indicator(layer: int, *, locked: bool, caps_word: bool) -> int:
    """The indicator's state as a message's wparam. `layer`: the layer's value, 0 for the base layer."""
    return layer | locked << 4 | caps_word << 5


def decode_indicator(code: int) -> tuple[int, bool, bool]:
    return code & 0xF, bool(code & 0x10), bool(code & 0x20)
