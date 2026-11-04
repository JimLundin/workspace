"""Your settings: the apps the chords reach, text snippets, and which commands skip
prompts in optional approval mode. Edit freely; it's checked when Workspace starts.
(Secrets and the AI endpoint are environment variables instead; see the README.)
"""

from collections.abc import Callable
from datetime import datetime
from typing import Final

from protocol import App, Installed, PinnedWeb

# ---- Apps ------------------------------------------------------------------------------
# Up to ten, in chord-letter order: Q W F P B, then A R S T G (see `miryoku.firmware.CHORDS`).

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

# ---- Snippets --------------------------------------------------------------------------
# Type the trigger and it's replaced by the text. A function is called each time.
# Triggers start with ",," so they never turn up in normal writing.


def _now(fmt: str) -> Callable[[], str]:
    return lambda: datetime.now().strftime(fmt)


SNIPPETS: Final[dict[str, str | Callable[[], str]]] = {
    ",,date": _now("%Y-%m-%d"),
    ",,time": _now("%H:%M"),
    ",,now": _now("%Y-%m-%d %H:%M"),
    ",,week": _now("week %V"),
    ",,shrug": "¯\\_(ツ)_/¯",
    ",,thx": "Thanks!",
    ",,mvh": "Med vänliga hälsningar",
    ",,br": "Best regards",
}

# ---- Agent -----------------------------------------------------------------------------
# With WORKSPACE_AGENT_APPROVALS=ask, these commands skip the prompt only when
# nothing can chain another command after them. Default mode allows requested commands directly.

ALLOWED_COMMANDS: Final[tuple[str, ...]] = (
    "Get-ChildItem",
    "Get-Content",
    "Get-Date",
    "Get-Location",
    "Get-Process",
    "Select-String",
    "git status",
    "git log",
    "git diff",
)

AGENT_MAX_STEPS: Final = 80
"""The agent stops after this many actions, finished or not."""

# ---- Screens ---------------------------------------------------------------------------
# With Dark when away on, the home 4K screen goes dark after this many minutes without
# keyboard or mouse input, and wakes at the next touch. Whole minutes from 1 to 60.

DARK_WHEN_IDLE_MINUTES: Final = 2
