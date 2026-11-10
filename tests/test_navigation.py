"""Navigation decisions: spatial focus, desktop jumps, zoom, and app keys."""

from dataclasses import replace

from desktop_ui.navigation import (
    AppKey,
    Direction,
    Focus,
    JumpDesktop,
    Launch,
    SpatialFocus,
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
    FULL,
    NOWHERE,
    Group,
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
from tests.test_window_layout import ABOVE, CODE, EDGE, FOUR_K, LAPTOP, LEFT_HALF, LEFT_TWO_THIRDS, RIGHT_HALF, RIGHT_THIRD, SIDE, TERMINAL
from winapi.screen import Monitor

# The test's own arrangement: at home, terminals two thirds and Code a third across
# the 4K screen with Teams on the laptop, then Edge and Outlook on the next desktop;
# at work, Teams and Outlook on the laptop, Terminal and Edge above it, Code on the side.
SETUPS = Setups(
    externals=test_window_layout.SETUPS.externals,
    layouts=frozendict(
        {
            Setup.LAPTOP_ONLY: frozendict(),
            Setup.HOME: frozendict(
                {
                    TERMINAL: (Position(1, Role.MAIN, LEFT_TWO_THIRDS),),
                    CODE: (Position(1, Role.MAIN, RIGHT_THIRD),),
                    PinnedApp.TEAMS: (Position(1, Role.LAPTOP, FULL),),
                    EDGE: (Position(2, Role.MAIN, LEFT_HALF),),
                    PinnedApp.OUTLOOK: (Position(2, Role.MAIN, RIGHT_HALF),),
                }
            ),
            Setup.WORK: frozendict(
                {
                    CODE: (Position(1, Role.SIDE, FULL),),
                    TERMINAL: (Position(1, Role.ABOVE, LEFT_TWO_THIRDS),),
                    EDGE: (Position(1, Role.ABOVE, RIGHT_THIRD),),
                    PinnedApp.TEAMS: (Position(1, Role.LAPTOP, LEFT_HALF),),
                    PinnedApp.OUTLOOK: (Position(1, Role.LAPTOP, RIGHT_HALF),),
                }
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
HOME_APPS = (Group(TERMINAL, (1, 2)), Group(CODE, (3,)), Group(PinnedApp.TEAMS, (4,)), Group(EDGE, (5,)), Group(PinnedApp.OUTLOOK, (6,)))
WORK_APPS = (Group(PinnedApp.TEAMS, (1,)), Group(PinnedApp.OUTLOOK, (2,)), Group(TERMINAL, (3,)), Group(CODE, (4,)), Group(EDGE, (5,)))
TERMINAL_KEY = App("terminal", Installed("windowsterminal.exe", "wt.exe"))


def world(apps: tuple[Group, ...], *, work: bool = False, foreground: int = 1) -> World:
    placement = place(WORK if work else HOME, apps, NOWHERE)
    # Desktop 1 is the canvas's; the apps start on the second.
    return World(
        4,
        1,
        foreground,
        frozendict((group.app, group.windows) for group in apps),
        frozendict((handle, target.desktop) for handle, target in placement.items()),
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


def test_spatial_focus_picks_the_neighbour_sharing_the_most_edge_across_monitors() -> None:
    # Defects: focus skips the adjacent terminal for a farther window, crosses to
    # a window that only touches a corner, wraps around, or leaves the desktop.
    home = world(HOME_APPS)
    assert focused(home, Direction.RIGHT) == 2
    assert focused(home, Direction.LEFT) == 4
    assert focused(replace(home, foreground=3), Direction.RIGHT) is None
    assert focused(replace(home, foreground=3), Direction.UP) is None
    assert focused(replace(home, foreground=2), Direction.LEFT) == 1
    work = world(WORK_APPS, work=True)
    # Teams and Outlook on the laptop, Terminal ⅔ and Edge ⅓ above it, Code on the portrait SIDE.
    assert focused(work, Direction.RIGHT) == 2
    assert focused(work, Direction.UP) == 3
    assert focused(replace(work, foreground=2), Direction.UP) == 5
    assert focused(replace(work, foreground=5), Direction.DOWN) == 2
    assert focused(replace(work, foreground=3), Direction.LEFT) == 4
    assert focused(replace(work, foreground=4), Direction.RIGHT) == 3
    assert focused(replace(home, foreground=99), Direction.LEFT) is None


def test_desktop_jumps_stay_on_existing_desktops_and_land_on_the_last_window_used_there() -> None:
    # Defects: a jump leaves the existing desktops, a jump to the current
    # desktop switches anyway, or arriving ignores the last window used.
    home = world(HOME_APPS)
    assert effect(JumpDesktop(4), home) is None
    assert effect(JumpDesktop(1), home) is None
    assert effect(JumpDesktop(2), home) == Switch(2, 5)
    assert effect(JumpDesktop(2), replace(home, recent=(1, 6, 5))) == Switch(2, 6)
    assert effect(JumpDesktop(3), home) == Switch(3, None)
    # Defect: the observer keeps the old desktop as current after a switch, or after focusing a window on another desktop.
    assert destination(effect(JumpDesktop(2), home), home) == 2
    assert destination(Focus(5), home) == home.located[5]
    assert destination(None, home) == home.current


def test_zoom_exempts_the_window_in_front_until_pressed_again_or_focus_leaves() -> None:
    home = world(HOME_APPS, foreground=3)
    assert effect(Zoom(), home) == ZoomIn(3)
    assert effect(Zoom(), replace(home, zoomed=3)) == ZoomOut(3)
    assert effect(Zoom(), replace(home, foreground=99)) is None
    assert zoom_after(3, 3) == 3
    assert zoom_after(3, 4) is None


def test_app_keys_cycle_the_apps_windows_or_launch_it() -> None:
    # Defects: a repeated tap stays on the same window, a missing app isn't
    # started, or a web-app key launches desktop Outlook instead of its slot.
    home = world(HOME_APPS)
    assert effect(AppKey(TERMINAL_KEY), replace(home, foreground=3)) == Focus(1)
    assert effect(AppKey(TERMINAL_KEY), home) == Focus(2)
    assert effect(AppKey(TERMINAL_KEY), replace(home, foreground=2)) == Focus(1)
    outlook = App("outlook", PinnedWeb("outlook"))
    assert effect(AppKey(outlook), home) == Focus(6)
    empty = world(())
    assert effect(AppKey(outlook), empty) == Launch(PinnedApp.OUTLOOK)
    assert effect(AppKey(TERMINAL_KEY), empty) == Launch(Installed("windowsterminal.exe", "wt.exe"))
