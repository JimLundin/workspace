"""The key map's shortcut lookup: which physical key and thumb reach a tool."""

from desktop_ui.keymap import Shortcut, shortcut
from protocol import Tool


def test_shortcuts_use_physical_keys_the_right_thumb_and_dedicated_voice_first() -> None:
    # Defects: using BASE outputs as keycaps, selecting another layer's thumb,
    # advertising the Tools-layer dictation copy instead of its dedicated key, or
    # dropping the hint of a tool only a chord reaches.
    assert shortcut(Tool.DICTATE) == Shortcut("L", "X")
    assert shortcut(Tool.MEETING_TOGGLE) == Shortcut("C", "X")
