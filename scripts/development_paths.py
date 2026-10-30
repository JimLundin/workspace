"""Local installation paths for native Windows development and the WSL fallback."""

import os
from pathlib import Path

if os.name == "nt":
    USER = Path(os.environ["USERPROFILE"])
    LOCAL = Path(os.environ["LOCALAPPDATA"])
else:
    USER = Path("/mnt/c/Users/Jim.Lundin")
    LOCAL = USER / "AppData" / "Local"

LIVE = USER / "Downloads" / "workspace-sdk" / "workspace"
TEMP = LOCAL / "Temp"
PROFILE = LOCAL / "workspace"
PYTHON = LOCAL / "Programs" / "Python" / "Python315" / "python.exe"
