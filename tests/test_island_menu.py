"""The island menu's entries and keyboard navigation."""

from dataclasses import replace

from assistant.island_menu import (
    TILING,
    Chosen,
    Command,
    Dismissed,
    Item,
    Key,
    Letter,
    Live,
    Menu,
    Rule,
    ToolChoice,
    entries,
    label,
    press,
    restores_focus,
    rows,
)
from assistant.meeting_detection import AutomaticStatus
from protocol import Tool


def labels(menu: Menu) -> list[str]:
    return [label(row) for row in rows(menu) if row is not Rule.SEPARATOR]


def selected(outcome: object) -> str:
    match outcome:
        case Menu(selected=int() as index) as menu:
            return label(rows(menu)[index])
        case other:
            raise AssertionError(f"Expected a menu with a selection, got {other}")


def test_running_activities_lead_with_their_stop_and_recording_replaces_its_start() -> None:
    # Defects: a running recording still offers "Record a meeting", or agent work has no Stop in the menu.
    menu = entries(recording="02:05", agent="Reading the request")
    assert menu[:3] == (
        Live("Agent working", "Reading the request", Command.STOP_AGENT),
        Live("Recording", "02:05", Command.STOP_RECORDING),
        Rule.SEPARATOR,
    )
    assert all(label(entry) != "Record a meeting" for entry in menu)
    resting = entries(recording=None, agent=None)
    assert [label(entry) for entry in resting[:3]] == ["Your work canvas", "Your work feed", "Record a meeting"]


def test_tool_rows_derive_hints_without_advertising_inbox_for_the_work_feed() -> None:
    # Defects: the switcher advertises layer/tap labels instead of physical keys,
    # disclosed hints collide with labels, or the feed promises the inbox action.
    resting = entries(recording=None, agent=None)
    assert Item("Your work feed", "chat", Command.FEED) in resting
    assert Item("Switch windows", "search", ToolChoice(Tool.WINDOW_SWITCHER), ". X") in resting
    assert Item("Pause or resume automatic tiling", "", ToolChoice(Tool.TILE_PAUSE)) in TILING.items


def test_arrows_wrap_and_skip_separators() -> None:
    # Defects: the selection lands on a separator, or stops at either end instead of wrapping.
    menu = Menu(entries(recording=None, agent=None), "Layout on")
    assert selected(press(menu, Key.DOWN)) == "Your work canvas"
    assert selected(press(menu, Key.UP)) == "All Workspace controls…"
    outcome: object = menu
    for _ in range(3):
        match outcome:
            case Menu() as current:
                outcome = press(current, Key.DOWN)
            case other:
                raise AssertionError(f"Navigation left the menu: {other}")
    assert selected(outcome) == "Record a meeting"
    match outcome:
        case Menu() as current:
            assert selected(press(current, Key.DOWN)) == "Auto-record Teams: Off"
        case other:
            raise AssertionError(f"Navigation left the menu: {other}")


def test_tiling_discloses_in_place_and_closes_back_onto_its_row() -> None:
    # Defects: Right on tiling does nothing, its items stay after Left or Escape, or
    # closing leaves the selection on a row that no longer exists.
    resting = Menu(entries(recording=None, agent=None), "Layout on")
    menu = replace(resting, selected=next(i for i, row in enumerate(rows(resting)) if row is TILING))
    opened = press(menu, Key.RIGHT)
    assert selected(opened) == "Spread windows across screens"
    match opened:
        case Menu() as disclosed:
            assert labels(disclosed).count("Focus left") == 1
            for key in (Key.LEFT, Key.ESCAPE):
                closed = press(disclosed, key)
                assert selected(closed) == "Window tiling"
                match closed:
                    case Menu() as back:
                        assert "Focus left" not in labels(back)
                    case other:
                        raise AssertionError(f"Closing tiling left the menu: {other}")
        case other:
            raise AssertionError(f"Opening tiling left the menu: {other}")


def test_enter_chooses_escape_dismisses_and_a_letter_jumps_to_the_next_match() -> None:
    # Defects: Enter on a live row doesn't stop it, Escape chooses something, or a
    # repeated letter stays on its first match.
    menu = Menu(entries(recording="02:05", agent=None), "Layout on", selected=0)
    assert press(menu, Key.ENTER) == Chosen(Command.STOP_RECORDING)
    assert press(menu, Key.ESCAPE) is Dismissed.ESCAPE
    first = press(menu, Letter("k"))
    assert selected(first) == "Keyboard map"
    match first:
        case Menu() as current:
            assert selected(press(current, Letter("K"))) == "Keyboard overlay"
        case other:
            raise AssertionError(f"A letter left the menu: {other}")


def test_window_tools_hand_the_keyboard_back_and_workspace_views_keep_it() -> None:
    # Defects: tiling acts on the menu instead of the user's window, or a Workspace
    # view that just opened loses the keyboard to the previous window.
    assert restores_focus(ToolChoice(Tool.TILE_FLOAT)) and restores_focus(Command.TASKBAR)
    assert not restores_focus(Command.CANVAS) and not restores_focus(Command.KEYMAP)


def test_automatic_recording_menu_exposes_saved_state_and_connection_failure() -> None:
    # Defect: the menu hides the opt-in, advertises monitoring after a connection
    # failure, or dispatches its toggle as a manual recording start.
    for status, text in (
        (AutomaticStatus.OFF, "Auto-record Teams: Off"),
        (AutomaticStatus.READY, "Auto-record Teams: On"),
        (AutomaticStatus.UNAVAILABLE, "Auto-record Teams: Check connection"),
    ):
        menu = Menu(entries(recording=None, agent=None, automatic=status), "Layout on")
        index = next(i for i, entry in enumerate(rows(menu)) if label(entry) == text)
        assert press(replace(menu, selected=index), Key.ENTER) == Chosen(Command.AUTOMATIC_RECORDING)
    assert restores_focus(Command.AUTOMATIC_RECORDING)
