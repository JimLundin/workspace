"""The programs the launcher runs, and the windows they find each other by.

Only declarations: the types are `protocol`'s. Standard library only, so the
keyboard process can read it.
"""

from typing import Final

from protocol import Entry, Message, Programs, Window

PROGRAMS: Final = Programs(
    # The gateway holds no state: it creates no window, so the launcher ends it at once.
    gateway=Entry(name="gateway", module="gateway", window=Window("workspace gateway", None), quit_message=Message.CLOSE, shutdown_s=0.0),
    # The keyboard has nothing to drain, so a stuck one is replaced quickly.
    layout=Entry(name="layout", module="keyboard", window=Window("workspace layout", None), quit_message=Message.QUIT_LAYOUT, shutdown_s=5.0),
    # The desktop closes its windows and the tray icon, finishes a meeting's capture
    # and stops dictation: half a minute at most.
    desktop=Entry(
        name="desktop",
        module="desktop",
        window=Window("workspace desktop", "workspace desktop class"),
        quit_message=Message.CLOSE,
        shutdown_s=30.0,
    ),
    switcher="Workspace window switcher",
    state_variable="WORKSPACE_STATE",
)
