"""The controls menu's grid and its keyboard navigation."""

from dataclasses import replace

from assistant.meeting_detection import AutomaticStatus
from desktop_ui.island_layout import MENU_WIDTH, tiles
from desktop_ui.island_menu import (
    TILING,
    Applied,
    Chosen,
    Command,
    Controls,
    Dismissed,
    Face,
    Item,
    Key,
    Letter,
    Live,
    Menu,
    Outcome,
    Slider,
    Toggle,
    ToolChoice,
    Volume,
    entries,
    label,
    press,
    restores_focus,
    shown,
)
from protocol import Tool

RESTING = Controls(None, None, sound=Slider("Sound", 0.4, muted=False))


def at(menu: Menu, name: str) -> Menu:
    return replace(menu, selected=next(index for index, cell in enumerate(shown(menu)) if label(cell.entry) == name))


def selected(outcome: Outcome) -> str:
    match outcome:
        case Menu(selected=int() as index) as menu:
            return label(shown(menu)[index].entry)
        case other:
            raise AssertionError(f"Expected a menu with a selection, got {other}")


def opened(outcome: Outcome) -> Menu:
    match outcome:
        case Menu() as menu:
            return menu
        case other:
            raise AssertionError(f"Expected the menu to stay open, got {other}")


def test_running_activities_lead_as_cards_and_recording_replaces_its_start() -> None:
    # Defects: a running recording still offers "Record a meeting", or agent work has no Stop in the menu.
    cells = entries(Controls("02:05", "Reading the request"))
    assert [(cell.entry, cell.face) for cell in cells[:2]] == [
        (Live("Agent working", "Reading the request", Command.STOP_AGENT), Face.CARD),
        (Live("Recording", "02:05", Command.STOP_RECORDING), Face.CARD),
    ]
    assert all(label(cell.entry) != "Record a meeting" for cell in cells)
    assert any(label(cell.entry) == "Record a meeting" for cell in entries(RESTING))


def test_every_grid_fits_the_menu_without_overlapping_cells() -> None:
    # Defect: a track or column offset places one tile over another or past the menu's edge.
    for controls in (RESTING, Controls("02:05", None), Controls("02:05", "Reading"), replace(RESTING, agent="Reading")):
        laid = tiles(Menu(entries(controls)))
        for tile in laid:
            assert tile.x > 0 and tile.x + tile.width < MENU_WIDTH
        for first in laid:
            for second in laid:
                if first.index < second.index:
                    apart = (
                        first.x + first.width <= second.x
                        or second.x + second.width <= first.x
                        or first.y + first.height <= second.y
                        or second.y + second.height <= first.y
                    )
                    assert apart, f"{label(first.cell.entry)} overlaps {label(second.cell.entry)}"


def test_toggles_show_their_state_and_apply_in_place() -> None:
    # Defects: a toggle misreports its setting, or flipping it closes the menu like a launcher.
    cells = entries(Controls(None, None, AutomaticStatus.READY, overlay=True, taskbar=False))
    toggles = [cell.entry for cell in cells if cell.face is Face.TOGGLE]
    assert toggles == [
        Toggle("Auto-record", "Teams · On", "mic", Command.AUTOMATIC_RECORDING, on=True),
        Toggle("Keyboard overlay", "On", "layers", Command.OVERLAY, on=True),
        Toggle("Windows taskbar", "Hidden", "table", Command.TASKBAR, on=False),
    ]
    menu = Menu(cells)
    assert press(at(menu, "Keyboard overlay"), Key.ENTER) == Applied(Command.OVERLAY)
    assert press(at(menu, "Your work canvas"), Key.ENTER) == Chosen(Command.CANVAS)


def test_automatic_recording_reports_connection_failure_while_opted_in() -> None:
    # Defect: the toggle advertises monitoring after a connection failure, or reads as off while still opted in.
    for status, detail, on in (
        (AutomaticStatus.OFF, "Teams · Off", False),
        (AutomaticStatus.CHECKING, "Teams · Connecting…", True),
        (AutomaticStatus.UNAVAILABLE, "Teams · Check connection", True),
    ):
        toggle = next(cell.entry for cell in entries(Controls(None, None, status)) if cell.face is Face.TOGGLE)
        assert toggle == Toggle("Auto-record", detail, "mic", Command.AUTOMATIC_RECORDING, on=on)


def test_arrows_move_to_the_neighbouring_cell_and_up_and_down_wrap() -> None:
    # Defects: an arrow skips the cell beside or below the selection, Left leaves
    # the grid's edge, or Down from the last cell strands the selection.
    menu = Menu(entries(RESTING))
    assert selected(press(menu, Key.DOWN)) == "Auto-record"
    assert selected(press(at(menu, "Auto-record"), Key.RIGHT)) == "Your work canvas"
    assert selected(press(at(menu, "Keyboard overlay"), Key.DOWN)) == "Windows taskbar"
    assert selected(press(at(menu, "Your work feed"), Key.LEFT)) == "Windows taskbar"
    assert selected(press(at(menu, "Your work feed"), Key.DOWN)) == "Record a meeting"
    assert selected(press(at(menu, "Record a meeting"), Key.DOWN)) == "Sound"
    assert selected(press(at(menu, "Copy latest transcript"), Key.RIGHT)) == "Window tiling"
    assert selected(press(at(menu, "Switch windows"), Key.LEFT)) == "Switch windows"
    assert selected(press(at(menu, "All Workspace controls…"), Key.DOWN)) == "Auto-record"
    assert selected(press(at(menu, "Auto-record"), Key.UP)) == "All Workspace controls…"


def test_the_sound_slider_steps_the_volume_within_its_range() -> None:
    # Defects: Left or Right moves off the slider instead of changing the volume,
    # a step leaves the 0 to 1 range, or an unknown level invents one.
    menu = at(Menu(entries(RESTING)), "Sound")
    assert press(menu, Key.RIGHT) == Applied(Volume(0.45))
    assert press(menu, Key.LEFT) == Applied(Volume(0.35))
    full = at(Menu(entries(replace(RESTING, sound=Slider("Sound", 0.98, muted=False)))), "Sound")
    assert press(full, Key.RIGHT) == Applied(Volume(1.0))
    unknown = at(Menu(entries(Controls(None, None))), "Sound")
    assert press(unknown, Key.RIGHT) == unknown
    assert press(menu, Key.ENTER) == menu


def test_tiling_opens_its_page_and_closes_back_onto_its_cell() -> None:
    # Defects: Right on tiling does nothing, its page stays after Left or Escape, or
    # closing leaves the selection on a cell that no longer exists.
    page = opened(press(at(Menu(entries(RESTING)), "Window tiling"), Key.RIGHT))
    assert selected(page) == "Spread windows across screens"
    assert [label(cell.entry) for cell in shown(page)] == ["Window tiling", *(item.label for item in TILING.items)]
    assert press(page, Key.ENTER) == Chosen(ToolChoice(Tool.TILE_BALANCE))
    for key in (Key.LEFT, Key.ESCAPE):
        back = opened(press(page, key))
        assert selected(back) == "Window tiling" and not back.disclosed


def test_enter_chooses_escape_dismisses_and_a_letter_jumps_to_the_next_match() -> None:
    # Defects: Enter on a card doesn't stop its activity, Escape chooses something,
    # or a repeated letter stays on its first match.
    menu = Menu(entries(Controls("02:05", None)), selected=0)
    assert press(menu, Key.ENTER) == Chosen(Command.STOP_RECORDING)
    assert press(menu, Key.ESCAPE) is Dismissed.ESCAPE
    first = opened(press(menu, Letter("k")))
    assert selected(first) == "Keyboard overlay"
    assert selected(press(first, Letter("K"))) == "Keyboard map"


def test_tool_cells_derive_hints_and_short_captions() -> None:
    # Defects: the switcher advertises layer/tap labels instead of physical keys, or a
    # small tile shows a caption that doesn't name its tool.
    tools = [(cell.entry, cell.caption) for cell in entries(RESTING) if cell.face is Face.TOOL]
    assert tools[0] == (Item("Switch windows", "search", ToolChoice(Tool.WINDOW_SWITCHER), ". X"), "Switch")
    assert [caption for _, caption in tools] == ["Switch", "Transcript", "Tiling", "Key map"]


def test_window_tools_hand_the_keyboard_back_and_workspace_views_keep_it() -> None:
    # Defects: tiling acts on the menu instead of the user's window, or a Workspace
    # view that just opened loses the keyboard to the previous window.
    assert restores_focus(ToolChoice(Tool.TILE_FLOAT)) and restores_focus(Command.TASKBAR)
    assert not restores_focus(Command.CANVAS) and not restores_focus(Command.KEYMAP)
