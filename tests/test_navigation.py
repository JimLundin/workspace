"""Navigation decisions: spatial focus, desktop jumps, zoom, and app keys."""

from dataclasses import replace

from desktop_ui.navigation import (
    AppKey,
    Direction,
    Focus,
    JumpDesktop,
    Launch,
    Navigated,
    Placing,
    Source,
    SpatialFocus,
    Switch,
    World,
    Zoom,
    ZoomIn,
    ZoomOut,
    decide,
    keyed,
    zoom_after,
)
from desktop_ui.shell_items import PinnedApp
from desktop_ui.window_layout import CODE, EDGE, NOWHERE, TERMINAL, Group, Screens, place, screens
from protocol import DESKTOP_TOOLS, App, Installed, PinnedWeb, Side, Tool, owner
from tests.test_window_layout import ABOVE, FOUR_K, LAPTOP, SIDE
from winapi.screen import Monitor


def matched(monitors: tuple[Monitor, ...]) -> Screens:
    found = screens(monitors)
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
    match decide(SpatialFocus(direction, Source.KEY), at)[0]:
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
    assert focused(work, Direction.RIGHT) == 3
    assert focused(replace(work, foreground=2), Direction.RIGHT) == 5
    assert focused(replace(work, foreground=5), Direction.LEFT) == 2
    assert focused(replace(work, foreground=1), Direction.DOWN) == 2
    assert focused(replace(home, foreground=99), Direction.LEFT) is None


def test_desktop_jumps_stay_on_existing_desktops_and_land_on_the_last_window_used_there() -> None:
    # Defects: a jump leaves the existing desktops, a jump to the current
    # desktop switches anyway, or arriving ignores the last window used.
    home = world(HOME_APPS)
    assert decide(JumpDesktop(4, Source.KEY), home)[0] is None
    assert decide(JumpDesktop(1, Source.KEY), home)[0] is None
    assert decide(JumpDesktop(2, Source.KEY), home)[0] == Switch(2, 5)
    assert decide(JumpDesktop(2, Source.KEY), replace(home, recent=(1, 6, 5)))[0] == Switch(2, 6)
    assert decide(JumpDesktop(3, Source.KEY), home)[0] == Switch(3, None)
    assert decide(JumpDesktop(2, Source.KEY), home)[1] == Navigated(JumpDesktop(2, Source.KEY), 1, 2, TERMINAL, EDGE)


def test_zoom_exempts_the_window_in_front_until_pressed_again_or_focus_leaves() -> None:
    home = world(HOME_APPS, foreground=3)
    assert decide(Zoom(Source.KEY), home)[0] == ZoomIn(3)
    assert decide(Zoom(Source.KEY), replace(home, zoomed=3))[0] == ZoomOut(3)
    assert decide(Zoom(Source.KEY), replace(home, foreground=99))[0] is None
    assert zoom_after(3, 3) == 3
    assert zoom_after(3, 4) is None


def test_app_keys_cycle_the_apps_windows_or_launch_it() -> None:
    # Defects: a repeated tap stays on the same window, a missing app isn't
    # started, or a web-app key launches desktop Outlook instead of its slot.
    home = world(HOME_APPS)
    assert decide(AppKey(TERMINAL_KEY, Source.KEY), replace(home, foreground=3))[0] == Focus(1)
    assert decide(AppKey(TERMINAL_KEY, Source.KEY), home)[0] == Focus(2)
    assert decide(AppKey(TERMINAL_KEY, Source.KEY), replace(home, foreground=2))[0] == Focus(1)
    outlook = App("outlook", PinnedWeb("outlook"))
    assert decide(AppKey(outlook, Source.KEY), home)[0] == Focus(6)
    empty = world(())
    effect, record = decide(AppKey(outlook, Source.KEY), empty)
    assert effect == Launch(PinnedApp.OUTLOOK) and record.launched and record.to_app is PinnedApp.OUTLOOK
    assert decide(AppKey(TERMINAL_KEY, Source.KEY), empty)[0] == Launch(Installed("windowsterminal.exe", "wt.exe"))


def test_navigation_keys_give_their_orders() -> None:
    # Defects: a desktop key jumps to the wrong desktop, a focus key goes the wrong
    # way, or a placement key gives no order, so the desktop drops the key.
    assert [keyed(tool) for tool in (Tool.DESKTOP_2, Tool.FOCUS_UP, Tool.ZOOM, Tool.PLACEMENT_PAUSE, Tool.DICTATE)] == [
        JumpDesktop(1, Source.KEY),
        SpatialFocus(Direction.UP, Source.KEY),
        Zoom(Source.KEY),
        Placing.TOGGLE_PAUSE,
        None,
    ]


def test_every_tool_has_one_owner_and_the_desktops_keys_need_no_assistant() -> None:
    # Defect: a key the desktop handles alone is sent to the assistant (so it fails
    # while the assistant restarts), or an assistant tool is swallowed by the desktop.
    desktop = {tool for tool in Tool if owner(tool) is Side.DESKTOP}
    assert desktop == DESKTOP_TOOLS
    assert owner(App("terminal", Installed("windowsterminal.exe", "wt.exe"))) is Side.DESKTOP
    assert all(keyed(tool) is not None for tool in desktop - {Tool.OPEN_INBOX, Tool.WINDOW_SWITCHER})
    assert all(keyed(tool) is None for tool in set(Tool) - desktop)
