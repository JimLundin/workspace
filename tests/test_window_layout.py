"""Monitor setups, declared positions, splitting and overflow desktops."""

from desktop_ui.shell_items import EMPTY_SHELF, PinnedApp, shelf
from desktop_ui.window_layout import (
    CODE,
    EDGE,
    NOWHERE,
    TERMINAL,
    Group,
    Program,
    Role,
    Screens,
    Setup,
    Target,
    WorkspaceView,
    dark_when_away,
    groups,
    managed,
    place,
    reading_order,
    screens,
)
from winapi.screen import Monitor
from winapi.shapes import Rect, Window

LAPTOP = Monitor(Rect(0, 0, 1920, 1200), Rect(0, 0, 1920, 1200), primary=True, internal=True)
FOUR_K = Monitor(Rect(1920, -269, 5760, 1891), Rect(1920, -269, 5760, 1891), primary=False, internal=False)
"""The 32-inch 4K screen at home, right of the laptop, as Windows reports them."""
ABOVE = Monitor(Rect(-320, -1440, 2240, 0), Rect(-320, -1440, 2240, 0), primary=False, internal=False)
SIDE = Monitor(Rect(-1760, -1360, -320, 1200), Rect(-1760, -1360, -320, 1200), primary=False, internal=False)
PYTHON, NOTEPAD, PAINT = Program("python.exe"), Program("notepad.exe"), Program("mspaint.exe")


def targets(placement: frozendict[int, Target]) -> dict[int, tuple[int, Rect]]:
    return {handle: (target.desktop, target.rect) for handle, target in placement.items()}


def test_setups_match_their_screens_and_assign_work_roles_by_orientation() -> None:
    # Defects: the 4K screen isn't recognized as home, work roles follow the
    # screens' positions instead of their orientation, or an unknown screen set
    # isn't treated as the laptop alone on its own panel.
    assert screens((LAPTOP, FOUR_K)) == Screens(Setup.HOME, frozendict({Role.LAPTOP: LAPTOP.work, Role.MAIN: FOUR_K.work}))
    work = Screens(Setup.WORK, frozendict({Role.LAPTOP: LAPTOP.work, Role.ABOVE: ABOVE.work, Role.SIDE: SIDE.work}))
    assert screens((SIDE, ABOVE, LAPTOP)) == work
    rearranged_side = Monitor(Rect(2240, -2000, 3680, 560), Rect(2240, -2000, 3680, 520), primary=True, internal=False)
    assert screens((LAPTOP, ABOVE, rearranged_side)) == Screens(
        Setup.WORK, frozendict({Role.LAPTOP: LAPTOP.work, Role.ABOVE: ABOVE.work, Role.SIDE: rearranged_side.work})
    )
    projector = Monitor(Rect(1920, 0, 3840, 1080), Rect(1920, 0, 3840, 1040), primary=True, internal=False)
    assert screens((LAPTOP, projector)) == Screens(Setup.LAPTOP_ONLY, frozendict({Role.LAPTOP: LAPTOP.work}))
    assert screens((LAPTOP, FOUR_K, projector)) == Screens(Setup.LAPTOP_ONLY, frozendict({Role.LAPTOP: LAPTOP.work}))
    docked = Monitor(FOUR_K.area, FOUR_K.work, primary=True, internal=False)
    assert screens((docked,)) == Screens(Setup.LAPTOP_ONLY, frozendict({Role.LAPTOP: docked.work}))
    assert screens(()) is None


def test_only_the_home_4k_screen_goes_dark_when_away() -> None:
    # Defects: the laptop panel or an unprotected work screen is turned off, or
    # an unrecognized screen of the same size as a protected one is.
    assert dark_when_away((LAPTOP, FOUR_K)) == frozenset({FOUR_K})
    assert dark_when_away((SIDE, ABOVE, LAPTOP)) == frozenset()
    assert dark_when_away((LAPTOP,)) == frozenset()
    projector = Monitor(Rect(-1920, 0, 0, 1080), Rect(-1920, 0, 0, 1080), primary=False, internal=False)
    assert dark_when_away((LAPTOP, FOUR_K, projector)) == frozenset()
    assert dark_when_away(()) == frozenset()


def test_home_places_terminals_and_code_across_the_4k_and_teams_on_the_laptop() -> None:
    # Defects: a declared position lands on the wrong desktop or screen, the two
    # terminals don't split their two thirds, or Code doesn't meet them exactly.
    home = screens((LAPTOP, FOUR_K))
    assert home is not None
    apps = (
        Group(TERMINAL, (1, 2)),
        Group(CODE, (3,)),
        Group(PinnedApp.TEAMS, (4,)),
        Group(EDGE, (5,)),
        Group(PinnedApp.OUTLOOK, (6,)),
        Group(WorkspaceView.CANVAS, (7,)),
    )
    assert targets(place(home, apps, NOWHERE)) == {
        7: (0, Rect(1920, -269, 5760, 1891)),
        1: (1, Rect(1920, -269, 3200, 1891)),
        2: (1, Rect(3200, -269, 4480, 1891)),
        3: (1, Rect(4480, -269, 5760, 1891)),
        4: (1, Rect(0, 0, 1920, 1200)),
        5: (2, Rect(1920, -269, 3840, 1891)),
        6: (2, Rect(3840, -269, 5760, 1891)),
    }


def test_laptop_alone_gives_the_canvas_the_first_of_five_desktops_and_terminals_two_more() -> None:
    # Defects: the canvas isn't alone on the first desktop, the second terminal
    # doesn't take the right half of desktop 3, or the third doesn't join Code.
    alone = screens((LAPTOP,))
    assert alone is not None
    apps = (
        Group(WorkspaceView.CANVAS, (9,)),
        Group(PinnedApp.OUTLOOK, (1,)),
        Group(PinnedApp.TEAMS, (2,)),
        Group(TERMINAL, (3, 6, 7)),
        Group(CODE, (4,)),
        Group(EDGE, (5,)),
    )
    assert targets(place(alone, apps, NOWHERE)) == {
        9: (0, Rect(0, 0, 1920, 1200)),
        1: (1, Rect(0, 0, 960, 1200)),
        2: (1, Rect(960, 0, 1920, 1200)),
        3: (2, Rect(0, 0, 960, 1200)),
        6: (2, Rect(960, 0, 1920, 1200)),
        7: (3, Rect(0, 0, 960, 1200)),
        4: (3, Rect(960, 0, 1920, 1200)),
        5: (4, Rect(0, 0, 1920, 1200)),
    }


def test_windows_beyond_an_apps_places_share_its_last_place_and_fewer_leave_places_empty() -> None:
    # Defects: a fourth terminal is dropped or overlaps the third, or a lone
    # terminal is stretched over places meant for others.
    alone = screens((LAPTOP,))
    assert alone is not None
    assert targets(place(alone, (Group(TERMINAL, (3, 6, 7, 8)),), NOWHERE)) == {
        3: (2, Rect(0, 0, 960, 1200)),
        6: (2, Rect(960, 0, 1920, 1200)),
        # The half-width laptop place is portrait, so the two stack.
        7: (3, Rect(0, 0, 960, 600)),
        8: (3, Rect(0, 600, 960, 1200)),
    }
    assert targets(place(alone, (Group(TERMINAL, (3,)),), NOWHERE)) == {3: (2, Rect(0, 0, 960, 1200))}


def test_work_gives_the_canvas_the_upper_screen_then_everything_on_one_desktop() -> None:
    work = screens((LAPTOP, ABOVE, SIDE))
    assert work is not None
    apps = (Group(PinnedApp.TEAMS, (1,)), Group(PinnedApp.OUTLOOK, (2,)), Group(TERMINAL, (3,)), Group(CODE, (4,)), Group(EDGE, (5,)))
    assert targets(place(work, (Group(WorkspaceView.CANVAS, (6,)), *apps), NOWHERE)) == {
        6: (0, Rect(-320, -1440, 2240, 0)),
        1: (1, Rect(-1760, -1360, -320, -80)),
        2: (1, Rect(-1760, -80, -320, 1200)),
        3: (1, Rect(-320, -1440, 960, 0)),
        4: (1, Rect(960, -1440, 2240, 0)),
        5: (1, Rect(0, 0, 1920, 1200)),
    }


def test_undeclared_apps_keep_their_own_desktops_while_others_come_and_go() -> None:
    # Defects: a surviving app hops down when an earlier one closes, a newcomer
    # doesn't reuse the freed desktop, or a desktop index left from another
    # setup's overflow overrides a declared desktop.
    alone = screens((LAPTOP,))
    assert alone is not None
    first = place(alone, (Group(PYTHON, (1, 2)), Group(NOTEPAD, (3,))), NOWHERE)
    assert targets(first) == {1: (5, Rect(0, 0, 960, 1200)), 2: (5, Rect(960, 0, 1920, 1200)), 3: (6, Rect(0, 0, 1920, 1200))}
    second = place(alone, (Group(PAINT, (4,)), Group(NOTEPAD, (3,))), first)
    assert targets(second) == {4: (5, Rect(0, 0, 1920, 1200)), 3: (6, Rect(0, 0, 1920, 1200))}
    third = place(alone, (Group(PYTHON, (1, 2)), Group(PAINT, (4,))), first)
    assert targets(third) == {1: (5, Rect(0, 0, 960, 1200)), 2: (5, Rect(960, 0, 1920, 1200)), 4: (6, Rect(0, 0, 1920, 1200))}
    from_home = frozendict({3: Target(2, Rect(0, 0, 1920, 1200))})
    assert targets(place(alone, (Group(NOTEPAD, (3,)),), from_home)) == {3: (5, Rect(0, 0, 1920, 1200))}


def test_windows_stack_in_a_portrait_region() -> None:
    portrait = Screens(Setup.LAPTOP_ONLY, frozendict({Role.LAPTOP: Rect(0, 0, 1200, 1920)}))
    assert targets(place(portrait, (Group(PYTHON, (1, 2, 3)),), NOWHERE)) == {
        1: (5, Rect(0, 0, 1200, 640)),
        2: (5, Rect(0, 640, 1200, 1280)),
        3: (5, Rect(0, 1280, 1200, 1920)),
    }


def test_pinned_web_apps_are_not_placed_as_ordinary_edge() -> None:
    # Defects: a Teams window is also grouped as Edge, or an unmanaged window
    # keeps its group alive and takes a share of the region.
    edge, teams, dialog = (
        Window(1, "News", "msedge.exe", minimized=False),
        Window(2, "Chat", "msedge.exe", minimized=False),
        Window(3, "Save", "notepad.exe", minimized=False),
    )
    observed = shelf((edge, teams, dialog), {1: "MSEdge", 2: "MSEdge.teams.cloud.microsoft_/"}, EMPTY_SHELF)
    assert groups(observed, frozenset({1, 2})) == (Group(PinnedApp.TEAMS, (2,)), Group(EDGE, (1,)))


def test_resizable_windows_of_other_programs_are_managed_even_when_minimized() -> None:
    # Defect: a minimized window keeps its stale desktop after the monitors
    # change, so the user has to find and restore it by hand.
    window = Window(1, "Editor", "code.exe", minimized=False)
    assert managed(window, resizable=True, own=False)
    assert not managed(window, resizable=False, own=False)
    assert not managed(window, resizable=True, own=True)
    assert managed(Window(1, "Editor", "code.exe", minimized=True), resizable=True, own=False)
    assert not managed(Window(1, "Elevated", "", minimized=False), resizable=True, own=False)


def test_a_desktops_apps_read_left_to_right_then_top_to_bottom_running_or_not() -> None:
    # Defects: the pager orders a desktop's icons by when the apps started
    # rather than where they sit, lists an app placed on another desktop, or
    # leaves out an app the layout puts there because it isn't running.
    work = screens((LAPTOP, ABOVE, SIDE))
    assert work is not None
    apps = (Group(EDGE, (5,)), Group(CODE, (4,)), Group(PinnedApp.OUTLOOK, (2,)), Group(TERMINAL, (3,)), Group(PinnedApp.TEAMS, (1,)))
    placement = place(work, (Group(WorkspaceView.CANVAS, (6,)), *apps), NOWHERE)
    windows = frozendict((group.app, group.windows) for group in apps)
    # SIDE is leftmost (Teams above Outlook), then ABOVE's Terminal, then the laptop's Edge, then ABOVE's Code.
    assert reading_order(work, windows, placement, 1) == (PinnedApp.TEAMS, PinnedApp.OUTLOOK, TERMINAL, EDGE, CODE)
    assert reading_order(work, windows, placement, 0) == (WorkspaceView.CANVAS,)
    alone = screens((LAPTOP,))
    assert reading_order(alone, frozendict(), NOWHERE, 3) == (TERMINAL, CODE)
    assert reading_order(alone, frozendict(), NOWHERE, 5) == ()
    assert reading_order(None, windows, placement, 0) == ()
