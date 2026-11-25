from typing import Final

from protocol import Entry, Message, Programs, Window

PROGRAMS: Final = Programs(
    gateway=Entry(
        name="gateway",
        module="gateway",
        window=Window("workspace gateway", None),
        quit_message=Message.CLOSE,
        shutdown_s=0.0,
    ),
    layout=Entry(
        name="layout",
        module="keyboard",
        window=Window("workspace layout", None),
        quit_message=Message.QUIT_LAYOUT,
        shutdown_s=5.0,
    ),
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
