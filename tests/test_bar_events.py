"""The bar's decisions, as values: opening and closing the menu, and what a publication changes."""

from dataclasses import replace
from datetime import date

from desktop_ui.bar_events import (
    BarModel,
    Deactivated,
    DictationShown,
    Expand,
    Opening,
    Paged,
    PanelPressed,
    Picked,
    Pressed,
    Release,
    Render,
    SetMute,
    Survey,
    menu,
    transition,
)
from desktop_ui.island_menu import Applied, Calendar, Command, Key, Page, Panel, Toggle, label, press
from desktop_ui.island_model import Action
from desktop_ui.month import Month
from tests import test_bar_specs
from winapi.machine_status import Speakers


def model() -> BarModel:
    return BarModel(test_bar_specs.SPEC)


def test_opening_the_menu_remembers_the_keyboard_only_when_the_island_was_closed() -> None:
    # Defect: reopening the open menu forgets who had the keyboard first.
    closed = model()
    _, effects = transition(closed, Pressed(Action.OPEN_MENU))
    assert tuple(effects) == (Expand(menu(closed, Panel.WORKSPACE), remember=True), Survey(listing=False))
    opened, _ = transition(closed, Opening(menu(closed, Panel.WORKSPACE), 42))
    assert opened.menu_target == 42
    _, again = transition(opened, Pressed(Action.OPEN_MENU))
    assert Expand(menu(replace(opened, opened=None), Panel.WORKSPACE), remember=False) in tuple(again)


def test_a_reading_opens_its_panel_switches_from_another_and_closes_its_own() -> None:
    # Defects: pressing the open panel's reading opens it again instead of closing, switching
    # panels forgets who had the keyboard, or a closed bar still opens.
    closed = model()
    _, opening = transition(closed, PanelPressed(Panel.SOUND, 2))
    assert tuple(opening) == (Expand(replace(menu(closed, Panel.SOUND), anchor=2), remember=True), Survey(listing=False))
    sound, _ = transition(closed, Opening(menu(closed, Panel.SOUND), 42))
    _, switching = transition(sound, PanelPressed(Panel.WORKSPACE))
    assert tuple(switching) == (Expand(menu(sound, Panel.WORKSPACE), remember=False), Survey(listing=False))
    _, closing = transition(sound, PanelPressed(Panel.SOUND))
    assert Release(42) in tuple(closing)
    _, ignored = transition(replace(closed, closed=True), PanelPressed(Panel.SOUND))
    assert tuple(ignored) == ()


def test_losing_the_keyboard_closes_without_taking_it_back_but_escape_returns_it() -> None:
    # Defect: another window taking focus is fought for, or closing with the menu
    # key leaves the keyboard with Workspace.
    opened, _ = transition(model(), Opening(menu(model(), Panel.WORKSPACE), 42))
    lost, deactivated = transition(opened, Deactivated())
    assert lost.opened is None and tuple(deactivated) == (Release(0), Survey(listing=False), Render())
    _, closed = transition(opened, Pressed(Action.CLOSE_MENU))
    assert Release(42) in tuple(closed)


def test_an_unchanged_publication_does_not_render_again() -> None:
    # Defect: every repeated publication relays the bar out, or a real change doesn't.
    dictating, effects = transition(model(), DictationShown(active=True))
    assert dictating.dictating and tuple(effects) == (Render(),)
    _, repeated = transition(dictating, DictationShown(active=True))
    assert tuple(repeated) == ()


def test_mute_flips_the_speakers_and_shows_at_once() -> None:
    # Defects: pressing Mute on muted speakers mutes them again instead of unmuting,
    # or the toggle and the capsule wait for the next reading to show it.
    for before, after in ((Speakers.AUDIBLE, True), (Speakers.MUTED, False)):
        heard = replace(model(), seen=replace(model().seen, system=replace(model().seen.system, speakers=before)))
        sound = menu(heard, Panel.SOUND)
        toggle = next(index for index, cell in enumerate(sound.cells) if isinstance(cell.entry, Toggle))
        assert press(replace(sound, selected=toggle), Key.ENTER) == Applied(Command.MUTE)
        flipped, effects = transition(replace(heard, opened=sound), Picked(toggle))
        assert SetMute(muted=after) in tuple(effects)
        shown = next(cell.entry for cell in menu(flipped, Panel.SOUND).cells if isinstance(cell.entry, Toggle))
        assert shown.on is after, label(shown)


def test_the_calendar_turns_from_the_month_it_shows_and_returns_to_today() -> None:
    # Defects: each arrow turns from today's month rather than the one shown, the turned
    # month is lost on the next render, another panel inherits it, or the heading
    # doesn't bring today back.
    dated = replace(model(), seen=replace(model().seen, ambient=replace(model().seen.ambient, today=date(2026, 12, 31))))

    def shown(state: BarModel) -> Month:
        assert state.opened is not None
        calendar = next(cell.entry for cell in menu(state, state.opened.panel).cells if isinstance(cell.entry, Calendar))
        return calendar.month

    opened = replace(dated, opened=menu(dated, Panel.CALENDAR))
    assert shown(opened) == Month(2026, 12)
    once, _ = transition(opened, Paged(1))
    twice, _ = transition(once, Paged(1))
    assert shown(twice) == Month(2027, 2)
    calendar = menu(twice, Panel.CALENDAR)
    assert press(replace(calendar, selected=0), Key.LEFT) == Applied(Page(-1))
    assert menu(twice, Panel.SOUND).month is None
    back, _ = transition(twice, Picked(0))
    assert shown(back) == Month(2026, 12)


def test_networks_are_read_only_while_their_panel_is_open() -> None:
    # Defects: the worker keeps scanning after the panel closes or switches away, or
    # opening the Wi-Fi panel never starts reading the networks in range.
    _, opening = transition(model(), PanelPressed(Panel.NETWORK))
    assert Survey(listing=True) in tuple(opening)
    listing, _ = transition(model(), Opening(menu(model(), Panel.NETWORK), 42))
    _, switching = transition(listing, PanelPressed(Panel.SOUND))
    assert Survey(listing=False) in tuple(switching)
    _, closing = transition(listing, PanelPressed(Panel.NETWORK))
    assert Survey(listing=False) in tuple(closing)
