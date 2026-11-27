from dataclasses import replace

from desktop_ui.navigation import (
    AppKey,
    Direction,
    Focus,
    JumpDesktop,
    Launch,
    SpatialFocus,
    StepLayer,
    Switch,
    World,
    Zoom,
    ZoomIn,
    ZoomOut,
    destination,
    effect,
    zoom_after,
)
from desktop_ui.shell_items import PinnedApp
from desktop_ui.window_layout import (
    Group,
    Layout,
    Position,
    Role,
    Screens,
    Setup,
    Setups,
    place,
    screens,
)
from protocol import App, Installed, PinnedWeb
from tests import test_window_layout
from tests.test_window_layout import (
    ABOVE,
    CODE,
    EDGE,
    FOUR_K,
    FULL,
    LAPTOP,
    LEFT_HALF,
    LEFT_TWO_THIRDS,
    RIGHT_HALF,
    RIGHT_THIRD,
    SIDE,
    TERMINAL,
)
from winapi.screen import Monitor

SETUPS = Setups(
    externals=test_window_layout.SETUPS.externals,
    layouts=frozendict(
        {
            Setup.LAPTOP_ONLY: Layout(
                frozendict(), others=Position(0, Role.LAPTOP, FULL)
            ),
            Setup.HOME: Layout(
                frozendict(
                    {
                        TERMINAL: (Position(1, Role.MAIN, LEFT_TWO_THIRDS),),
                        CODE: (Position(1, Role.MAIN, RIGHT_THIRD),),
                        PinnedApp.TEAMS: (Position(1, Role.LAPTOP, FULL),),
                        EDGE: (Position(2, Role.MAIN, LEFT_HALF),),
                        PinnedApp.OUTLOOK: (
                            Position(2, Role.MAIN, RIGHT_HALF),
                        ),
                    }
                ),
                others=Position(2, Role.LAPTOP, FULL),
            ),
            Setup.WORK: Layout(
                frozendict(
                    {
                        CODE: (Position(1, Role.SIDE, FULL),),
                        TERMINAL: (Position(1, Role.ABOVE, LEFT_TWO_THIRDS),),
                        EDGE: (Position(1, Role.ABOVE, RIGHT_THIRD),),
                        PinnedApp.TEAMS: (Position(1, Role.LAPTOP, LEFT_HALF),),
                        PinnedApp.OUTLOOK: (
                            Position(1, Role.LAPTOP, RIGHT_HALF),
                        ),
                    }
                ),
                others=Position(2, Role.LAPTOP, FULL),
            ),
        }
    ),
    dark_when_away=frozendict(),
)


def matched(monitors: tuple[Monitor, ...]) -> Screens:
    found = screens(monitors, SETUPS)
    assert found is not None
    return found


HOME = matched((LAPTOP, FOUR_K))
WORK = matched((LAPTOP, ABOVE, SIDE))
HOME_APPS = (
    Group(TERMINAL, (1, 2)),
    Group(CODE, (3,)),
    Group(PinnedApp.TEAMS, (4,)),
    Group(EDGE, (5,)),
    Group(PinnedApp.OUTLOOK, (6,)),
)
WORK_APPS = (
    Group(PinnedApp.TEAMS, (1,)),
    Group(PinnedApp.OUTLOOK, (2,)),
    Group(TERMINAL, (3,)),
    Group(CODE, (4,)),
    Group(EDGE, (5,)),
)
TERMINAL_KEY = App("terminal", Installed("windowsterminal.exe", "wt.exe"))


def world(
    apps: tuple[Group, ...], *, work: bool = False, foreground: int = 1
) -> World:
    placement = place(WORK if work else HOME, apps)
    return World(
        4,
        1,
        foreground,
        frozendict((group.app, group.windows) for group in apps),
        frozendict(
            (handle, target.desktop) for handle, target in placement.items()
        ),
        placement,
        (),
        None,
    )


def focused(at: World, direction: Direction) -> int | None:
    match effect(SpatialFocus(direction), at):
        case Focus(window=window):
            return window
        case None:
            return None
        case other:
            raise AssertionError(other)


def test_spatial_focus_picks_the_neighbour_sharing_the_most_edge_across_monitors() -> (
    None
):
    home = world(HOME_APPS)
    assert focused(home, Direction.RIGHT) == 2
    assert focused(home, Direction.LEFT) == 4
    assert focused(replace(home, foreground=3), Direction.RIGHT) is None
    assert focused(replace(home, foreground=3), Direction.UP) is None
    assert focused(replace(home, foreground=2), Direction.LEFT) == 1
    work = world(WORK_APPS, work=True)
    assert focused(work, Direction.RIGHT) == 2
    assert focused(work, Direction.UP) == 3
    assert focused(replace(work, foreground=2), Direction.UP) == 5
    assert focused(replace(work, foreground=5), Direction.DOWN) == 2
    assert focused(replace(work, foreground=3), Direction.LEFT) == 4
    assert focused(replace(work, foreground=4), Direction.RIGHT) == 3
    assert focused(replace(home, foreground=99), Direction.LEFT) is None


def test_desktop_jumps_stay_on_existing_desktops_and_land_on_the_last_window_used_there() -> (
    None
):
    home = world(HOME_APPS)
    assert effect(JumpDesktop(4), home) is None
    assert effect(JumpDesktop(1), home) is None
    assert effect(JumpDesktop(2), home) == Switch(2, 5)
    assert effect(JumpDesktop(2), replace(home, recent=(1, 6, 5))) == Switch(
        2, 6
    )
    assert effect(JumpDesktop(3), home) == Switch(3, None)
    assert destination(effect(JumpDesktop(2), home), home) == 2
    assert destination(Focus(5), home) == home.located[5]
    assert destination(None, home) == home.current


def test_zoom_exempts_the_window_in_front_until_pressed_again_or_focus_leaves() -> (
    None
):
    home = world(HOME_APPS, foreground=3)
    assert effect(Zoom(), home) == ZoomIn(3)
    assert effect(Zoom(), replace(home, zoomed=3)) == ZoomOut(3)
    assert effect(Zoom(), replace(home, foreground=99)) is None
    assert zoom_after(3, 3) == 3
    assert zoom_after(3, 4) is None


def test_app_keys_cycle_the_apps_windows_or_launch_it() -> None:
    home = world(HOME_APPS)
    assert effect(AppKey(TERMINAL_KEY), replace(home, foreground=3)) == Focus(1)
    assert effect(AppKey(TERMINAL_KEY), home) == Focus(2)
    assert effect(AppKey(TERMINAL_KEY), replace(home, foreground=2)) == Focus(1)
    outlook = App("outlook", PinnedWeb("outlook"))
    assert effect(AppKey(outlook), home) == Focus(6)
    empty = world(())
    assert effect(AppKey(outlook), empty) == Launch(PinnedApp.OUTLOOK)
    assert effect(AppKey(TERMINAL_KEY), empty) == Launch(
        Installed("windowsterminal.exe", "wt.exe")
    )


LAYERED = Screens(
    Setup.LAPTOP_ONLY,
    frozendict({Role.LAPTOP: LAPTOP.work}),
    Layout(frozendict(), others=Position(0, Role.LAPTOP, FULL), side_by_side=2),
)
"""Five windows in two-wide layers: 1 and 2 at the bottom, 3 and 4 above them, 5 alone on top."""


def layered(foreground: int) -> World:
    placement = place(LAYERED, (Group(TERMINAL, (1, 2, 3, 4, 5)),))
    return World(
        1,
        0,
        foreground,
        frozendict({TERMINAL: (1, 2, 3, 4, 5)}),
        frozendict((handle, 0) for handle in placement),
        placement,
        (),
        None,
    )


def stepped(at: World, step: int) -> int | None:
    match effect(StepLayer(step), at):
        case Focus(window=window):
            return window
        case None:
            return None
        case other:
            raise AssertionError(other)


def test_layer_keys_land_on_the_same_spot_a_layer_away_and_wrap_round() -> None:
    assert stepped(layered(1), 1) == 3
    assert stepped(layered(2), 1) == 4
    assert stepped(layered(4), 1) == 5
    assert stepped(layered(5), 1) == 1
    assert stepped(layered(1), -1) == 5
    assert stepped(world(HOME_APPS), 1) is None


def test_focus_up_and_down_climb_layers_where_no_window_lies_that_way() -> None:
    assert focused(layered(2), Direction.UP) == 4
    assert focused(layered(4), Direction.DOWN) == 2
    assert focused(layered(1), Direction.DOWN) is None
    assert focused(layered(5), Direction.UP) is None


def test_spatial_focus_skips_windows_a_higher_layer_covers() -> None:
    assert focused(layered(3), Direction.RIGHT) == 4
