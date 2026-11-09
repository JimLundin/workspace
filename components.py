"""The programs the launcher runs, the windows they own, and where they keep their state.

Only declarations: the types are `protocol`'s. Standard library only, so the
keyboard process can read it.
"""

import os
import tempfile
from pathlib import Path
from typing import Final

from protocol import Component, Entry, Message, Window

# The gateway holds no state: it creates no window, so the launcher ends it at once.
GATEWAY: Final = Entry(name="gateway", module="gateway", window=Window("workspace gateway", None), quit_message=Message.CLOSE, shutdown_s=0.0)
# The keyboard has nothing to drain, so a stuck one is replaced quickly.
LAYOUT: Final = Entry(name="layout", module="keyboard", window=Window("workspace layout", None), quit_message=Message.QUIT_LAYOUT, shutdown_s=5.0)
# The desktop closes its windows and the tray icon, finishes a meeting's capture
# and stops dictation: half a minute at most.
DESKTOP: Final = Entry(
    name="desktop",
    module="desktop",
    window=Window("workspace desktop", "workspace desktop class"),
    quit_message=Message.CLOSE,
    shutdown_s=30.0,
)

CATALOGUE: Final[frozendict[Component, Entry]] = frozendict({entry.name: entry for entry in (GATEWAY, LAYOUT, DESKTOP)})
"""In startup order; shutdown reverses it."""

BAR_WINDOW: Final = "Workspace floating bar"
"""The desktop's visible surface."""
SWITCHER_TITLE: Final = "Workspace window switcher"
"""The desktop's window switcher; the layout passes Esc, Enter and Tab to it while it has focus."""

DIRECTORY: Final = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "workspace"
"""Where the programs keep their logs and state."""
STATE_VARIABLE: Final = "WORKSPACE_STATE"
"""The launcher's state folder, passed to every program it starts."""
GATEWAY_ENDPOINT: Final = Path(os.environ[STATE_VARIABLE]) / "endpoint-gateway" if STATE_VARIABLE in os.environ else None
"""Where the gateway publishes how to reach it; None outside the launcher."""
