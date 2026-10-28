"""Workspace's window-management commands; the keyboard only shares Tool identifiers."""

from typing import Final

from protocol import Tool

TILING_COMMANDS: Final[frozendict[Tool, tuple[str, ...]]] = frozendict({  # pyright: ignore[reportCallIssue]  # Python 3.15 stubs lag.
    Tool.TILE_FOCUS_LEFT: ("focus", "--direction", "left"),
    Tool.TILE_FOCUS_DOWN: ("focus", "--direction", "down"),
    Tool.TILE_FOCUS_UP: ("focus", "--direction", "up"),
    Tool.TILE_FOCUS_RIGHT: ("focus", "--direction", "right"),
    Tool.TILE_FLOAT: ("toggle-floating",),
    Tool.TILE_PREVIOUS_WORKSPACE: ("focus", "--prev-workspace"),
    Tool.TILE_NEXT_WORKSPACE: ("focus", "--next-workspace"),
    Tool.TILE_DIRECTION: ("toggle-tiling-direction",),
    Tool.TILE_PAUSE: ("wm-toggle-pause",),
})

WINDOW_COMMANDS: Final[frozendict[Tool, tuple[str, ...]]] = frozendict({  # pyright: ignore[reportCallIssue]
    Tool.SNAP_LEFT: ("move", "--direction", "left"),
    Tool.SNAP_RIGHT: ("move", "--direction", "right"),
    Tool.MAXIMIZE: ("toggle-fullscreen",),
    Tool.MINIMIZE: ("set-minimized",),
})

GLOBAL_TILING: Final = frozenset({Tool.TILE_PREVIOUS_WORKSPACE, Tool.TILE_NEXT_WORKSPACE, Tool.TILE_PAUSE})
