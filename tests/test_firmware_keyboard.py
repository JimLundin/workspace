"""Detect selecting unrelated keyboards, losing the device across USB ports, or misreading its shortcuts."""

from pathlib import Path

from config import APPS
from desktop_ui.keymap import describe
from miryoku.firmware import CHORDS, connected, shortcut
from miryoku.layout import TABLE, Layer
from protocol import App, Tool


def test_only_the_configured_firmware_keyboard_suspends_remapping() -> None:
    other = (r"\\?\HID#VID_1050&PID_0407&MI_00#yubikey", r"\\?\HID#INTC816&COL01#laptop")
    assert not connected(other)
    for path in (r"\\?\HID#VID_A8F8&PID_1832&MI_00#port-one", r"\\?\hid#vid_a8f8&pid_1832&mi_00#port-two"):
        assert connected((*other, path))
    assert not connected((r"\\?\HID#VID_A8F8&PID_1833&MI_00#other-product",))


def test_apps_thumb_letters_reach_navigation_voice_and_the_configured_apps() -> None:
    # Defects: a letter reaches the wrong tool, app letters lose config's order,
    # or a voice hold moves off the laptop's place for it.
    held = {"apps_held": True}
    assert [shortcut(ord(letter), **held) for letter in "NEIO"] == [Tool.FOCUS_LEFT, Tool.FOCUS_DOWN, Tool.FOCUS_UP, Tool.FOCUS_RIGHT]
    assert [shortcut(ord(letter), **held) for letter in "JLUY"] == [Tool.DESKTOP_1, Tool.DESKTOP_2, Tool.DESKTOP_3, Tool.DESKTOP_4]
    assert [shortcut(ord(letter), **held) for letter in "MXCDV"] == [
        Tool.ZOOM,
        Tool.PLACEMENT_PAUSE,
        Tool.WINDOW_SWITCHER,
        Tool.PLACE_NOW,
        Tool.MINIMIZE,
    ]
    assert [shortcut(ord(letter), **held) for letter in "QWFPBARSTG"] == list(APPS[:10])
    assert shortcut(ord("H"), apps_held=True) is Tool.DICTATE
    assert shortcut(ord("K"), apps_held=True) is Tool.AGENT_VOICE
    assert shortcut(0x20, apps_held=True) is Tool.MEETING_TOGGLE  # the Space thumb's place


def test_without_the_apps_thumb_and_for_unassigned_keys_keys_keep_their_meaning() -> None:
    # Defects: a key is taken without the Apps thumb held, or an unassigned
    # letter or punctuation is swallowed.
    for vk in (ord("Z"), 0xDB, 0x31):
        assert shortcut(vk, apps_held=True) is None
    for vk in (ord("H"), ord("J"), ord("Q")):
        assert shortcut(vk, apps_held=False) is None


def test_readme_lists_every_chord_by_its_key_map_name() -> None:
    # Defect: the chord table changes while the README's documentation drifts.
    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")
    rows = [line for line in readme.splitlines() if line.startswith("| Apps **")]
    assert rows == [f"| Apps **{letter}** | {describe(request)[0]} |" for request, letter in CHORDS.items()]


def test_the_chords_are_exactly_the_apps_layer() -> None:
    # Defects: an Apps layer request the firmware keyboard can't reach, a chord
    # with no place on the laptop, or another layer binding a request again.
    requests = {binding for binding in TABLE[Layer.APPS] if isinstance(binding, (Tool, App))}
    assert set(CHORDS) == requests
    elsewhere = {binding for layer, row in TABLE.items() if layer is not Layer.APPS for binding in row}
    assert elsewhere.isdisjoint(CHORDS)
