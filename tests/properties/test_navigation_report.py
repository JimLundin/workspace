"""Replaying the logged history against the current layout saves nothing, whatever the log says."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from hypothesis import strategies

from desktop_ui.navigation_log import Cause, Entry
from desktop_ui.navigation_report import History, Move, suggested
from desktop_ui.window_layout import LAYOUTS, App, Setup
from tests.properties.generation import cases, property_test

APPS = ("windowsterminal.exe", "code.exe", "msedge.exe", "outlook", "teams", "notepad.exe", None)
CAUSES: tuple[Cause, ...] = ("key", "pager", "scroll", "toolbar", "alt_tab", "mouse", "other")
CLOCK = datetime(2026, 11, 4, 9, 30, tzinfo=timezone(timedelta(hours=1)))


@dataclass(frozen=True, slots=True)
class ReplayCase:
    setup: Setup
    app: App
    history: History


def logged(draw: strategies.DrawFn) -> Entry:
    desktops = strategies.sampled_from((None, 0, 1, 2, 3, 4))
    return Entry(
        CLOCK,
        "home",
        "external",
        draw(strategies.sampled_from(CAUSES)),
        draw(strategies.sampled_from(APPS)),
        draw(strategies.sampled_from(APPS)),
        draw(desktops),
        draw(desktops),
        # Logged desktops needn't match the layout or each other.
        other_desktop=draw(strategies.booleans()),
        launched=False,
        dwell_ms=None,
    )


def replay_cases(draw: strategies.DrawFn) -> ReplayCase:
    setup = draw(strategies.sampled_from(tuple(Setup)))
    app = draw(strategies.sampled_from(tuple(LAYOUTS[setup])))
    entries = tuple(logged(draw) for _ in range(draw(strategies.integers(0, 12))))
    chorded = frozenset(name for name in APPS if name is not None and draw(strategies.booleans()))
    return ReplayCase(setup, app, History(entries, chorded))


@property_test(cases(replay_cases))
def test_a_candidate_identical_to_the_current_layout_saves_nothing(case: ReplayCase) -> None:
    # Defect: the before cost taken from the logged desktops or causes rather than
    # replayed under the same model as the candidate, so every suggestion carries a bias.
    layout = LAYOUTS[case.setup]
    suggestion = suggested(case.history, layout, Move(case.app, layout[case.app]))
    assert suggestion is not None
    assert suggestion.before == suggestion.after
