"""Double-click launcher: the keeper runs the layout and the assistant."""

from runtime import activate
lazy from keeper import STATE, main
lazy from keeper_ui import launch

activate()
launch(STATE, main)
