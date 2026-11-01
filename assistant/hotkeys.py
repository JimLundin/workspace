"""Every tool key's behavior, shared by dispatch and the visible key map."""

from enum import Enum, auto
from typing import assert_never

from protocol import Tool


class Route(Enum):
    HOLD = auto()
    TOGGLE = auto()
    STOP = auto()
    REWRITE = auto()
    ASK = auto()
    SCREEN_TEXT = auto()
    SCREEN_ASK = auto()
    AGENT_SESSION = auto()
    TRANSCRIPT = auto()
    ARRANGE = auto()
    BALANCE = auto()
    SWITCHER = auto()
    INBOX = auto()
    MEETING = auto()


def route(tool: Tool) -> Route:
    match tool:
        case Tool.DICTATE | Tool.DICTATE_CLEAN | Tool.DICTATE_COMMAND | Tool.REWRITE_VOICE | Tool.AGENT_VOICE:
            return Route.HOLD
        case Tool.DICTATE_TOGGLE | Tool.AGENT_VOICE_TOGGLE:
            return Route.TOGGLE
        case Tool.STOP:
            return Route.STOP
        case Tool.FIX | Tool.TRANSLATE | Tool.SHORTER | Tool.FORMAL:
            return Route.REWRITE
        case Tool.ASK:
            return Route.ASK
        case Tool.SCREEN_TEXT:
            return Route.SCREEN_TEXT
        case Tool.SCREEN_ASK:
            return Route.SCREEN_ASK
        case Tool.AGENT_TYPED:
            return Route.AGENT_SESSION
        case Tool.COPY_TRANSCRIPT:
            return Route.TRANSCRIPT
        case (
            Tool.SNAP_LEFT
            | Tool.SNAP_RIGHT
            | Tool.MAXIMIZE
            | Tool.MINIMIZE
            | Tool.NEXT_MONITOR
            | Tool.TILE_FOCUS_LEFT
            | Tool.TILE_FOCUS_DOWN
            | Tool.TILE_FOCUS_UP
            | Tool.TILE_FOCUS_RIGHT
            | Tool.TILE_FLOAT
            | Tool.TILE_PREVIOUS_WORKSPACE
            | Tool.TILE_NEXT_WORKSPACE
            | Tool.TILE_DIRECTION
            | Tool.TILE_PAUSE
        ):
            return Route.ARRANGE
        case Tool.TILE_BALANCE:
            return Route.BALANCE
        case Tool.WINDOW_SWITCHER:
            return Route.SWITCHER
        case Tool.OPEN_INBOX:
            return Route.INBOX
        case Tool.MEETING_TOGGLE:
            return Route.MEETING
        case _:
            assert_never(tool)


def needs_settings(kind: Route) -> bool:
    """Only model routes need AI settings; desktop controls remain available."""
    match kind:
        case Route.HOLD | Route.TOGGLE | Route.REWRITE | Route.ASK | Route.SCREEN_TEXT | Route.SCREEN_ASK | Route.AGENT_SESSION:
            return True
        case Route.STOP | Route.TRANSCRIPT | Route.ARRANGE | Route.BALANCE | Route.SWITCHER | Route.INBOX | Route.MEETING:
            return False
        case _:
            assert_never(kind)
