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
    dark_when_locked,
    groups,
    managed,
    place,
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


def test_only_the_home_4k_screen_goes_dark_when_locked() -> None:
    # Defects: the laptop panel or an unprotected work screen is turned off, or
    # an unrecognized screen of the same size as a protected one is.
    assert dark_when_locked((LAPTOP, FOUR_K)) == frozenset({FOUR_K})
    assert dark_when_locked((SIDE, ABOVE, LAPTOP)) == frozenset()
    assert dark_when_locked((LAPTOP,)) == frozenset()
    projector = Monitor(Rect(-1920, 0, 0, 1080), Rect(-1920, 0, 0, 1080), primary=False, internal=False)
    assert dark_when_locked((LAPTOP, FOUR_K, projector)) == frozenset()
    assert dark_when_locked(()) == frozenset()


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
    )
    assert targets(place(home, apps, NOWHERE)) == {
        1: (0, Rect(1920, -269, 3200, 1891)),
        2: (0, Rect(3200, -269, 4480, 1891)),
        3: (0, Rect(4480, -269, 5760, 1891)),
        4: (0, Rect(0, 0, 1920, 1200)),
        5: (1, Rect(1920, -269, 3840, 1891)),
        6: (1, Rect(3840, -269, 5760, 1891)),
    }


def test_laptop_alone_spreads_the_apps_over_three_desktops() -> None:
    alone = screens((LAPTOP,))
    assert alone is not None
    apps = (Group(PinnedApp.OUTLOOK, (1,)), Group(PinnedApp.TEAMS, (2,)), Group(TERMINAL, (3,)), Group(CODE, (4,)), Group(EDGE, (5,)))
    assert targets(place(alone, apps, NOWHERE)) == {
        1: (0, Rect(0, 0, 960, 1200)),
        2: (0, Rect(960, 0, 1920, 1200)),
        3: (1, Rect(0, 0, 960, 1200)),
        4: (1, Rect(960, 0, 1920, 1200)),
        5: (2, Rect(0, 0, 1920, 1200)),
    }


def test_work_puts_everything_on_one_desktop_across_three_screens() -> None:
    work = screens((LAPTOP, ABOVE, SIDE))
    assert work is not None
    apps = (Group(PinnedApp.TEAMS, (1,)), Group(PinnedApp.OUTLOOK, (2,)), Group(TERMINAL, (3,)), Group(CODE, (4,)), Group(EDGE, (5,)))
    assert targets(place(work, apps, NOWHERE)) == {
        1: (0, Rect(-1760, -1360, -320, -80)),
        2: (0, Rect(-1760, -80, -320, 1200)),
        3: (0, Rect(-320, -1440, 960, 0)),
        4: (0, Rect(960, -1440, 2240, 0)),
        5: (0, Rect(0, 0, 1920, 1200)),
    }


def test_undeclared_apps_keep_their_own_desktops_while_others_come_and_go() -> None:
    # Defects: a surviving app hops down when an earlier one closes, a newcomer
    # doesn't reuse the freed desktop, or a desktop index left from another
    # setup's overflow overrides a declared desktop.
    alone = screens((LAPTOP,))
    assert alone is not None
    first = place(alone, (Group(PYTHON, (1, 2)), Group(NOTEPAD, (3,))), NOWHERE)
    assert targets(first) == {1: (3, Rect(0, 0, 960, 1200)), 2: (3, Rect(960, 0, 1920, 1200)), 3: (4, Rect(0, 0, 1920, 1200))}
    second = place(alone, (Group(PAINT, (4,)), Group(NOTEPAD, (3,))), first)
    assert targets(second) == {4: (3, Rect(0, 0, 1920, 1200)), 3: (4, Rect(0, 0, 1920, 1200))}
    third = place(alone, (Group(PYTHON, (1, 2)), Group(PAINT, (4,))), first)
    assert targets(third) == {1: (3, Rect(0, 0, 960, 1200)), 2: (3, Rect(960, 0, 1920, 1200)), 4: (4, Rect(0, 0, 1920, 1200))}
    from_home = frozendict({3: Target(2, Rect(0, 0, 1920, 1200))})
    assert targets(place(alone, (Group(NOTEPAD, (3,)),), from_home)) == {3: (3, Rect(0, 0, 1920, 1200))}


def test_windows_stack_in_a_portrait_region() -> None:
    portrait = Screens(Setup.LAPTOP_ONLY, frozendict({Role.LAPTOP: Rect(0, 0, 1200, 1920)}))
    assert targets(place(portrait, (Group(PYTHON, (1, 2, 3)),), NOWHERE)) == {
        1: (3, Rect(0, 0, 1200, 640)),
        2: (3, Rect(0, 640, 1200, 1280)),
        3: (3, Rect(0, 1280, 1200, 1920)),
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


def test_only_resizable_restored_windows_of_other_programs_are_managed() -> None:
    window = Window(1, "Editor", "code.exe", minimized=False)
    assert managed(window, resizable=True, own=False)
    assert not managed(window, resizable=False, own=False)
    assert not managed(window, resizable=True, own=True)
    assert not managed(Window(1, "Editor", "code.exe", minimized=True), resizable=True, own=False)
    assert not managed(Window(1, "Elevated", "", minimized=False), resizable=True, own=False)
