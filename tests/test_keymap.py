"""The key map: what each physical key does, per layer; and the indicator's words."""

from desktop_ui.keymap import ROWS, Kind, Shortcut, indicator_text, keymap, shortcut, shortcut_hint
from miryoku.firmware import CHORDS
from miryoku.layout import Layer
from protocol import Tool
lazy from desktop_ui.keymap import TOOL_NAMES


def caps(layer: Layer | None) -> dict[str, tuple[str, str, Kind]]:
    return {cap.physical: (cap.label, cap.hold, cap.kind) for row in keymap(layer) for cap in row}


def test_rows_are_the_nordic_iso_keyboard() -> None:
    assert [len(row) for row in ROWS] == [13, 12, 13, 11, 1]
    assert ROWS[0][0][1] == "§"
    assert ROWS[3][0][1] == "<"


def test_shortcuts_use_physical_keys_the_right_thumb_and_dedicated_voice_first() -> None:
    # Defects: using BASE outputs as keycaps, selecting another layer's thumb,
    # advertising the Tools-layer dictation copy instead of its dedicated key, or
    # dropping the hint of a tool only a chord reaches.
    assert shortcut(Tool.OPEN_INBOX) == Shortcut("M", "X")
    assert shortcut(Tool.DICTATE) == Shortcut("L", "X")
    assert shortcut(Tool.AGENT_VOICE) == Shortcut("K", "X")
    assert shortcut_hint(shortcut(Tool.WINDOW_SWITCHER), compact=True) == "X S"


def test_shortcut_hints_share_keycap_notation_and_omit_absent_bindings() -> None:
    # Defects: the compact hint uses a layer's name, a dedicated key acquires a
    # nonexistent thumb, or a missing binding renders "None".
    assert shortcut_hint(Shortcut("P", "V")) == "Hold V + P"
    assert shortcut_hint(Shortcut("X", "."), compact=True) == ". X"
    assert shortcut_hint(Shortcut("Space", None)) == "Space"
    assert shortcut_hint(None) == ""


def test_base_layer() -> None:
    base = caps(None)
    assert base["2"] == ("Q", "", Kind.KEY)
    assert base["Q"] == ("A", "Win", Kind.KEY)  # home row mod: tap A, hold Win
    assert base["C"] == ("Space", "Nav", Kind.KEY)
    assert base["M"] == ("Enter", "Sym", Kind.KEY)
    assert base[","] == ("Bksp", "Num", Kind.KEY)
    assert base["X"] == ("Esc", "Apps", Kind.KEY)
    assert base["."] == ("Del", "", Kind.KEY)
    assert base["-"] == ("", "", Kind.BLANK)
    assert base["§"] == ("On/off", "hold: quit", Kind.SPECIAL)
    assert base["B"] == base["N"] == base["Space"] == ("", "", Kind.BLANK)
    assert base["Y"] == ("", "", Kind.BLANK)


def test_layers_show_their_keys_and_the_thumb_holding_them() -> None:
    nav = caps(Layer.NAV)
    assert nav["O"] == ("←", "", Kind.KEY)
    assert nav["8"] == ("Redo", "", Kind.KEY)
    assert nav["Q"] == ("Win", "", Kind.MOD)
    assert nav["C"][2] is Kind.HELD
    sym = caps(Layer.SYM)
    assert sym["2"] == ("{", "", Kind.KEY)
    assert sym["M"][2] is Kind.HELD
    assert caps(Layer.NUM)[","][2] is Kind.HELD


def test_the_apps_layer_holds_every_workspace_request() -> None:
    # Defects: a voice hold loses its hold marking, or a request moves off the
    # place its firmware chord letter names.
    apps = caps(Layer.APPS)
    assert apps["K"] == ("Agent talk", "hold", Kind.TOOL)
    assert apps["L"] == ("Talk", "hold", Kind.TOOL)
    assert apps["2"] == ("Terminal", "", Kind.APP)
    assert apps["8"] == ("Desk 1", "", Kind.TOOL)
    assert apps["M"] == ("Inbox", "", Kind.TOOL)
    assert apps["X"][2] is Kind.HELD


def test_every_tool_is_on_the_key_map_or_a_chord() -> None:
    # Defect: removing a binding leaves a tool no key reaches.
    layers: list[Layer | None] = [None, *list(Layer)]
    labels = {cap.label for layer in layers for row in keymap(layer) for cap in row if cap.kind is Kind.TOOL}
    labels |= {TOOL_NAMES[request] for request in CHORDS if isinstance(request, Tool)}
    assert labels == {TOOL_NAMES[tool] for tool in Tool}


def test_indicator_text() -> None:
    assert indicator_text(None, locked=False, caps_word=False) is None
    assert indicator_text(Layer.NAV, locked=False, caps_word=False) == "NAV"
    assert indicator_text(Layer.NUM, locked=True, caps_word=False) == "NUM · locked"
    assert indicator_text(None, locked=False, caps_word=True) == "CAPS WORD"
    assert indicator_text(Layer.SYM, locked=False, caps_word=True) == "SYM · CAPS WORD"
