"""The tray menu's spec: what it may say, and that it keeps every action."""

from dataclasses import replace

from desktop_ui.desktop_controls import Menu, MenuState, TrayAction, menu_items, tray_problems
from desktop_ui.spec.tray import TRAY
from protocol import LayoutState


def test_the_shipped_tray_offers_every_action_once() -> None:
    # Defect: an edit to the tray spec drops an action (Quit, Restart desktop), leaving no way to reach it.
    actions = [item.action for item in TRAY.items if isinstance(item, TrayAction)]
    assert sorted(actions, key=lambda action: action.value) == sorted(Menu, key=lambda action: action.value)
    assert tray_problems(TRAY) == ()


def test_tray_edits_that_misword_or_repeat_an_item_are_refused() -> None:
    # Defect: a label that hides the layout's state, an unlabelled item, or an item
    # listed twice reaches the menu instead of being reported.
    assert "meeting takes no label: its words follow state" in tray_problems(replace(TRAY, items=(TrayAction(Menu.MEETING, "Record"),)))
    assert "quit needs a label" in tray_problems(replace(TRAY, items=(TrayAction(Menu.QUIT),)))
    twice = replace(TRAY, items=(*TRAY.items, TrayAction(Menu.QUIT, "Quit")))
    assert "quit appears more than once" in tray_problems(twice)


def test_the_tray_words_its_items_from_the_spec() -> None:
    # Defect: the menu shows the code's old words instead of the spec's.
    renamed = replace(
        TRAY, items=tuple(replace(item, label="Usage") if isinstance(item, TrayAction) and item.action is Menu.USAGE else item for item in TRAY.items)
    )
    state = MenuState(layout=LayoutState.ON, overlay_enabled=False, capturing=False)
    assert any(item.text == "Usage" for item in menu_items(state, renamed))
