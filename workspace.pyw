"""Double-click launcher: the keeper runs the layout and the assistant."""

import sys

from runtime import activate
lazy from keeper import RELAUNCH, RELAUNCH_WAIT_S, STATE, main
lazy from keeper_ui import launch

activate()
launch(STATE, main, wait_s=RELAUNCH_WAIT_S if RELAUNCH in sys.argv else 0)
