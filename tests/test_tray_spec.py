"""The tray menu's spec: what it may say, and that it keeps every action."""

from pathlib import Path

from assistant.control_policy import TRAY_FILE, Menu, MenuState, TrayAction, menu_items, tray, tray_spec
from desktop_ui.ui_spec import SHIPPED, SpecError
from protocol import LayoutState

TRAY = (SHIPPED / TRAY_FILE).read_text(encoding="utf-8")


def refusal(tmp_path: Path, text: str) -> str:
    tmp_path.mkdir(parents=True)
    (tmp_path / TRAY_FILE).write_text(text, encoding="utf-8")
    try:
        tray_spec(tmp_path)
    except SpecError as error:
        return str(error)
    raise AssertionError("The tray spec was accepted.")


def test_the_shipped_tray_offers_every_action_once() -> None:
    # Defect: an edit to the tray spec drops an action (Quit, Undo), leaving no way to reach it.
    actions = [item.action for item in tray_spec().items if isinstance(item, TrayAction)]
    assert sorted(actions, key=lambda action: action.value) == sorted(Menu, key=lambda action: action.value)


def test_tray_edits_that_misword_repeat_or_misname_an_item_are_refused(tmp_path: Path) -> None:
    # Defect: a label that hides the layout's state, an item listed twice, or an
    # unknown action reaches the menu instead of being reported.
    stated = TRAY.replace('action = "meeting"\n', 'action = "meeting"\nlabel = "Record"\n')
    assert "meeting takes no label" in refusal(tmp_path / "stated", stated)
    assert "quit needs a label" in refusal(tmp_path / "bare", TRAY.replace('label = "Quit Workspace"\n', ""))
    assert "quit appears more than once" in refusal(tmp_path / "twice", TRAY + '\n[[items]]\naction = "quit"\nlabel = "Quit"\n')
    assert refusal(tmp_path / "unknown", TRAY.replace('action = "logs"', 'action = "log"')).startswith("tray.toml: items.")


def test_a_broken_tray_edit_opens_the_last_good_menu(tmp_path: Path) -> None:
    # Defect: a broken edit leaves the tray with no menu, so Quit and Undo are unreachable.
    live, kept = tmp_path / "live", tmp_path / "kept"
    live.mkdir()
    (live / TRAY_FILE).write_text(TRAY.replace('label = "Usage report"', 'label = "Usage"'), encoding="utf-8")
    assert tray(live, kept)[1] is None
    (live / TRAY_FILE).write_text(TRAY.replace('action = "logs"', 'action = "log"'), encoding="utf-8")
    spec, problem = tray(live, kept)
    state = MenuState(layout=LayoutState.ON, overlay_enabled=False, agent_running=False, capturing=False)
    assert problem is not None and any(item.text == "Usage" for item in menu_items(state, spec))
