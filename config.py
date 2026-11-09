"""Your settings: the apps the chords reach and the dark-screen delay.
Edit freely; it's checked when Workspace starts.
(Secrets and the AI endpoint are environment variables instead; see the README.)
"""

from typing import Final

from protocol import App, Installed, PinnedWeb

# ---- Apps ------------------------------------------------------------------------------
# Up to ten, in chord-letter order: Q W F P B, then A R S T G (see `keyboard.firmware.CHORDS`).

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

# ---- Screens ---------------------------------------------------------------------------
# With Dark when away on, the home 4K screen goes dark after this many minutes without
# keyboard or mouse input, and wakes at the next touch. Whole minutes from 1 to 60.

DARK_WHEN_IDLE_MINUTES: Final = 2
