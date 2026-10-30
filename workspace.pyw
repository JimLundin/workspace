"""Double-click launcher: the keeper runs the layout, assistant, and automation."""

from runtime import activate
lazy from keeper import STATE, main
lazy from keeper_ui import launch

activate()
launch(STATE, main)
