"""The desktop's declarative specs: loading, refusal and the kept fallback."""

import re
from dataclasses import replace
from pathlib import Path

from desktop_ui.island_layout import Metrics, Placed, arrange, frame, tiles
from desktop_ui.island_menu import Command, Item, Live, Menu, Toggle, entries
from desktop_ui.island_model import Action, Control, Glyph, Key, Marker, Spinner, Text, Zone
from desktop_ui.ui_spec import SHIPPED, Sizes, SpecError, controls, sizes, starting_specs
from tests.test_island_menu import RESTING

TOKENS = (SHIPPED / "tokens.toml").read_text(encoding="utf-8")
CONTROLS = (SHIPPED / "controls.toml").read_text(encoding="utf-8")


def folder(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.mkdir(parents=True)
    (path / "tokens.toml").write_text(text, encoding="utf-8")
    (path / "controls.toml").write_text(CONTROLS, encoding="utf-8")
    return path


def refusal(tmp_path: Path, text: str) -> str:
    try:
        sizes(folder(tmp_path, "edited", text))
    except SpecError as error:
        return str(error)
    raise AssertionError("The spec was accepted.")


def test_the_shipped_specs_load() -> None:
    # Defect: a deployed spec that doesn't validate; the desktop would start on the kept copy.
    assert sizes().capsule.height >= sizes().capsule.control


def test_an_edit_that_misspells_or_overflows_a_size_is_refused_by_name(tmp_path: Path) -> None:
    # Defect: a misspelt token is ignored or an impossible one applied, and the bar
    # silently keeps or breaks its geometry instead of saying which value is wrong.
    assert refusal(tmp_path / "unknown", TOKENS.replace("gutter = 8", "gutter = 8\ngutters = 8")).startswith("tokens.toml: menu.gutters")
    assert refusal(tmp_path / "negative", TOKENS.replace("gap = 6 ", "gap = -6 ")).startswith("tokens.toml: bar.gap")
    assert refusal(tmp_path / "missing", TOKENS.replace("icon = 16\n", "")).startswith("tokens.toml: capsule.icon")
    assert "must fit" in refusal(tmp_path / "control", TOKENS.replace("control = 28", "control = 40"))
    assert refusal(tmp_path / "syntax", TOKENS + "\n[bar\n").startswith("tokens.toml: ")


def test_a_broken_edit_starts_from_the_last_spec_that_validated(tmp_path: Path) -> None:
    # Defect: a hand-edited spec that no longer validates stops the desktop from
    # starting, so the keeper restarts it into the same failure.
    live, kept = folder(tmp_path, "live", TOKENS.replace("height = 34", "height = 40")), tmp_path / "kept"
    started, problem = starting_specs(live, kept)
    assert problem is None and started.sizes.capsule.height == 40
    (live / "tokens.toml").write_text(TOKENS.replace("gap = 6 ", "gap = -1 "), encoding="utf-8")
    started, problem = starting_specs(live, kept)
    assert started.sizes.capsule.height == 40
    assert problem is not None and "bar.gap" in str(problem)


def doubled(tmp_path: Path) -> Sizes:
    """Every size twice as large; the trace's bar count is a count, not a size."""

    def twice(match: re.Match[str]) -> str:
        return match.group(0) if match.group(1) == "wave_bars" else f"{match.group(1)} = {float(match.group(2)) * 2}"

    return sizes(folder(tmp_path, "doubled", re.sub(r"(?m)^(\w+) = ([0-9.]+)", twice, TOKENS)))


def test_every_size_the_bar_lays_out_comes_from_the_spec(tmp_path: Path) -> None:
    # Defect: a size is still a literal in the layout, so editing the spec moves only
    # part of the bar and its parts drift out of alignment.
    base, large = sizes(), doubled(tmp_path)

    def width(text: Text) -> float:
        return 7.0 * len(text.text)

    def wide(text: Text) -> float:
        return 2 * width(text)

    row = ((Spinner("Agent"), Text("Reading"), Control("stop", "Stop", Action.OPEN_MENU)),), ((Glyph("bell"), Marker.DOT, Marker.DOTS),)
    for slots in row:
        small, big = arrange(slots, width, base), arrange(slots, wide, large)
        assert (big.width, big.height) == (2 * small.width, 2 * small.height)
        assert [spot.x for spot in big.spots] == [2 * spot.x for spot in small.spots]
    capsules = (Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.STATUS, Zone.RIGHT, 200, 34), Placed(Key.INBOX, Zone.TRAIL, 40, 34))
    bars = ((base, capsules, 1000.0), (large, tuple(Placed(c.key, c.zone, 2 * c.width, 2 * c.height) for c in capsules), 2000.0))
    small_frame, big_frame = (frame(placed, Metrics(screen, s.bar.top, s.bar.gap, s.bar.edge)) for s, placed, screen in bars)
    assert [(f.box.x * 2, f.box.y * 2, f.box.width * 2) for f in small_frame] == [(f.box.x, f.box.y, f.box.width) for f in big_frame]
    menu = Menu(entries(RESTING, controls()))
    pairs = zip(tiles(menu, base.menu), tiles(menu, large.menu), strict=True)
    assert all((2 * a.x, 2 * a.y, 2 * a.width, 2 * a.height) == (b.x, b.y, b.width, b.height) for a, b in pairs)


def controls_refusal(tmp_path: Path, text: str) -> str:
    path = folder(tmp_path, "edited", TOKENS)
    (path / "controls.toml").write_text(text, encoding="utf-8")
    try:
        controls(path)
    except SpecError as error:
        return str(error)
    raise AssertionError("The menu spec was accepted.")


def test_a_menu_edit_that_overflows_repeats_or_misnames_is_refused(tmp_path: Path) -> None:
    # Defect: a menu edit puts a row past the grid's edge, places an entry twice (two
    # cells, one action), names an entry that doesn't exist, or shows a toggle as a
    # slider, and the menu draws it anyway instead of keeping the last good layout.
    wide = CONTROLS.replace('{ entry = "taskbar", face = "toggle", span = 4', '{ entry = "taskbar", face = "toggle", span = 5')
    assert "span 9 of the menu's 8 columns" in controls_refusal(tmp_path / "wide", wide)
    twice = CONTROLS.replace('entry = "taskbar"', 'entry = "overlay"')
    assert "overlay is already placed" in controls_refusal(tmp_path / "twice", twice)
    assert controls_refusal(tmp_path / "unknown", CONTROLS.replace('entry = "keymap"', 'entry = "key_map"')).startswith("controls.toml: rows.")
    slider = CONTROLS.replace('{ entry = "overlay", face = "toggle"', '{ entry = "overlay", face = "slider"')
    assert "overlay can't show as slider" in controls_refusal(tmp_path / "slider", slider)
    assert "needs a label and an icon" in controls_refusal(tmp_path / "bare", CONTROLS.replace(', label = "Keyboard map"', ""))


def test_every_menu_command_is_reachable_from_the_shipped_menu() -> None:
    # Defect: an edit to the menu spec drops a control, so its action is no longer
    # reachable from the menu at all.
    resting, busy = entries(RESTING, controls()), entries(replace(RESTING, agent="Reading", recording="00:10"), controls())
    choices = {cell.entry.choice for cell in (*resting, *busy) if isinstance(cell.entry, Item | Toggle)}
    stops = {cell.entry.stop for cell in busy if isinstance(cell.entry, Live)}
    assert choices | stops >= set(Command)
