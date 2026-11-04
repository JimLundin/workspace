"""Detect selecting unrelated keyboards, losing the device across USB ports, or misreading its shortcuts."""

from pathlib import Path

from config import APPS
from desktop_ui.keymap import describe
from miryoku.firmware import CHORDS, connected, shortcut
from protocol import Tool

CTRL, ALT, SHIFT, WIN = 0x1D, 0x38, 0x2A, 0x15B
RIGHT_CTRL, RIGHT_ALT, RIGHT_SHIFT, EXTENDED_RIGHT_SHIFT = 0x11D, 0x138, 0x36, 0x136


def test_only_the_configured_firmware_keyboard_suspends_remapping() -> None:
    other = (r"\\?\HID#VID_1050&PID_0407&MI_00#yubikey", r"\\?\HID#INTC816&COL01#laptop")
    assert not connected(other)
    for path in (r"\\?\HID#VID_A8F8&PID_1832&MI_00#port-one", r"\\?\hid#vid_a8f8&pid_1832&mi_00#port-two"):
        assert connected((*other, path))
    assert not connected((r"\\?\HID#VID_A8F8&PID_1833&MI_00#other-product",))


def test_ctrl_alt_shift_letters_reach_navigation_and_the_apps_layer_app_positions() -> None:
    # Defects: a letter reaches the wrong tool, app keys lose the Apps layer's
    # order, one side's modifiers are missed, or voice and chord letters collide.
    for held in ({CTRL, ALT, SHIFT}, {RIGHT_CTRL, RIGHT_ALT, RIGHT_SHIFT}):
        assert [shortcut(ord(letter), held) for letter in "NEIO"] == [Tool.FOCUS_LEFT, Tool.FOCUS_DOWN, Tool.FOCUS_UP, Tool.FOCUS_RIGHT]
        assert [shortcut(ord(letter), held) for letter in "LUYKH"] == [
            Tool.DESKTOP_1,
            Tool.DESKTOP_2,
            Tool.DESKTOP_3,
            Tool.DESKTOP_PREVIOUS,
            Tool.DESKTOP_NEXT,
        ]
        assert [shortcut(ord(letter), held) for letter in "MJCDV"] == [
            Tool.ZOOM,
            Tool.PLACEMENT_PAUSE,
            Tool.WINDOW_SWITCHER,
            Tool.PLACE_NOW,
            Tool.MINIMIZE,
        ]
        assert [shortcut(ord(letter), held) for letter in "QWFPBARSTG"] == list(APPS[:10])
    assert shortcut(ord("D"), {CTRL, SHIFT}) is Tool.DICTATE
    assert shortcut(ord("G"), {RIGHT_CTRL, EXTENDED_RIGHT_SHIFT}) is Tool.AGENT_VOICE


def test_other_letters_and_modifier_sets_keep_their_application_meaning() -> None:
    # Defects: matching a partial modifier set, accepting the Office key's Win,
    # or swallowing an unassigned letter or punctuation.
    chord = {CTRL, ALT, SHIFT}
    for vk in (ord("Z"), ord("X"), 0xBC, 0x31):
        assert shortcut(vk, chord) is None
    for held in (set[int](), {CTRL}, {CTRL, ALT}, {ALT, SHIFT}, {CTRL, SHIFT}, {CTRL, ALT, SHIFT, WIN}, {CTRL, ALT, SHIFT, 0x15C}):
        assert shortcut(ord("L"), held) is None


def test_readme_lists_every_chord_by_its_key_map_name() -> None:
    # Defect: the chord table changes while the README's documentation drifts.
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    rows = [line for line in readme.splitlines() if line.startswith("| ⌃⌥⇧ ")]
    assert rows == [f"| ⌃⌥⇧ **{letter}** | {describe(request)[0]} |" for request, letter in CHORDS.items()]
