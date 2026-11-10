"""Where Microsoft Edge is installed."""

import os
from pathlib import Path
from typing import Final

DETACHED: Final = 0x0000_0008 | 0x0800_0000
"""DETACHED_PROCESS | CREATE_NO_WINDOW: a child that outlives its parent, without a console."""


def edge_path() -> Path | None:
    """Microsoft Edge's executable, wherever this machine installed it; None when it isn't."""
    roots = (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA"))
    return next((path for root in roots if root and (path := Path(root) / "Microsoft/Edge/Application/msedge.exe").is_file()), None)
