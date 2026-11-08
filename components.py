"""The programs the keeper supervises, and how each one proves it is up.

The keeper, its restart plan and every child read this one catalogue.
It is protected with the keeper and uses only the standard library, so the
keyboard process announces readiness without importing the keeper.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

type Component = Literal["gateway", "layout", "desktop"]

WM_CLOSE: Final = 0x0010
WM_QUIT_LAYOUT: Final = 0x8000 + 3
"""Keeper -> layout: release held keys, then exit cleanly. Here, not in `protocol`,
so the AI connection's closure stays clear of the keyboard's wire contract."""


@dataclass(frozen=True, slots=True)
class Window:
    """The hidden control window a component creates; other processes find it by title."""

    title: str
    window_class: str | None
    """None matches any class: the component uses a system class, not its own."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Entry:
    name: Component
    module: str
    """Started as `python -m <module>`."""
    window: Window
    quit_message: int
    """Posted to `window` to ask for a clean exit; the layout lets go of held keys first."""
    shutdown_s: float
    """How long the keeper waits for a clean exit before ending the process."""
    live_assets: tuple[str, ...] = ()
    """Folders of data files the running program reloads itself; changing one restarts nothing."""


# The AI connection holds no state: it creates no window, so the keeper ends it at once.
GATEWAY: Final = Entry(name="gateway", module="gateway", window=Window("workspace gateway", None), quit_message=WM_CLOSE, shutdown_s=0.0)
# The keyboard has nothing to drain, so a stuck one is replaced quickly.
LAYOUT: Final = Entry(name="layout", module="miryoku", window=Window("workspace layout", None), quit_message=WM_QUIT_LAYOUT, shutdown_s=5.0)
# The desktop closes its windows and the tray icon, and the assistant inside it
# finishes a meeting's capture and stops dictation: half a minute at most.
DESKTOP: Final = Entry(
    name="desktop",
    module="desktop",
    window=Window("workspace desktop", "workspace desktop class"),
    quit_message=WM_CLOSE,
    shutdown_s=30.0,
    live_assets=("desktop_ui/spec/",),
)

CATALOGUE: Final[frozendict[Component, Entry]] = frozendict({entry.name: entry for entry in (GATEWAY, LAYOUT, DESKTOP)})
"""In startup order; shutdown reverses it."""

ASSISTANT_WINDOW: Final = Window("workspace assistant", "workspace assistant class")
"""The assistant's hidden control window in the desktop's process: the keyboard sends it dictation and meeting requests."""

BAR_WINDOW: Final = "Workspace floating bar"
"""The desktop's visible surface."""


STATE_VARIABLE: Final = "WORKSPACE_STATE"
"""The keeper's state folder, passed to every child it starts."""


def endpoint(name: Component) -> Path | None:
    """Where `name` publishes how to reach it; None outside the keeper."""
    state = os.environ.get(STATE_VARIABLE)
    return Path(state) / f"endpoint-{name}" if state else None
