"""The controls menu (press the clock or battery), top to bottom.

The menu is a grid of 8 columns. Each row is a band `tracks` tall (a track is
`menu.track` in `sizes`, gutter included):

- `CellsRow`: entries placed left to right; `span` is their width in columns. An
  entry that doesn't apply now (Record a meeting while one records) gives its
  place to the next; an empty row takes no space.
- `ActivitiesRow`: a full-width card with its Stop for each running activity.
- `TrayRow`: the system tray's icons, a column each, wrapping onto new lines.

Each entry is placed once; the sound slider takes Windows' own name.
"""

from typing import Final

from desktop_ui.island_menu import ActivitiesRow, CellSpec, CellsRow, ControlsSpec, EntryId, Face, TrayRow

CONTROLS: Final = ControlsSpec(
    (
        ActivitiesRow(5),
        CellsRow(
            4,
            (
                CellSpec(EntryId.AUTO_RECORD, Face.TOGGLE, 4, "Auto-record", "mic"),
                CellSpec(EntryId.CANVAS, Face.TILE, 4, "Your work canvas", "canvas", "Canvas"),
            ),
        ),
        CellsRow(
            4,
            (
                CellSpec(EntryId.OVERLAY, Face.TOGGLE, 4, "Keyboard overlay", "layers"),
                CellSpec(EntryId.TASKBAR, Face.TOGGLE, 4, "Windows taskbar", "table"),
            ),
        ),
        CellsRow(
            4,
            (
                CellSpec(EntryId.PLACEMENT, Face.TOGGLE, 4, "Placement", "grid"),
                CellSpec(EntryId.DARK_WHEN_AWAY, Face.TOGGLE, 4, "Dark when away", "lock"),
            ),
        ),
        CellsRow(5, (CellSpec(EntryId.RECORD, Face.WIDE, 8, "Record a meeting", "mic"),)),
        CellsRow(6, (CellSpec(EntryId.SOUND, Face.SLIDER, 8),)),
        CellsRow(
            7,
            (
                CellSpec(EntryId.SWITCH_WINDOWS, Face.TOOL, 2, "Switch windows", "search", "Switch"),
                CellSpec(EntryId.COPY_TRANSCRIPT, Face.TOOL, 2, "Copy latest transcript", "doc", "Transcript"),
                CellSpec(EntryId.KEYMAP, Face.TOOL, 2, "Keyboard map", "keyboard", "Key map"),
                CellSpec(EntryId.AGENT_TYPED, Face.TOOL, 2, "Type a task for the agent", "agent", "Agent"),
            ),
        ),
        TrayRow(4),
        CellsRow(3, (CellSpec(EntryId.NOTIFICATIONS, Face.LINK, 8, "Windows notification settings", "bell"),)),
        CellsRow(3, (CellSpec(EntryId.ALL_CONTROLS, Face.LINK, 8, "All Workspace controls…", "more"),)),
    )
)
