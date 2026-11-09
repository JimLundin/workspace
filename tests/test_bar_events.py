"""The bar's decisions, as values: opening and closing the menu, and what a publication changes."""

from dataclasses import replace

from desktop_ui.bar_events import (
    BarModel,
    Deactivated,
    DictationShown,
    Expand,
    Opening,
    Pressed,
    Release,
    Render,
    menu,
    transition,
)
from desktop_ui.island_model import Action


def model() -> BarModel:
    return BarModel()


def test_opening_the_menu_remembers_the_keyboard_only_when_the_island_was_closed() -> None:
    # Defect: reopening the open menu forgets who had the keyboard first.
    closed = model()
    _, effects = transition(closed, Pressed(Action.OPEN_MENU))
    assert tuple(effects) == (Expand(menu(closed), remember=True),)
    opened, _ = transition(closed, Opening(menu(closed), 42))
    assert opened.menu_target == 42
    _, again = transition(opened, Pressed(Action.OPEN_MENU))
    assert tuple(again)[-1] == Expand(menu(replace(opened, opened=None)), remember=False)


def test_losing_the_keyboard_closes_without_taking_it_back_but_escape_returns_it() -> None:
    # Defect: another window taking focus is fought for, or closing with the menu
    # key leaves the keyboard with Workspace.
    opened, _ = transition(model(), Opening(menu(model()), 42))
    lost, deactivated = transition(opened, Deactivated())
    assert lost.opened is None and tuple(deactivated) == (Release(0), Render())
    _, closed = transition(opened, Pressed(Action.CLOSE_MENU))
    assert Release(42) in tuple(closed)


def test_an_unchanged_publication_does_not_render_again() -> None:
    # Defect: every repeated publication relays the bar out, or a real change doesn't.
    dictating, effects = transition(model(), DictationShown(active=True))
    assert dictating.dictating and tuple(effects) == (Render(),)
    _, repeated = transition(dictating, DictationShown(active=True))
    assert tuple(repeated) == ()
