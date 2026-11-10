"""Monitor setups, declared positions, splitting and overflow desktops.

The setups here are the test's own, so each test checks how windows are placed
from whatever setups it is given, never Workspace's real layouts.
"""

from fractions import Fraction

from desktop_ui.shell_items import EMPTY_SHELF, PinnedApp, shelf
from desktop_ui.window_layout import (
    FULL,
    NOWHERE,
    Group,
    Position,
    Program,
    Region,
    Role,
    Screens,
    Setup,
    Setups,
    Target,
    dark_when_away,
    groups,
    managed,
    place,
    reading_order,
    screens,
)
from tests import test_shell_items
from winapi.screen import Monitor
from winapi.shapes import Rect, Size, Window

SHELL, EDITOR, BROWSER, CHAT = Program("shell.exe"), Program("editor.exe"), Program("browser.exe"), Program("chat.exe")
TERMINAL, CODE, EDGE = Program("windowsterminal.exe"), Program("code.exe"), Program("msedge.exe")
LEFT_HALF = Region(Fraction(0), Fraction(0), Fraction(1, 2), Fraction(1))
RIGHT_HALF = Region(Fraction(1, 2), Fraction(0), Fraction(1, 2), Fraction(1))
LEFT_TWO_THIRDS = Region(Fraction(0), Fraction(0), Fraction(2, 3), Fraction(1))
RIGHT_THIRD = Region(Fraction(2, 3), Fraction(0), Fraction(1, 3), Fraction(1))
"""The tests' own programs and regions to write setups with."""
PYTHON, NOTEPAD, PAINT = Program("python.exe"), Program("notepad.exe"), Program("mspaint.exe")

SETUPS = Setups(
    externals=frozendict(
        {
            Setup.LAPTOP_ONLY: frozendict(),
            Setup.HOME: frozendict({Size(3840, 2160): Role.MAIN}),
            Setup.WORK: frozendict({Size(2560, 1440): Role.ABOVE, Size(1440, 2560): Role.SIDE}),
        }
    ),
    layouts=frozendict(
        {
            # Two shell places side by side on desktop 1, the editor alone on desktop 2.
            Setup.LAPTOP_ONLY: frozendict(
                {SHELL: (Position(1, Role.LAPTOP, LEFT_HALF), Position(1, Role.LAPTOP, RIGHT_HALF)), EDITOR: (Position(2, Role.LAPTOP, FULL),)}
            ),
            Setup.HOME: frozendict({SHELL: (Position(1, Role.MAIN, FULL),)}),
            Setup.WORK: frozendict(
                {
                    EDITOR: (Position(1, Role.SIDE, FULL),),
                    SHELL: (Position(1, Role.ABOVE, LEFT_HALF),),
                    BROWSER: (Position(1, Role.ABOVE, RIGHT_HALF),),
                    CHAT: (Position(1, Role.LAPTOP, FULL),),
                }
            ),
        }
    ),
    dark_when_away=frozendict({Setup.HOME: frozenset({Role.MAIN})}),
)
OVERFLOW = 3
"""The first desktop after the laptop setup's declared ones."""

LAPTOP = Monitor(Rect(0, 0, 1920, 1200), Rect(0, 0, 1920, 1200), primary=True, internal=True)
FOUR_K = Monitor(Rect(1920, -269, 5760, 1891), Rect(1920, -269, 5760, 1891), primary=False, internal=False)
ABOVE = Monitor(Rect(-320, -1440, 2240, 0), Rect(-320, -1440, 2240, 0), primary=False, internal=False)
SIDE = Monitor(Rect(-1760, -1360, -320, 1200), Rect(-1760, -1360, -320, 1200), primary=False, internal=False)


def targets(placement: frozendict[int, Target]) -> dict[int, tuple[int, Rect]]:
    return {handle: (target.desktop, target.rect) for handle, target in placement.items()}


def recognized(setup: Setup, roles: dict[Role, Monitor]) -> Screens:
    return Screens(setup, frozendict((role, monitor.work) for role, monitor in roles.items()), SETUPS.layouts[setup])


def test_setups_match_their_screens_and_assign_work_roles_by_orientation() -> None:
    # Defects: a setup's screen isn't recognized, roles follow the screens'
    # positions instead of their orientation, or an unknown screen set isn't
    # treated as the laptop alone on its own panel.
    assert screens((LAPTOP, FOUR_K), SETUPS) == recognized(Setup.HOME, {Role.LAPTOP: LAPTOP, Role.MAIN: FOUR_K})
    assert screens((SIDE, ABOVE, LAPTOP), SETUPS) == recognized(Setup.WORK, {Role.LAPTOP: LAPTOP, Role.ABOVE: ABOVE, Role.SIDE: SIDE})
    rearranged_side = Monitor(Rect(2240, -2000, 3680, 560), Rect(2240, -2000, 3680, 520), primary=True, internal=False)
    assert screens((LAPTOP, ABOVE, rearranged_side), SETUPS) == recognized(
        Setup.WORK, {Role.LAPTOP: LAPTOP, Role.ABOVE: ABOVE, Role.SIDE: rearranged_side}
    )
    alone = recognized(Setup.LAPTOP_ONLY, {Role.LAPTOP: LAPTOP})
    projector = Monitor(Rect(1920, 0, 3840, 1080), Rect(1920, 0, 3840, 1040), primary=True, internal=False)
    assert screens((LAPTOP, projector), SETUPS) == alone
    assert screens((LAPTOP, FOUR_K, projector), SETUPS) == alone
    docked = Monitor(FOUR_K.area, FOUR_K.work, primary=True, internal=False)
    assert screens((docked,), SETUPS) == recognized(Setup.LAPTOP_ONLY, {Role.LAPTOP: docked})
    assert screens((), SETUPS) is None


def test_only_a_recognized_setups_protected_screens_go_dark_when_away() -> None:
    # Defects: the laptop panel or an unknown screen is darkened, or a protected screen is missed.
    assert dark_when_away((LAPTOP, FOUR_K), SETUPS) == frozenset({FOUR_K})
    assert dark_when_away((LAPTOP, ABOVE, SIDE), SETUPS) == frozenset()
    assert dark_when_away((LAPTOP, FOUR_K, ABOVE), SETUPS) == frozenset()


def test_windows_beyond_an_apps_places_share_its_last_place_and_fewer_leave_places_empty() -> None:
    # Defects: a fourth window is dropped or overlaps the third, or a lone
    # window is stretched over places meant for others.
    alone = screens((LAPTOP,), SETUPS)
    assert alone is not None
    assert targets(place(alone, (Group(SHELL, (3, 6, 7, 8)),), NOWHERE)) == {
        3: (1, Rect(0, 0, 960, 1200)),
        # The half-width laptop place is portrait, so the three stack.
        6: (1, Rect(960, 0, 1920, 400)),
        7: (1, Rect(960, 400, 1920, 800)),
        8: (1, Rect(960, 800, 1920, 1200)),
    }
    assert targets(place(alone, (Group(SHELL, (3,)),), NOWHERE)) == {3: (1, Rect(0, 0, 960, 1200))}


def test_undeclared_apps_keep_their_own_desktops_while_others_come_and_go() -> None:
    # Defects: a surviving app hops down when an earlier one closes, a newcomer
    # doesn't reuse the freed desktop, or a desktop index left from another
    # setup's overflow overrides a declared desktop.
    alone = screens((LAPTOP,), SETUPS)
    assert alone is not None
    first = place(alone, (Group(PYTHON, (1, 2)), Group(NOTEPAD, (3,))), NOWHERE)
    assert targets(first) == {
        1: (OVERFLOW, Rect(0, 0, 960, 1200)),
        2: (OVERFLOW, Rect(960, 0, 1920, 1200)),
        3: (OVERFLOW + 1, Rect(0, 0, 1920, 1200)),
    }
    second = place(alone, (Group(PAINT, (4,)), Group(NOTEPAD, (3,))), first)
    assert targets(second) == {4: (OVERFLOW, Rect(0, 0, 1920, 1200)), 3: (OVERFLOW + 1, Rect(0, 0, 1920, 1200))}
    third = place(alone, (Group(PYTHON, (1, 2)), Group(PAINT, (4,))), first)
    assert targets(third) == {
        1: (OVERFLOW, Rect(0, 0, 960, 1200)),
        2: (OVERFLOW, Rect(960, 0, 1920, 1200)),
        4: (OVERFLOW + 1, Rect(0, 0, 1920, 1200)),
    }
    from_home = frozendict({3: Target(OVERFLOW - 1, Rect(0, 0, 1920, 1200))})
    assert targets(place(alone, (Group(NOTEPAD, (3,)),), from_home)) == {3: (OVERFLOW, Rect(0, 0, 1920, 1200))}


def test_windows_stack_in_a_portrait_region() -> None:
    # Defect: windows sharing a tall region are squeezed side by side.
    portrait = Screens(Setup.LAPTOP_ONLY, frozendict({Role.LAPTOP: Rect(0, 0, 1200, 1920)}), frozendict())
    assert targets(place(portrait, (Group(PYTHON, (1, 2, 3)),), NOWHERE)) == {
        1: (0, Rect(0, 0, 1200, 640)),
        2: (0, Rect(0, 640, 1200, 1280)),
        3: (0, Rect(0, 1280, 1200, 1920)),
    }


def test_pinned_web_apps_are_not_placed_as_ordinary_edge() -> None:
    # Defects: a Teams window is also grouped as Edge, or an unmanaged window
    # keeps its group alive and takes a share of the region.
    edge, teams, dialog = (
        Window(1, "News", "msedge.exe", minimized=False),
        Window(2, "Chat", "msedge.exe", minimized=False),
        Window(3, "Save", "notepad.exe", minimized=False),
    )
    observed = shelf((edge, teams, dialog), {1: "Edge", 2: "Edge.chat.example_/"}, EMPTY_SHELF, {}, test_shell_items.WEB_APPS)
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
    work = screens((LAPTOP, ABOVE, SIDE), SETUPS)
    assert work is not None
    apps = (Group(BROWSER, (5,)), Group(EDITOR, (4,)), Group(SHELL, (3,)), Group(CHAT, (1,)))
    placement = place(work, apps, NOWHERE)
    windows = frozendict((group.app, group.windows) for group in apps)
    # SIDE's editor is leftmost, then ABOVE's shell, then the laptop's chat, then ABOVE's browser.
    assert reading_order(work, windows, placement, 1) == (EDITOR, SHELL, CHAT, BROWSER)
    assert reading_order(work, frozendict(), NOWHERE, 1) == (EDITOR, SHELL, CHAT, BROWSER)
    alone = screens((LAPTOP,), SETUPS)
    assert reading_order(alone, frozendict(), NOWHERE, 1) == (SHELL,)
    assert reading_order(alone, frozendict(), NOWHERE, 2) == (EDITOR,)
    assert reading_order(alone, frozendict(), NOWHERE, OVERFLOW) == ()
    assert reading_order(None, frozendict(), NOWHERE, 1) == ()
