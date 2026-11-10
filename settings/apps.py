"""Your apps: the ones the chords reach, in chord-letter order.
Edit freely; it's checked when Workspace starts.
(Secrets and the AI endpoint are environment variables instead; see the README.)
"""

from typing import Final

from protocol import App, Installed, PinnedWeb

# ---- Apps ------------------------------------------------------------------------------
# Up to ten, in chord-letter order: Q W F P B, then A R S T G (see `keyboard.firmware.Chords`).

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
