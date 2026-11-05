"""Key hints: which letter each window shows while the chord is held, and the panel of every chord."""

from dataclasses import replace

from desktop_ui.key_hints import HIDDEN, PANEL, ActionCap, AppCap, DirectionCap, Group, Keycap, Row, Section, hints, panel
from desktop_ui.navigation import Direction, Focus, Source, SpatialFocus, World, decide
from desktop_ui.window_layout import CODE, EDGE, TERMINAL, Target
from miryoku.firmware import CHORDS
from protocol import Tool
from winapi.shapes import Rect

# Two terminals stacked on the left, Edge and Code stacked on the right, a third
# terminal on desktop 2 and a minimized Code window, which placement leaves out.
PLACEMENT = frozendict(
    {
        1: Target(0, Rect(0, 0, 960, 600)),
        5: Target(0, Rect(0, 600, 960, 1200)),
        2: Target(0, Rect(960, 0, 1920, 800)),
        3: Target(0, Rect(960, 800, 1920, 1200)),
        4: Target(1, Rect(0, 0, 1920, 1200)),
    }
)
WORLD = World(
    2,
    0,
    1,
    frozendict({TERMINAL: (1, 5, 4), EDGE: (2,), CODE: (3, 6)}),
    frozendict({1: 0, 5: 0, 2: 0, 3: 0, 4: 1, 6: 0}),
    PLACEMENT,
    (),
    None,
)


def badges(world: World) -> dict[int, tuple[Keycap, ...]]:
    return {badge.window: badge.keycaps for badge in hints(world, 0.0).badges}


def test_badges_carry_each_apps_letter_and_mark_the_window_its_next_press_reaches() -> None:
    # Defects: the wrong app's letter, a cycle mark on the focused window instead
    # of the next one, a mark on an app's only window, or Zoom and Minimize off focus.
    shown = badges(WORLD)
    assert shown[1] == (AppCap("Q", next=False), ActionCap("M"), ActionCap("V"))
    assert shown[5] == (AppCap("Q", next=True), DirectionCap("E", Direction.DOWN))
    assert shown[2] == (AppCap("W", next=False), DirectionCap("O", Direction.RIGHT))
    assert shown[3] == (AppCap("A", next=True),)
    assert badges(replace(WORLD, foreground=5))[1] == (AppCap("Q", next=False), DirectionCap("I", Direction.UP))


def test_direction_letters_name_the_window_spatial_focus_reaches() -> None:
    # Defect: a hint drifts from the decision and points at a window the chord skips.
    for foreground in (1, 5, 2, 3):
        world = replace(WORLD, foreground=foreground)
        shown = badges(world)
        for direction in Direction:
            expected: frozenset[int]
            match decide(SpatialFocus(direction, Source.KEY), world)[0]:
                case Focus(window=window):
                    expected = frozenset({window})
                case None:
                    expected = frozenset()
                case other:
                    raise AssertionError(other)
            drawn = frozenset(window for window, caps in shown.items() if any(cap == DirectionCap(cap.letter, direction) for cap in caps))
            assert drawn == expected, (foreground, direction)


def test_only_placed_windows_on_the_current_desktop_get_badges() -> None:
    # Defects: badges for the minimized Code window or the terminal on desktop 2.
    assert set(badges(WORLD)) == {1, 5, 2, 3}
    assert set(badges(replace(WORLD, current=1, foreground=4))) == {4}


def test_hints_show_while_held_add_the_panel_after_a_pause_and_hide_on_release() -> None:
    assert hints(WORLD, None) == HIDDEN
    assert hints(None, None) == HIDDEN
    assert hints(WORLD, 0.59).panel == ()
    assert hints(WORLD, 0.6).panel == PANEL
    assert hints(None, 0.6).badges == ()


def test_the_panel_lists_every_chord_once_in_its_section() -> None:
    # Defects: a chord missing or repeated, or one filed under the wrong section.
    letters = [row.letter for group in PANEL for row in group.rows]
    assert sorted(letters) == sorted(CHORDS.values())
    assert [group.section for group in PANEL] == [Section.APPS, Section.DESKTOPS, Section.FOCUS, Section.WINDOW]
    remapped = panel({Tool.MINIMIZE: "Z", Tool.FOCUS_LEFT: "Q", Tool.DESKTOP_NEXT: "X"})
    assert remapped == (
        Group(Section.DESKTOPS, (Row("X", "Desk →"),)),
        Group(Section.FOCUS, (Row("Q", "Focus ←"),)),
        Group(Section.WINDOW, (Row("Z", "Min"),)),
    )
