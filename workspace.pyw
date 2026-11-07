"""Double-click launcher: the keeper runs the gateway, the layout, the assistant and the desktop.

Before anything else it makes sure it runs in the environment the installed
dependency lock names: built once from PyPI if it's new, then this launcher
starts again with that environment's interpreter. Everything the keeper starts
inherits that interpreter.
"""

import ctypes
import os
import subprocess
import sys
from pathlib import Path

import environments
lazy from keeper import RELAUNCH, RELAUNCH_WAIT_S, STATE, main
lazy from keeper_ui import launch

ROOT = Path(__file__).resolve().parent
DETACHED_PROCESS = 0x0000_0008

try:
    environment = environments.ensure(ROOT / environments.LOCK)
except environments.DependencyError as error:
    ctypes.windll.user32.MessageBoxW(None, f"Workspace couldn't install its dependencies.\n\n{error}", "Workspace", 0x10)
    sys.exit(1)
if not environments.running_in(environment):
    command = [str(environments.pythonw(environment)), str(Path(__file__).resolve()), *sys.argv[1:]]
    # Nothing may graft other packages onto the environment's interpreter (the retired bundle did).
    clean = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "WORKSPACE_BUNDLED_RUNTIME")}
    subprocess.Popen(command, cwd=ROOT, env=clean, creationflags=DETACHED_PROCESS)
    sys.exit(0)
launch(STATE, main, wait_s=RELAUNCH_WAIT_S if RELAUNCH in sys.argv else 0)
