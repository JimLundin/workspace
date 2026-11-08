"""The navigation log: one entry per change of the focused window, whatever caused it."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from desktop_ui.navigation import AppKey, CycleApp, Focus, JumpDesktop, Launch, Navigated, Source, Switch, World
from desktop_ui.navigation_log import (
    ENTRY,
    NAVIGATION_LOG,
    ROTATE_BYTES,
    START,
    Arrival,
    Entry,
    Focused,
    Moment,
    Tracker,
    append,
    arrived,
    navigated,
    noticed,
    seen,
    settled,
)
from desktop_ui.shell_items import PinnedApp
from desktop_ui.window_layout import CODE, EDGE, NOWHERE, TERMINAL, Program, Setup
from protocol import App, Installed
from winapi.win_events import CaptureStart, SwitchEnd, SwitchStart

CLOCK = datetime(2026, 11, 4, 9, 30, tzinfo=timezone(timedelta(hours=1)))
WORLD = World(
    3,
    0,
    1,
    frozendict({TERMINAL: (1,), CODE: (2,), PinnedApp.TEAMS: (3,), EDGE: (4,)}),
    frozendict({1: 0, 2: 0, 3: 0, 4: 1}),
    NOWHERE,
    (),
    None,
)
TERMINAL_START = Installed("windowsterminal.exe", "wt.exe")
TERMINAL_KEY = AppKey(App("terminal", TERMINAL_START), Source.KEY)


def at(seconds: float) -> Moment:
    return Moment(100 + seconds, CLOCK + timedelta(seconds=seconds), Setup.HOME)


WORLD_APPS: frozendict[int, Program | PinnedApp | None] = frozendict({1: TERMINAL, 2: CODE, 3: PinnedApp.TEAMS, 4: EDGE, 9: None})


def came(window: int, desktop: int = 0, *, held: bool = False) -> Arrival:
    return Arrival(window, WORLD_APPS[window], desktop, held=held)


def front(window: int) -> Tracker:
    """`window` came to the front at 0 s."""
    return Tracker(Focused(window, WORLD_APPS[window], 0, 100.0), None, None, None)


def run(tracker: Tracker, *steps: tuple[float, Arrival]) -> tuple[Tracker, tuple[Entry, ...]]:
    logged: tuple[Entry, ...] = ()
    for seconds, change in steps:
        tracker, entries = arrived(tracker, change, at(seconds))
        logged += entries
    return tracker, logged


def summary(entries: tuple[Entry, ...]) -> tuple[tuple[str, str, str | None, str | None, int | None], ...]:
    return tuple((entry.navigation, entry.cause, entry.from_app, entry.to_app, entry.dwell_ms) for entry in entries)


def test_workspace_navigation_and_its_foreground_echo_are_one_entry() -> None:
    """The toolbar's button may still be down when its window comes forward; the next change is the user's own."""
    tracker, first = navigated(front(1), (Focus(2), Navigated(CycleApp(CODE, Source.TOOLBAR), 0, 0, TERMINAL, CODE)), at(4))
    _, later = run(tracker, (4.2, came(2, held=True)), (4.5, came(3)))

    assert summary((*first, *later)) == (
        ("cycle_app", "toolbar", "windowsterminal.exe", "code.exe", 4000),
        ("external", "other", "code.exe", "teams", 300),
    )


def test_the_shell_passing_focus_during_a_desktop_switch_is_not_a_navigation() -> None:
    decided = (Switch(1, 4), Navigated(JumpDesktop(1, Source.KEY), 0, 1, TERMINAL, EDGE))
    tracker, first = navigated(front(1), decided, at(1))
    tracker, later = run(tracker, (1.1, came(2)), (1.3, came(4, 1)), (5, came(1)))

    assert summary((*first, *later)) == (
        ("jump_desktop", "key", "windowsterminal.exe", "msedge.exe", 1000),
        ("external", "other", "msedge.exe", "windowsterminal.exe", 3700),
    )
    assert (first[0].from_desktop, first[0].to_desktop, first[0].other_desktop) == (0, 1, True)


def test_a_click_during_a_workspace_navigation_is_still_logged() -> None:
    tracker, _ = navigated(front(1), (Focus(2), Navigated(CycleApp(CODE, Source.TOOLBAR), 0, 0, TERMINAL, CODE)), at(1))
    _, logged = run(tracker, (1.1, came(3, held=True)))

    assert summary(logged) == (("external", "mouse", "windowsterminal.exe", "teams", 1100),)


def test_a_launch_is_echoed_by_its_application_s_first_window() -> None:
    decided = (Launch(TERMINAL_START), Navigated(TERMINAL_KEY, 0, 0, CODE, TERMINAL, launched=True))
    tracker, first = navigated(front(2), decided, at(2))
    _, later = run(tracker, (8, came(1)))

    assert summary((*first, *later)) == (("app_key", "key", "code.exe", "windowsterminal.exe", 2000),)
    assert first[0].launched


def test_focusing_the_window_already_in_front_expects_no_change() -> None:
    tracker, _ = navigated(front(1), (Focus(1), Navigated(CycleApp(TERMINAL, Source.TOOLBAR), 0, 0, TERMINAL, TERMINAL)), at(1))
    _, logged = run(tracker, (1.5, came(3)))

    assert summary(logged) == (("external", "other", "windowsterminal.exe", "teams", 1500),)


def test_an_expired_navigation_no_longer_absorbs_changes() -> None:
    tracker, _ = navigated(front(1), (Focus(2), Navigated(CycleApp(CODE, Source.TOOLBAR), 0, 0, TERMINAL, CODE)), at(1))
    _, logged = run(tracker, (4, came(3)))

    assert summary(logged) == (("external", "other", "windowsterminal.exe", "teams", 4000),)


def test_external_changes_are_classified_by_the_input_just_before_them() -> None:
    tracker, clicked = run(front(1), (1, came(2, held=True)))
    tracker = noticed(tracker, CaptureStart(100 + 2.8))
    tracker, captured = run(tracker, (3, came(3)))
    tracker = noticed(tracker, CaptureStart(100 + 3))
    _, other = run(tracker, (6, came(1)))

    assert summary((*clicked, *captured, *other)) == (
        ("external", "mouse", "windowsterminal.exe", "code.exe", 1000),
        ("external", "mouse", "code.exe", "teams", 2000),
        ("external", "other", "teams", "windowsterminal.exe", 3000),
    )


def test_alt_tab_is_one_entry_from_where_it_started_whichever_order_its_events_arrive() -> None:
    switching = noticed(front(1), SwitchStart(100 + 2))
    host, opening = run(switching, (2.05, came(9)))
    after, choice_after_close = run(noticed(host, SwitchEnd(100 + 3)), (3.1, came(3)))
    before, _ = run(host, (2.9, came(3)))
    _, choice_before_close = settled(noticed(before, SwitchEnd(100 + 3)), at(4))

    assert opening == ()
    assert summary(choice_after_close) == (("external", "alt_tab", "windowsterminal.exe", "teams", 3100),)
    assert summary(choice_before_close) == (("external", "alt_tab", "windowsterminal.exe", "teams", 4000),)
    assert after.switcher is None


def test_a_cancelled_alt_tab_is_not_a_navigation_and_keeps_the_dwell() -> None:
    switching, _ = run(noticed(front(1), SwitchStart(100 + 2)), (2.05, came(9)))
    tracker, cancelled = run(noticed(switching, SwitchEnd(100 + 3)), (3.1, came(1)))
    _, later = run(tracker, (10, came(2)))

    assert cancelled == ()
    assert summary(later) == (("external", "other", "windowsterminal.exe", "code.exe", 10000),)


def test_dwell_is_the_time_between_consecutive_changes_and_unknown_before_the_first() -> None:
    _, logged = run(seen(START, WORLD), (5, came(2)), (12.5, came(3)), (12.75, came(1)))

    assert tuple(entry.dwell_ms for entry in logged) == (None, 7500, 250)


def test_an_entry_is_one_line_of_app_identities_never_titles(tmp_path: Path) -> None:
    _, logged = run(front(1), (1.5, came(4, 1, held=True)))
    path = tmp_path / NAVIGATION_LOG.name
    append(logged, path)

    line = path.read_text(encoding="utf-8")
    assert line == (
        '{"time":"2026-11-04T09:30:01.500000+01:00","setup":"home","navigation":"external","cause":"mouse",'
        '"from_app":"windowsterminal.exe","to_app":"msedge.exe","from_desktop":0,"to_desktop":1,'
        '"other_desktop":true,"launched":false,"dwell_ms":1500}\n'
    )
    assert ENTRY.validate_json(line) == logged[0]


def test_a_full_log_rotates_to_one_previous_file(tmp_path: Path) -> None:
    _, logged = run(front(1), (1, came(2)))
    path = tmp_path / "navigation.jsonl"
    with path.open("wb") as full:
        full.truncate(ROTATE_BYTES)
    append(logged, path)

    assert (tmp_path / "navigation.1.jsonl").stat().st_size == ROTATE_BYTES
    assert ENTRY.validate_json(path.read_text(encoding="utf-8")) == logged[0]
