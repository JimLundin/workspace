from desktop_ui.keymap import KeyboardView, Shortcut
from protocol import Tool
from tests import layouts

VIEW = KeyboardView.of(layouts.LAYOUT, layouts.APPS)
"""The tests' own layout, as the desktop reads it."""


def test_shortcuts_use_physical_keys_the_right_thumb_and_dedicated_voice_first() -> (
    None
):
    assert VIEW.shortcut(Tool.DICTATE) == Shortcut("L", "X")
    assert VIEW.shortcut(Tool.MEETING_TOGGLE) == Shortcut("C", "X")
