"""The tray icon's menu, top to bottom.

`TOGGLE_LAYOUT`, `RESTART_LAYOUT` and `MEETING` word their own state and take no
label; the `AGENT` and `STOP_AGENT` hints come from the key map. Each action is
listed once.
"""

from typing import Final

from assistant.control_policy import Menu, Separator, TrayAction, TraySpec

TRAY: Final = TraySpec(
    (
        TrayAction(Menu.TOGGLE_LAYOUT),
        TrayAction(Menu.RESTART_LAYOUT),
        TrayAction(Menu.OVERLAY, "Keyboard overlay"),
        TrayAction(Menu.KEYMAP, "Key map"),
        Separator(),
        TrayAction(Menu.AGENT, "Agent session"),
        TrayAction(Menu.WORK, "Work…"),
        TrayAction(Menu.TASKBAR, "Toggle Windows taskbar", "Windows key"),
        TrayAction(Menu.STOP_AGENT, "Stop agent"),
        TrayAction(Menu.MEETING),
        TrayAction(Menu.TRANSCRIPTS, "Open meeting transcripts"),
        Separator(),
        TrayAction(Menu.UNDO, "Undo the last update"),
        TrayAction(Menu.USAGE, "Usage report"),
        TrayAction(Menu.LOGS, "Open logs folder"),
        Separator(),
        TrayAction(Menu.RESTART_ASSISTANT, "Restart assistant"),
        TrayAction(Menu.QUIT, "Quit Workspace"),
    )
)
