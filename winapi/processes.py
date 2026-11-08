"""Where Microsoft Edge is installed."""

import os
from pathlib import Path


def edge_path() -> Path | None:
    """Microsoft Edge's executable, wherever this machine installed it; None when it isn't."""
    roots = (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA"))
    return next((path for root in roots if root and (path := Path(root) / "Microsoft/Edge/Application/msedge.exe").is_file()), None)
