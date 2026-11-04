"""The controls menu's grid and its keyboard navigation."""

from dataclasses import replace

from assistant.meeting_detection import AutomaticStatus
from desktop_ui.island_layout import MENU_WIDTH, tiles
from desktop_ui.island_menu import (
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
    TrayChoice,
    TrayIcon,
    Volume,
    entries,
    label,
    press,
    restores_focus,
)
from protocol import Tool

RESTING = Controls(None, None, sound=Slider("Sound", 0.4, muted=False))


def at(menu: Menu, name: str) -> Menu:
    return replace(menu, selected=next(index for index, cell in enumerate(menu.cells) if label(cell.entry) == name))


def selected(outcome: Outcome) -> str:
    match outcome:
        case Menu(selected=int() as index) as menu:
            return label(menu.cells[index].entry)
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
    tray = tuple(f"App {index}" for index in range(11))
    for controls in (RESTING, Controls("02:05", None), Controls("02:05", "Reading"), replace(RESTING, agent="Reading"), replace(RESTING, tray=tray)):
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
    cells = entries(Controls(None, None, AutomaticStatus.READY, overlay=True, taskbar=False, dark_when_locked=False))
    toggles = [cell.entry for cell in cells if cell.face is Face.TOGGLE]
    assert toggles == [
        Toggle("Auto-record", "Teams · On", "mic", Command.AUTOMATIC_RECORDING, on=True),
        Toggle("Keyboard overlay", "On", "layers", Command.OVERLAY, on=True),
        Toggle("Windows taskbar", "Hidden", "table", Command.TASKBAR, on=False),
        Toggle("Window placement", "On", "grid", Command.PLACEMENT, on=True),
        Toggle("Dark when locked", "Off", "lock", Command.DARK_WHEN_LOCKED, on=False),
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
    assert selected(press(at(menu, "Your work feed"), Key.LEFT)) == "Window placement"
    assert selected(press(at(menu, "Your work feed"), Key.DOWN)) == "Record a meeting"
    assert selected(press(at(menu, "Record a meeting"), Key.DOWN)) == "Sound"
    assert selected(press(at(menu, "Copy latest transcript"), Key.RIGHT)) == "Keyboard map"
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
    assert tools[0] == (Item("Switch windows", "search", ToolChoice(Tool.WINDOW_SWITCHER), "⌃⌥⇧ C"), "Switch")
    assert [caption for _, caption in tools] == ["Switch", "Transcript", "Key map"]


def test_window_tools_hand_the_keyboard_back_and_workspace_views_keep_it() -> None:
    # Defects: a window tool acts on the menu instead of the user's window, or a Workspace
    # view that just opened loses the keyboard to the previous window.
    assert restores_focus(ToolChoice(Tool.MINIMIZE)) and restores_focus(Command.TASKBAR)
    assert not restores_focus(Command.CANVAS) and not restores_focus(Command.KEYMAP) and not restores_focus(TrayChoice(0))


def test_tray_icons_fill_rows_of_eight_after_the_tools_and_click_their_own_slot() -> None:
    # Defects: an icon lands on the wrong row or slot, the links overlap the tray,
    # or Enter on an icon clicks another application's icon.
    menu = Menu(entries(replace(RESTING, tray=tuple(f"App {index}" for index in range(10)))))
    icons = [cell for cell in menu.cells if cell.face is Face.ICON]
    assert [cell.entry for cell in icons] == [TrayIcon(f"App {index}", index) for index in range(10)]
    assert [(cell.column, cell.track - icons[0].track) for cell in icons] == [*((column, 0) for column in range(8)), (0, 4), (1, 4)]
    assert selected(press(at(menu, "Switch windows"), Key.DOWN)) == "App 0"
    assert selected(press(at(menu, "App 1"), Key.DOWN)) == "App 9"
    assert selected(press(at(menu, "App 9"), Key.DOWN)) == "Windows notification settings"
    assert press(at(menu, "App 9"), Key.ENTER) == Chosen(TrayChoice(9))
    assert not any(cell.face is Face.ICON for cell in entries(RESTING))
