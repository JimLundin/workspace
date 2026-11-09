"""The key map: what each physical key does, per layer; and the indicator's words."""

from desktop_ui.keymap import Role, Shortcut, keymap, shortcut
from keyboard.firmware import CHORDS
from keyboard.layout import Layer
from protocol import Tool
lazy from desktop_ui.keymap import TOOL_NAMES


def caps(layer: Layer | None) -> dict[str, tuple[str, str, Role]]:
    return {cap.physical: (cap.label, cap.hold, cap.role) for row in keymap(layer) for cap in row}


def test_shortcuts_use_physical_keys_the_right_thumb_and_dedicated_voice_first() -> None:
    # Defects: using BASE outputs as keycaps, selecting another layer's thumb,
    # advertising the Tools-layer dictation copy instead of its dedicated key, or
    # dropping the hint of a tool only a chord reaches.
    assert shortcut(Tool.DICTATE) == Shortcut("L", "X")
    assert shortcut(Tool.MEETING_TOGGLE) == Shortcut("C", "X")


def test_each_key_shows_its_role_and_tap_hold_keys_their_hold() -> None:
    # Defects: a home-row mod or layer thumb loses its hold, a blocked key shows an
    # action, or a layer doesn't mark the thumb holding it.
    base = caps(None)
    assert all(base[physical][1] for physical in ("Q", "C", "M", ",", "X"))
    assert not base["2"][1]
    assert {base[physical][2] for physical in ("-", "B", "N", "Space", "Y")} == {Role.BLANK}
    assert base["§"][2] is Role.SPECIAL
    assert caps(Layer.NAV)["Q"][2] is Role.MOD
    assert caps(Layer.NAV)["C"][2] is caps(Layer.SYM)["M"][2] is caps(Layer.NUM)[","][2] is Role.HELD


def test_the_apps_layer_holds_every_workspace_request() -> None:
    # Defects: a voice hold loses its hold marking, or a request moves off the
    # place its firmware chord letter names.
    apps = caps(Layer.APPS)
    assert apps["L"][2] is Role.TOOL and apps["L"][1]
    assert apps["2"][2] is Role.APP
    assert apps["8"][2] is Role.TOOL and not apps["8"][1]
    assert apps["X"][2] is Role.HELD


def test_every_tool_is_on_the_key_map_or_a_chord() -> None:
    # Defect: removing a binding leaves a tool no key reaches.
    layers: list[Layer | None] = [None, *list(Layer)]
    labels = {cap.label for layer in layers for row in keymap(layer) for cap in row if cap.role is Role.TOOL}
    labels |= {TOOL_NAMES[request] for request in CHORDS if isinstance(request, Tool)}
    assert labels == {TOOL_NAMES[tool] for tool in Tool}
