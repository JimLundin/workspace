"""Run Workspace's desktop: `pythonw -m desktop`. `launch.py` starts it with the gateway and the layout.

The desktop owns the bar, the tray, window placement, dictation and meetings.
Quit in its tray menu quits Workspace.
"""

import os
import sys

from protocol import Places
from settings import apps, programs
lazy from desktop_ui import island_layout, island_menu, island_model, island_motion
lazy from desktop_ui.bar_events import BarSpec
lazy from desktop_ui.components import appearance
lazy from desktop_ui.desktop_app import run
lazy from desktop_ui.desktop_settings import DesktopSettings


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Workspace only runs on Windows")
    bar = BarSpec(
        island_model.ISLAND,
        island_menu.CONTROLS,
        island_motion.SPRINGS,
        island_motion.TIMING,
        island_layout.SIZES,
        appearance.GLASS,
        appearance.WASHES,
        title="Workspace floating bar",
    )
    run(DesktopSettings(programs=programs.PROGRAMS, places=Places.of(os.environ, programs.PROGRAMS), apps=apps.APPS, bar=bar))


if __name__ == "__main__":
    main()
