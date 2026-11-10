"""The controls menu's grid and its keyboard navigation.

The spec and grid here are the test's own, so each test checks how the menu
flows and navigates whatever it is given, never the real menu's rows or labels.
"""

from dataclasses import replace
from itertools import pairwise

from desktop_ui.island_layout import MenuGrid, tiles
from desktop_ui.island_menu import (
    DISMISSED,
    ActivitiesRow,
    Applied,
    Cell,
    CellSpec,
    CellsRow,
    Chosen,
    Command,
    Controls,
    ControlsSpec,
    EntryId,
    Face,
    Item,
    Key,
    Letter,
    Live,
    Menu,
    MenuWords,
    Outcome,
    Slider,
    Toggle,
    ToolChoice,
    TrayChoice,
    TrayIcon,
    TrayRow,
    Volume,
    entries,
    label,
    press,
    restores_focus,
)
from protocol import Tool

TRAY_TRACKS = 3

SPEC = ControlsSpec(
    (
        ActivitiesRow(3),
        CellsRow(2, (CellSpec(EntryId.OVERLAY, Face.TOGGLE, 4, "Keys"), CellSpec(EntryId.PLACEMENT, Face.TOGGLE, 4, "Placing"))),
        CellsRow(2, (CellSpec(EntryId.DARK_WHEN_AWAY, Face.TOGGLE, 8, "Dark"),)),
        CellsRow(2, (CellSpec(EntryId.RECORD, Face.WIDE, 8, "Record"),)),
        CellsRow(2, (CellSpec(EntryId.SOUND, Face.SLIDER, 8),)),
        CellsRow(
            2,
            (
                CellSpec(EntryId.SWITCH_WINDOWS, Face.TOOL, 2, "Switch"),
                CellSpec(EntryId.COPY_TRANSCRIPT, Face.TOOL, 2, "Copy"),
                CellSpec(EntryId.KEYMAP, Face.TOOL, 2, "Key map"),
            ),
        ),
        TrayRow(TRAY_TRACKS),
        CellsRow(1, (CellSpec(EntryId.NOTIFICATIONS, Face.LINK, 8, "Notices"),)),
        CellsRow(1, (CellSpec(EntryId.ALL_CONTROLS, Face.LINK, 8, "Everything"),)),
    ),
    MenuWords(on="Yes", off="No", paused="Held", away="After {minutes}", recording="Taping", sound="Level", unread="?", muted="hushed"),
)

RESTING = Controls(None, sound=Slider("Volume", 0.4, muted=False))


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
    # Defects: a running recording still offers its start, or has no Stop in the menu.
    cells = entries(Controls("02:05"), SPEC)
    assert cells[0].face is Face.CARD and isinstance(cells[0].entry, Live) and cells[0].entry.stop is Command.STOP_RECORDING
    assert not any(isinstance(cell.entry, Item) and cell.entry.choice is Command.RECORD for cell in cells)
    assert any(isinstance(cell.entry, Item) and cell.entry.choice is Command.RECORD for cell in entries(RESTING, SPEC))


def test_every_grid_fits_the_menu_without_overlapping_cells() -> None:
    # Defect: a track or column offset places one tile over another or past the menu's edge.
    grid = MenuGrid(width=200, radius=0, pad=5, head=10, track=4, gutter=2)
    tray = tuple(f"App {index}" for index in range(11))
    for controls in (RESTING, Controls("02:05"), replace(RESTING, tray=tray)):
        laid = tiles(Menu(entries(controls, SPEC)), grid)
        for tile in laid:
            assert tile.x > 0 and tile.x + tile.width < grid.width
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
    def states(controls: Controls) -> dict[Command, bool]:
        return {cell.entry.choice: cell.entry.on for cell in entries(controls, SPEC) if isinstance(cell.entry, Toggle)}

    assert states(Controls(None, overlay=True, dark_when_away=2)) == {Command.OVERLAY: True, Command.PLACEMENT: True, Command.DARK_WHEN_AWAY: True}
    assert states(Controls(None, placement_paused=True)) == {Command.OVERLAY: False, Command.PLACEMENT: False, Command.DARK_WHEN_AWAY: False}
    menu = Menu(entries(RESTING, SPEC))
    assert press(at(menu, "Keys"), Key.ENTER) == Applied(Command.OVERLAY)
    assert press(at(menu, "Key map"), Key.ENTER) == Chosen(Command.KEYMAP)


def test_arrows_move_to_the_neighbouring_cell_and_up_and_down_wrap() -> None:
    # Defects: an arrow skips the cell beside or below the selection, Left or Right
    # leaves the grid's edge, or Down from the last cell strands the selection.
    menu = Menu(entries(RESTING, SPEC))
    assert selected(press(menu, Key.DOWN)) == "Keys"
    assert selected(press(at(menu, "Keys"), Key.RIGHT)) == "Placing"
    assert selected(press(at(menu, "Placing"), Key.LEFT)) == "Keys"
    assert selected(press(at(menu, "Placing"), Key.DOWN)) == "Dark"
    assert selected(press(at(menu, "Record"), Key.DOWN)) == "Volume"
    assert selected(press(at(menu, "Copy"), Key.RIGHT)) == "Key map"
    assert selected(press(at(menu, "Key map"), Key.RIGHT)) == "Key map"
    assert selected(press(at(menu, "Switch"), Key.LEFT)) == "Switch"
    assert selected(press(at(menu, "Everything"), Key.DOWN)) == "Keys"
    assert selected(press(at(menu, "Keys"), Key.UP)) == "Everything"


def test_the_sound_slider_steps_the_volume_within_its_range() -> None:
    # Defects: Left or Right moves off the slider instead of changing the volume,
    # a step leaves the 0 to 1 range, or an unknown level invents one.
    def stepped(level: float | None, key: Key) -> Outcome:
        return press(at(Menu(entries(replace(RESTING, sound=Slider("Volume", level, muted=False)), SPEC)), "Volume"), key)

    match stepped(0.4, Key.RIGHT), stepped(0.4, Key.LEFT):
        case Applied(Volume(up)), Applied(Volume(down)):
            assert down < 0.4 < up and abs((up - 0.4) - (0.4 - down)) < 1e-9
        case other:
            raise AssertionError(f"Expected two volume changes, got {other}")
    assert stepped(1.0, Key.RIGHT) == Applied(Volume(1.0))
    assert stepped(0.0, Key.LEFT) == Applied(Volume(0.0))
    unknown = at(Menu(entries(replace(RESTING, sound=Slider("Volume", None, muted=False)), SPEC)), "Volume")
    assert press(unknown, Key.RIGHT) == unknown
    menu = at(Menu(entries(RESTING, SPEC)), "Volume")
    assert press(menu, Key.ENTER) == menu


def test_enter_chooses_escape_dismisses_and_a_letter_jumps_to_the_next_match() -> None:
    # Defects: Enter on a card doesn't stop its activity, Escape chooses something,
    # or a repeated letter stays on its first match.
    menu = Menu(entries(Controls("02:05"), SPEC), selected=0)
    assert press(menu, Key.ENTER) == Chosen(Command.STOP_RECORDING)
    assert press(menu, Key.ESCAPE) is DISMISSED
    first = opened(press(menu, Letter("k")))
    assert selected(first) == "Keys"
    assert selected(press(first, Letter("K"))) == "Key map"


def test_window_tools_hand_the_keyboard_back_and_workspace_views_keep_it() -> None:
    # Defects: a window tool acts on the menu instead of the user's window, or a Workspace
    # view that just opened loses the keyboard to the previous window.
    assert restores_focus(ToolChoice(Tool.COPY_TRANSCRIPT)) and restores_focus(Command.PLACEMENT)
    assert not restores_focus(Command.KEYMAP) and not restores_focus(TrayChoice(0))


def test_tray_icons_wrap_onto_new_lines_after_the_tools_and_click_their_own_slot() -> None:
    # Defects: an icon lands on the wrong line or slot, the links overlap the tray,
    # or Enter on an icon clicks another application's icon.
    count = 30
    menu = Menu(entries(replace(RESTING, tray=tuple(f"App {index}" for index in range(count))), SPEC))
    icons = [cell for cell in menu.cells if cell.face is Face.ICON]
    assert [cell.entry for cell in icons] == [TrayIcon(f"App {index}", index) for index in range(count)]
    assert (icons[0].column, icons[0].span) == (0, 1)
    for before, after in pairwise(icons):
        same_line = (after.column, after.track) == (before.column + 1, before.track)
        next_line = (after.column, after.track) == (0, before.track + TRAY_TRACKS)
        assert same_line or next_line, f"{label(after.entry)} doesn't follow {label(before.entry)}"
    assert len({cell.track for cell in icons}) > 1, "Expected the icons to wrap."

    def below(icon: Cell) -> Cell | None:
        return next((cell for cell in icons if cell.column == icon.column and cell.track == icon.track + TRAY_TRACKS), None)

    assert selected(press(at(menu, "Switch"), Key.DOWN)) == "App 0"
    for icon in icons:
        if (under := below(icon)) is not None:
            assert selected(press(at(menu, label(icon.entry)), Key.DOWN)) == label(under.entry)
    assert selected(press(at(menu, f"App {count - 1}"), Key.DOWN)) == "Notices"
    assert press(at(menu, "App 9"), Key.ENTER) == Chosen(TrayChoice(9))
    assert not any(cell.face is Face.ICON for cell in entries(RESTING, SPEC))
