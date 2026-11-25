from typing import Final

from protocol import App, Installed, PinnedWeb

APPS: Final[tuple[App, ...]] = (
    App("terminal", Installed("windowsterminal.exe", "wt.exe")),
    App("browser", Installed("msedge.exe", "msedge.exe")),
    App("outlook", PinnedWeb("outlook")),
    App("teams", PinnedWeb("teams")),
    App("files", Installed("explorer.exe", "explorer.exe")),
    App("notepad", Installed("notepad.exe", "notepad.exe")),
)
