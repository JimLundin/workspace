"""Run Workspace's desktop: `pythonw -m desktop`. `launch.py` starts it with the gateway and the layout.

The desktop owns the bar, the tray, window placement, dictation and meetings.
Quit in its tray menu quits Workspace.
"""

import os
import sys

from protocol import Places
from settings import apps, programs
lazy from desktop_ui import (
    desktop_control,
    island_layout,
    island_menu,
    island_model,
    island_motion,
    key_hint_overlay,
    keymap_views,
    layer_indicator,
    shell_items,
    tray,
    window_layout,
    window_switcher,
)
lazy from desktop_ui.application_observer import PlacementSpec
lazy from desktop_ui.bar_events import BarSpec
lazy from desktop_ui.components import appearance, typeface
lazy from desktop_ui.desktop_app import run
lazy from desktop_ui.desktop_settings import DesktopSettings


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Workspace only runs on Windows")
    design = appearance.Design(palette=appearance.PALETTE, glass=appearance.GLASS, kit=appearance.KIT, type=typeface.TYPE)
    bar = BarSpec(
        island=island_model.ISLAND,
        controls=island_menu.CONTROLS,
        springs=island_motion.SPRINGS,
        timing=island_motion.TIMING,
        sizes=island_layout.SIZES,
        glass=design.glass,
        palette=design.palette,
        washes=appearance.WASHES,
        title="Workspace floating bar",
    )
    places = Places.of(os.environ, programs.PROGRAMS)
    run(
        DesktopSettings(
            programs=programs.PROGRAMS,
            places=places,
            apps=apps.APPS,
            design=design,
            bar=bar,
            badges=key_hint_overlay.BADGES,
            keymap=keymap_views.KEYMAP,
            indicator=layer_indicator.INDICATOR,
            switcher=window_switcher.SWITCHER,
            tray=tray.TRAY_ICON,
            tray_menu=desktop_control.TRAY_MENU,
            placement=PlacementSpec(setups=window_layout.SETUPS, web_apps=shell_items.WEB_APPS, launch_grace=15.0, recent=32),
        )
    )


if __name__ == "__main__":
    main()
