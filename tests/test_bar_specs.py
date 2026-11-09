"""The layout reads every size from the sizes it is given.

The sizes and specs here are the test's own: scaling every size scales every
coordinate, whatever the bar's real sizes are.
"""

from dataclasses import asdict

from desktop_ui.bar_events import BarSpec
from desktop_ui.island_layout import Bar, Capsule, MenuGrid, Metrics, Placed, Sizes, arrange, frame, tiles
from desktop_ui.island_menu import Menu, entries
from desktop_ui.island_model import Action, Control, Glyph, Key, Marker, Text, Zone, order
from tests import test_island_menu, test_island_model, test_island_motion

BASE = Sizes(
    Bar(top=5, edge=20, gap=10, radius=3, shadow=7),
    Capsule(height=40, control=30, icon=16, dot=8, dots=18, wave_bars=3, part_gap=4, slot_gap=9, text_pad=11, icon_pad=7),
    MenuGrid(width=200, radius=9, pad=5, head=40, track=4, gutter=2),
)

SPEC = BarSpec(test_island_model.SPEC, test_island_menu.SPEC, test_island_motion.SPRINGS, BASE)
"""The test's own bar, for tests of the bar's decisions."""


def doubled(sizes: Sizes) -> Sizes:
    """Every size twice as large; the trace's bar count is a count, not a size."""
    capsule = {name: value * 2 for name, value in asdict(sizes.capsule).items()}
    return Sizes(
        Bar(**{name: value * 2 for name, value in asdict(sizes.bar).items()}),
        Capsule(**{**capsule, "wave_bars": sizes.capsule.wave_bars}),
        MenuGrid(**{name: value * 2 for name, value in asdict(sizes.menu).items()}),
    )


def test_every_size_the_bar_lays_out_comes_from_the_sizes_it_is_given() -> None:
    # Defect: a size is still a literal in the layout, so editing the sizes moves only
    # part of the bar and its parts drift out of alignment.
    large = doubled(BASE)

    def width(text: Text) -> float:
        return 7.0 * len(text.text)

    def wide(text: Text) -> float:
        return 2 * width(text)

    rows = ((Marker.DOT, Text("Reading"), Control("stop", "Stop", Action.OPEN_MENU)),), ((Glyph("mic.fill"), Marker.DOT, Marker.DOTS),)
    for slots in rows:
        small, big = arrange(slots, width, BASE), arrange(slots, wide, large)
        assert (big.width, big.height) == (2 * small.width, 2 * small.height)
        assert [spot.x for spot in big.spots] == [2 * spot.x for spot in small.spots]
    capsules = (Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.STATUS, Zone.RIGHT, 200, 34), Placed(Key.RECORDING, Zone.TRAIL, 40, 34))
    bars = ((BASE, capsules, 1000.0), (large, tuple(Placed(c.key, c.zone, 2 * c.width, 2 * c.height) for c in capsules), 2000.0))
    small_frame, big_frame = (
        frame(placed, Metrics(screen, s.bar.top, s.bar.gap, s.bar.edge), order(test_island_model.SPEC)) for s, placed, screen in bars
    )
    assert [(f.box.x * 2, f.box.y * 2, f.box.width * 2) for f in small_frame] == [(f.box.x, f.box.y, f.box.width) for f in big_frame]
    menu = Menu(entries(test_island_menu.RESTING, test_island_menu.SPEC))
    pairs = zip(tiles(menu, BASE.menu), tiles(menu, large.menu), strict=True)
    assert all((2 * a.x, 2 * a.y, 2 * a.width, 2 * a.height) == (b.x, b.y, b.width, b.height) for a, b in pairs)
