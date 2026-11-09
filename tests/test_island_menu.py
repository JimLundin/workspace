"""The controls menu's grid and its keyboard navigation."""

from dataclasses import replace

from desktop_ui.island_layout import SIZES, tiles
from desktop_ui.island_menu import (
    CONTROLS,
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

SPEC = CONTROLS

RESTING = Controls(None, sound=Slider("Sound", 0.4, muted=False))


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


def test_a_running_recording_leads_as_a_card_and_replaces_its_start() -> None:
    # Defects: a running recording still offers "Record a meeting", or has no Stop in the menu.
    cells = entries(Controls("02:05"), SPEC)
    assert cells[0].face is Face.CARD and isinstance(cells[0].entry, Live) and cells[0].entry.stop is Command.STOP_RECORDING
    assert not any(isinstance(cell.entry, Item) and cell.entry.choice is Command.RECORD for cell in cells)
    assert any(isinstance(cell.entry, Item) and cell.entry.choice is Command.RECORD for cell in entries(RESTING, SPEC))


def test_every_grid_fits_the_menu_without_overlapping_cells() -> None:
    # Defect: a track or column offset places one tile over another or past the menu's edge.
    tray = tuple(f"App {index}" for index in range(11))
    for controls in (RESTING, Controls("02:05"), replace(RESTING, tray=tray)):
        laid = tiles(Menu(entries(controls, SPEC)), SIZES.menu)
        for tile in laid:
            assert tile.x > 0 and tile.x + tile.width < SIZES.menu.width
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
    cells = entries(Controls(None, overlay=True, dark_when_away=2), SPEC)
    toggles = [cell.entry for cell in cells if cell.face is Face.TOGGLE]
    assert [(toggle.choice, toggle.on) for toggle in toggles if isinstance(toggle, Toggle)] == [
        (Command.OVERLAY, True),
        (Command.PLACEMENT, True),
        (Command.DARK_WHEN_AWAY, True),
    ]
    resting = [cell.entry for cell in entries(Controls(None, overlay=False), SPEC) if cell.face is Face.TOGGLE]
    assert [toggle.on for toggle in resting if isinstance(toggle, Toggle)] == [False, True, False]
    menu = Menu(cells)
    assert press(at(menu, "Keyboard overlay"), Key.ENTER) == Applied(Command.OVERLAY)
    assert press(at(menu, "Keyboard map"), Key.ENTER) == Chosen(Command.KEYMAP)


def test_arrows_move_to_the_neighbouring_cell_and_up_and_down_wrap() -> None:
    # Defects: an arrow skips the cell beside or below the selection, Left leaves
    # the grid's edge, or Down from the last cell strands the selection.
    menu = Menu(entries(RESTING, SPEC))
    assert selected(press(menu, Key.DOWN)) == "Keyboard overlay"
    assert selected(press(at(menu, "Keyboard overlay"), Key.RIGHT)) == "Placement"
    assert selected(press(at(menu, "Keyboard overlay"), Key.DOWN)) == "Dark when away"
    assert selected(press(at(menu, "Placement"), Key.LEFT)) == "Keyboard overlay"
    assert selected(press(at(menu, "Dark when away"), Key.DOWN)) == "Record a meeting"
    assert selected(press(at(menu, "Record a meeting"), Key.DOWN)) == "Sound"
    assert selected(press(at(menu, "Copy latest transcript"), Key.RIGHT)) == "Keyboard map"
    assert selected(press(at(menu, "Switch windows"), Key.LEFT)) == "Switch windows"
    assert selected(press(at(menu, "All Workspace controls…"), Key.DOWN)) == "Keyboard overlay"
    assert selected(press(at(menu, "Keyboard overlay"), Key.UP)) == "All Workspace controls…"


def test_the_sound_slider_steps_the_volume_within_its_range() -> None:
    # Defects: Left or Right moves off the slider instead of changing the volume,
    # a step leaves the 0 to 1 range, or an unknown level invents one.
    menu = at(Menu(entries(RESTING, SPEC)), "Sound")
    assert press(menu, Key.RIGHT) == Applied(Volume(0.45))
    assert press(menu, Key.LEFT) == Applied(Volume(0.35))
    full = at(Menu(entries(replace(RESTING, sound=Slider("Sound", 0.98, muted=False)), SPEC)), "Sound")
    assert press(full, Key.RIGHT) == Applied(Volume(1.0))
    unknown = at(Menu(entries(Controls(None), SPEC)), "Sound")
    assert press(unknown, Key.RIGHT) == unknown
    assert press(menu, Key.ENTER) == menu


def test_enter_chooses_escape_dismisses_and_a_letter_jumps_to_the_next_match() -> None:
    # Defects: Enter on a card doesn't stop its activity, Escape chooses something,
    # or a repeated letter stays on its first match.
    menu = Menu(entries(Controls("02:05"), SPEC), selected=0)
    assert press(menu, Key.ENTER) == Chosen(Command.STOP_RECORDING)
    assert press(menu, Key.ESCAPE) is Dismissed.ESCAPE
    first = opened(press(menu, Letter("k")))
    assert selected(first) == "Keyboard overlay"
    assert selected(press(first, Letter("K"))) == "Keyboard map"


def test_window_tools_hand_the_keyboard_back_and_workspace_views_keep_it() -> None:
    # Defects: a window tool acts on the menu instead of the user's window, or a Workspace
    # view that just opened loses the keyboard to the previous window.
    assert restores_focus(ToolChoice(Tool.COPY_TRANSCRIPT)) and restores_focus(Command.PLACEMENT)
    assert not restores_focus(Command.KEYMAP) and not restores_focus(TrayChoice(0))


def test_tray_icons_fill_rows_of_eight_after_the_tools_and_click_their_own_slot() -> None:
    # Defects: an icon lands on the wrong row or slot, the links overlap the tray,
    # or Enter on an icon clicks another application's icon.
    menu = Menu(entries(replace(RESTING, tray=tuple(f"App {index}" for index in range(10))), SPEC))
    icons = [cell for cell in menu.cells if cell.face is Face.ICON]
    assert [cell.entry for cell in icons] == [TrayIcon(f"App {index}", index) for index in range(10)]
    assert [(cell.column, cell.track - icons[0].track) for cell in icons] == [*((column, 0) for column in range(8)), (0, 4), (1, 4)]
    assert selected(press(at(menu, "Switch windows"), Key.DOWN)) == "App 0"
    assert selected(press(at(menu, "App 1"), Key.DOWN)) == "App 9"
    assert selected(press(at(menu, "App 9"), Key.DOWN)) == "Windows notification settings"
    assert press(at(menu, "App 9"), Key.ENTER) == Chosen(TrayChoice(9))
    assert not any(cell.face is Face.ICON for cell in entries(RESTING, SPEC))
