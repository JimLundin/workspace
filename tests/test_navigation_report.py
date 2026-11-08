"""The navigation report: costs by cause, round trips, and layout changes replayed against the logged history."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from desktop_ui.navigation_log import ENTRY, Cause, Entry, SetupName
from desktop_ui.shell_items import PinnedApp
from desktop_ui.window_layout import CODE, EDGE, FULL, LEFT_HALF, LEFT_TWO_THIRDS, RIGHT_HALF, RIGHT_THIRD, TERMINAL, App, Position, Role, Setup
from scripts.navigation_analysis import (
    Exchange,
    History,
    Log,
    Move,
    Pair,
    Suggestion,
    edits,
    moves,
    pairs,
    read,
    selected,
    suggested,
    totals,
)

CLOCK = datetime(2026, 11, 4, 9, 30, tzinfo=timezone(timedelta(hours=1)))
HOME: frozendict[App, Position] = frozendict(
    {
        TERMINAL: Position(0, Role.MAIN, LEFT_TWO_THIRDS),
        CODE: Position(0, Role.MAIN, RIGHT_THIRD),
        PinnedApp.TEAMS: Position(0, Role.LAPTOP, FULL),
        EDGE: Position(1, Role.MAIN, LEFT_HALF),
        PinnedApp.OUTLOOK: Position(1, Role.MAIN, RIGHT_HALF),
    }
)
"""A fixed two-desktop home layout, so the replay arithmetic doesn't follow edits to `LAYOUTS`."""


def entry(cause: Cause, apps: tuple[str | None, str | None], desktops: tuple[int, int]) -> Entry:
    return Entry(
        CLOCK,
        "home",
        "app_key",
        cause,
        apps[0],
        apps[1],
        desktops[0],
        desktops[1],
        other_desktop=desktops[0] != desktops[1],
        launched=False,
        dwell_ms=60_000,
    )


def test_each_cause_costs_its_effort_plus_a_desktop_switch_and_a_chord_that_moved_nothing_is_wasted() -> None:
    # Defects: a weight applied to the wrong cause, the switch added to unprompted
    # focus changes, or a zoom or a cycle within one app counted as wasted.
    logged = (
        entry("key", ("code.exe", "windowsterminal.exe"), (0, 0)),
        entry("key", ("code.exe", "msedge.exe"), (0, 1)),
        entry("alt_tab", ("code.exe", "teams"), (0, 0)),
        entry("mouse", ("code.exe", "outlook"), (0, 1)),
        replace(entry("other", ("code.exe", "notepad.exe"), (0, 2)), navigation="zoom"),
        replace(entry("toolbar", ("code.exe", "excel.exe"), (0, 0)), navigation="cycle_app"),
        replace(entry("key", ("code.exe", "code.exe"), (0, 0)), navigation="spatial_focus"),
        replace(entry("key", ("code.exe", "code.exe"), (0, 0)), navigation="zoom"),
        replace(entry("key", ("code.exe", "code.exe"), (0, 0)), navigation="cycle_app"),
    )
    total = totals(logged)
    assert (total.cost, total.switches, total.wasted, total.navigations) == (1 + 2 + 3 + 5 + 0 + 4 + 1 + 1 + 1, 3, 1, 9)


def test_a_window_in_front_over_four_hours_is_left_out_of_the_rates() -> None:
    away = Entry(CLOCK, "home", "app_key", "key", "code.exe", "msedge.exe", 0, 1, other_desktop=True, launched=False, dwell_ms=5 * 3_600_000)
    total = totals((away, entry("key", ("msedge.exe", "code.exe"), (1, 0))))
    assert (total.navigations, total.cost, total.hours, total.away) == (1, 2, 1 / 60, 1)


def test_round_trips_combine_both_directions_and_skip_moves_within_one_app() -> None:
    logged = (
        entry("key", ("windowsterminal.exe", "msedge.exe"), (0, 1)),
        entry("mouse", ("msedge.exe", "windowsterminal.exe"), (1, 0)),
        entry("key", ("windowsterminal.exe", "msedge.exe"), (0, 1)),
        entry("key", ("windowsterminal.exe", "code.exe"), (0, 0)),
        replace(entry("key", ("code.exe", "code.exe"), (0, 0)), navigation="cycle_app"),
        entry("mouse", ("code.exe", None), (0, 0)),
    )
    assert pairs(logged) == (
        Pair(("msedge.exe", "windowsterminal.exe"), 3, 2 + 5 + 2, 3),
        Pair(("(unknown)", "code.exe"), 1, 4, 0),
        Pair(("code.exe", "windowsterminal.exe"), 1, 1, 0),
    )


def test_moving_teams_onto_edges_desktop_rederives_every_desktop_switch() -> None:
    # Defects: the replay keeping the logged other_desktop, moving only one end of a
    # navigation, or not assuming the chord for a chorded target reached by mouse.
    history = History(
        (
            entry("key", ("msedge.exe", "teams"), (1, 0)),
            entry("key", ("teams", "msedge.exe"), (0, 1)),
            entry("mouse", ("msedge.exe", "teams"), (1, 0)),
            entry("key", ("teams", "code.exe"), (0, 0)),
        ),
        frozenset({"teams", "msedge.exe", "code.exe"}),
    )
    teams = Move(PinnedApp.TEAMS, Position(1, Role.LAPTOP, FULL))
    assert suggested(history, HOME, teams) == Suggestion(teams, 2 + 2 + 2 + 1, 1 + 1 + 1 + 2)
    assert tuple(edits(Setup.HOME, HOME, teams)) == (
        "LAYOUTS[Setup.HOME][PinnedApp.TEAMS]: Position(0, Role.LAPTOP, FULL) -> Position(1, Role.LAPTOP, FULL)",
    )


def test_a_change_that_overlaps_two_apps_is_rejected_and_a_move_falls_back_to_a_free_monitor() -> None:
    history = History((entry("key", ("windowsterminal.exe", "msedge.exe"), (0, 1)),), frozenset())
    assert suggested(history, HOME, Move(EDGE, Position(0, Role.MAIN, LEFT_HALF))) is None
    assert tuple(moves(HOME, TERMINAL, 1)) == (Move(TERMINAL, Position(1, Role.LAPTOP, FULL)),)
    assert tuple(moves(HOME, EDGE, 0)) == ()
    assert suggested(history, HOME, Exchange(PinnedApp.TEAMS, EDGE)) == Suggestion(Exchange(PinnedApp.TEAMS, EDGE), 2, 1)


def test_malformed_lines_are_counted_and_skipped() -> None:
    valid = ENTRY.dump_json(entry("key", ("code.exe", "msedge.exe"), (0, 1))).decode()
    log = read((valid, valid[:-5], '{"time": "2026-11-04T09:30:00+01:00"}', valid.replace("+01:00", ""), "", "[]"))
    assert log == Log((entry("key", ("code.exe", "msedge.exe"), (0, 1)),), 4)


def test_selection_keeps_the_window_and_the_asked_setup() -> None:
    def at(days: int, setup: SetupName | None) -> Entry:
        return Entry(CLOCK - timedelta(days=days), setup, "app_key", "key", "a", "b", 0, 0, other_desktop=False, launched=False, dwell_ms=1)

    logged = (at(8, "home"), at(6, "home"), at(1, "work"), at(0, None))
    since = CLOCK - timedelta(days=7)
    assert selected(logged, since, Setup.HOME) == (at(6, "home"),)
    assert selected(logged, since, None) == (at(6, "home"), at(1, "work"), at(0, None))
