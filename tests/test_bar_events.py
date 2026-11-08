"""The bar's decisions, as values: opening and closing the island, and what a publication changes."""

from dataclasses import replace

from contracts import agent_session
from contracts.agent_session import Begin, Session
from desktop_ui import ui_spec
from desktop_ui.agent_progress import Phase, phases
from desktop_ui.bar_events import (
    BarModel,
    Deactivated,
    DictationShown,
    Expand,
    InboxRequested,
    Opening,
    Pressed,
    Release,
    Render,
    RequestsShown,
    SelectRequest,
    Showing,
    menu,
    transition,
)
from desktop_ui.island_model import Action
from tests.agent_requests import asked


def model() -> BarModel:
    return BarModel(ui_spec.bar_specs(reload=False))


def test_opening_the_menu_remembers_the_keyboard_only_when_the_island_was_closed() -> None:
    # Defect: reopening from an open request forgets who had the keyboard first,
    # or the request panel keeps a selection the menu replaced.
    closed = model()
    _, effects = transition(closed, Pressed(Action.OPEN_MENU))
    assert tuple(effects) == (SelectRequest(None), Expand(menu(closed), remember=True))
    opened, _ = transition(closed, Opening(menu(closed), 42))
    assert opened.menu_target == 42
    _, again = transition(opened, Pressed(Action.OPEN_MENU))
    assert tuple(again)[-1] == Expand(menu(replace(opened, opened=None)), remember=False)


def test_losing_the_keyboard_closes_without_taking_it_back_but_escape_returns_it() -> None:
    # Defect: another window taking focus is fought for, or closing with the menu
    # key leaves the keyboard with Workspace.
    opened, _ = transition(model(), Opening(menu(model()), 42))
    lost, deactivated = transition(opened, Deactivated())
    assert lost.opened is None and tuple(deactivated) == (SelectRequest(None), Release(0), Render())
    _, closed = transition(opened, Pressed(Action.CLOSE_MENU))
    assert Release(42) in tuple(closed)


def test_an_unchanged_publication_does_not_render_again() -> None:
    # Defect: every repeated publication relays the bar out, or a real change doesn't.
    dictating, effects = transition(model(), Showing(DictationShown(active=True)))
    assert dictating.dictating and tuple(effects) == (Render(),)
    _, repeated = transition(dictating, Showing(DictationShown(active=True)))
    assert tuple(repeated) == ()


def question(text: str, at: float) -> Phase:
    """The one phase of a session whose work asks `text`."""
    session = agent_session.transition(Session(identity="review"), Begin("Check the budget", 1))
    (phase,) = phases(agent_session.transition(session, asked("sheet", text, "Revenue contains the approved figures.", at)))
    return phase


def test_one_waiting_question_opens_in_place_from_the_bell() -> None:
    # Defect: a single question opens the bell's list, or a canvas, instead of
    # expanding the island on that request with the request panel on it.
    asking = question("Which sheet should I use?", 3)
    _, effects = transition(model(), InboxRequested((asking,)))
    assert tuple(effects) == (Expand(asking, remember=True), SelectRequest(asking.request))
    unchanged, nothing = transition(model(), InboxRequested(()))
    assert unchanged == model() and tuple(nothing) == ()


def test_an_open_request_follows_its_phase_and_closes_when_it_is_gone() -> None:
    # Defect: work asking again leaves the island on the stale request, or a
    # request the session no longer has stays open.
    first = question("Which sheet should I use?", 3)
    opened, _ = transition(model(), Opening(first, 42))
    again = replace(first, turn=question("Which tab should I use?", 5).turn)
    following, effects = transition(opened, RequestsShown((again,)))
    assert following.opened == again and tuple(effects) == (SelectRequest(again.request), Render())
    _, repeated = transition(following, RequestsShown((again,)))
    assert tuple(repeated) == ()
    closed, _ = transition(following, RequestsShown(()))
    assert closed.opened is None
