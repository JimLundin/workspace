"""Every tool key's behavior, shared by dispatch and the visible key map."""

from enum import Enum, auto
from typing import Final

from contracts.members import every_member
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


ROUTES: Final = every_member(
    Tool,
    {
        Tool.DICTATE: Route.HOLD,
        Tool.AGENT_VOICE: Route.HOLD,
        Tool.DICTATE_TOGGLE: Route.TOGGLE,
        Tool.AGENT_VOICE_TOGGLE: Route.TOGGLE,
        Tool.STOP: Route.STOP,
        Tool.AGENT_TYPED: Route.AGENT_SESSION,
        Tool.COPY_TRANSCRIPT: Route.TRANSCRIPT,
        Tool.ZOOM: Route.NAVIGATE,
        Tool.FOCUS_LEFT: Route.NAVIGATE,
        Tool.FOCUS_DOWN: Route.NAVIGATE,
        Tool.FOCUS_UP: Route.NAVIGATE,
        Tool.FOCUS_RIGHT: Route.NAVIGATE,
        Tool.DESKTOP_1: Route.NAVIGATE,
        Tool.DESKTOP_2: Route.NAVIGATE,
        Tool.DESKTOP_3: Route.NAVIGATE,
        Tool.DESKTOP_4: Route.NAVIGATE,
        Tool.DESKTOP_5: Route.NAVIGATE,
        Tool.PLACEMENT_PAUSE: Route.NAVIGATE,
        Tool.PLACE_NOW: Route.NAVIGATE,
        Tool.WINDOW_SWITCHER: Route.SWITCHER,
        Tool.OPEN_INBOX: Route.INBOX,
        Tool.MEETING_TOGGLE: Route.MEETING,
    },
)
"""The route each tool key takes."""


NEEDS_SETTINGS: Final = every_member(
    Route,
    {
        Route.HOLD: True,
        Route.TOGGLE: True,
        Route.AGENT_SESSION: True,
        Route.STOP: False,
        Route.TRANSCRIPT: False,
        Route.NAVIGATE: False,
        Route.SWITCHER: False,
        Route.INBOX: False,
        Route.MEETING: False,
    },
)
