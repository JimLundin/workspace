from typing import Final

from protocol import App, Installed, PinnedWeb


APPS: Final[tuple[App, ...]] = (
    App("terminal", Installed("windowsterminal.exe", "wt.exe")),
    App("browser", Installed("msedge.exe", "msedge.exe")),
    App("outlook", PinnedWeb("outlook")),
    App("teams", PinnedWeb("teams")),
    App("files", Installed("explorer.exe", "explorer.exe")),
    App("code", Installed("code.exe", "code")),
    App("notepad", Installed("notepad.exe", "notepad.exe")),
    App("excel", Installed("excel.exe", "excel.exe")),
    App("word", Installed("winword.exe", "winword.exe")),
    App("PowerPoint", Installed("powerpnt.exe", "powerpnt.exe")),
)
