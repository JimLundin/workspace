"""Every tool key's behavior, shared by dispatch and the visible key map."""

from enum import Enum, auto
from typing import assert_never

from protocol import Tool


class Route(Enum):
    HOLD = auto()
    TOGGLE = auto()
    STOP = auto()
    AGENT_SESSION = auto()
    TRANSCRIPT = auto()
    NAVIGATE = auto()
    SWITCHER = auto()
    INBOX = auto()
    MEETING = auto()


def route(tool: Tool) -> Route:
    match tool:
        case Tool.DICTATE | Tool.AGENT_VOICE:
            return Route.HOLD
        case Tool.DICTATE_TOGGLE | Tool.AGENT_VOICE_TOGGLE:
            return Route.TOGGLE
        case Tool.STOP:
            return Route.STOP
        case Tool.AGENT_TYPED:
            return Route.AGENT_SESSION
        case Tool.COPY_TRANSCRIPT:
            return Route.TRANSCRIPT
        case (
            Tool.ZOOM
            | Tool.FOCUS_LEFT
            | Tool.FOCUS_DOWN
            | Tool.FOCUS_UP
            | Tool.FOCUS_RIGHT
            | Tool.DESKTOP_1
            | Tool.DESKTOP_2
            | Tool.DESKTOP_3
            | Tool.DESKTOP_4
            | Tool.DESKTOP_5
            | Tool.PLACEMENT_PAUSE
            | Tool.PLACE_NOW
        ):
            return Route.NAVIGATE
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
        case Route.HOLD | Route.TOGGLE | Route.AGENT_SESSION:
            return True
        case Route.STOP | Route.TRANSCRIPT | Route.NAVIGATE | Route.SWITCHER | Route.INBOX | Route.MEETING:
            return False
        case _:
            assert_never(kind)
