"""The key map's shortcut lookup: which physical key and thumb reach a tool."""

from desktop_ui.keymap import KeyboardView, Shortcut
from protocol import Tool
from tests import layouts

VIEW = KeyboardView.of(layouts.LAYOUT, layouts.APPS)
"""The tests' own layout, as the desktop reads it."""


def test_shortcuts_use_physical_keys_the_right_thumb_and_dedicated_voice_first() -> None:
    # Defects: using BASE outputs as keycaps, selecting another layer's thumb,
    # advertising the Tools-layer dictation copy instead of its dedicated key, or
    # dropping the hint of a tool only a chord reaches.
    assert VIEW.shortcut(Tool.DICTATE) == Shortcut("L", "X")
    assert VIEW.shortcut(Tool.MEETING_TOGGLE) == Shortcut("C", "X")
