"""The layout reads every size from the sizes it is given.

The sizes and specs here are the test's own: scaling every size scales every
coordinate, whatever the bar's real sizes are.
"""

from dataclasses import asdict

from desktop_ui.bar_events import BarSpec
from desktop_ui.island_layout import Bar, Capsule, Cells, Markers, MenuGrid, Metrics, Placed, Sizes, arrange, frame, tiles
from desktop_ui.island_menu import Menu, entries
from desktop_ui.island_model import Action, Control, Glyph, Key, Marker, Text, Zone, order
from tests import test_island_menu, test_island_model, test_island_motion

BASE = Sizes(
    bar=Bar(top=5, edge=20, gap=10, radius=3, shadow=7, pager_gap=11),
    capsule=Capsule(
        height=40,
        control=30,
        icon=16,
        dot=8,
        dots=18,
        wave_bars=3,
        wave_bar=2,
        wave_gap=3,
        part_gap=4,
        slot_gap=9,
        text_pad=11,
        icon_pad=7,
        ring_inset=1,
    ),
    menu=MenuGrid(width=200, radius=9, pad=5, head=40, track=4, gutter=2),
    markers=Markers(wave_floor=2, wave_reach=9, wave_corner=1, halo=5, dot_count=4, dots_radius=2, dots_lift=1),
    cells=Cells(
        corner=9,
        lead=10,
        trail=11,
        symbol_x=3,
        text_x=36,
        text_right=5,
        label_x=33,
        label_right=7,
        tool_top=9,
        caption_side=1,
        caption_bottom=8,
        slider_label_top=6,
        slider_label=14,
        track_bottom=18,
        track_right=12,
        track=5,
        track_corner=2,
        knob=6,
        live_dot_x=17,
        live_dot=4,
        live_text_x=37,
        live_text_right=35,
        live_elide=80,
        stop_right=5,
        tray_image=20,
    ),
)
"""The test's own sizes, unlike the bar's so a test can't pass on its values."""

SPEC = BarSpec(test_island_model.SPEC, test_island_menu.SPEC, test_island_motion.SPRINGS, BASE)
"""The test's own bar, for tests of the bar's decisions."""


def doubled(sizes: Sizes) -> Sizes:
    """Every size twice as large; the trace's bars and the job's dots are counts, not sizes."""
    capsule = {name: value * 2 for name, value in asdict(sizes.capsule).items()}
    markers = {name: value * 2 for name, value in asdict(sizes.markers).items()}
    return Sizes(
        bar=Bar(**{name: value * 2 for name, value in asdict(sizes.bar).items()}),
        capsule=Capsule(**{**capsule, "wave_bars": sizes.capsule.wave_bars}),
        menu=MenuGrid(**{name: value * 2 for name, value in asdict(sizes.menu).items()}),
        markers=Markers(**{**markers, "dot_count": sizes.markers.dot_count}),
        cells=Cells(**{name: value * 2 for name, value in asdict(sizes.cells).items()}),
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
