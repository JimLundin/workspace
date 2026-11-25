import os
import sys
from pathlib import Path

from protocol import Places, Tool, interpreter
from settings import apps, layout, programs
lazy from desktop import bar, look, placement, windows
lazy from desktop_ui.bar_events import BarSpec
lazy from desktop_ui.desktop_app import run
lazy from desktop_ui.desktop_settings import DesktopSettings, Launcher
lazy from desktop_ui.keymap import KeyboardView, shortcut_hint


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Workspace only runs on Windows")
    root = Path(__file__).resolve().parent.parent
    keyboard = KeyboardView.of(layout.LAYOUT, apps.APPS)
    hints = frozendict(
        {
            tool: shortcut_hint(keyboard.shortcut(tool), compact=True)
            for tool in Tool
        }
    )
    island = BarSpec(
        island=bar.ISLAND,
        controls=bar.CONTROLS,
        springs=bar.SPRINGS,
        timing=bar.TIMING,
        sizes=bar.SIZES,
        glass=look.DESIGN.glass,
        palette=look.DESIGN.palette,
        washes=look.WASHES,
        hints=hints,
    )
    run(
        DesktopSettings(
            programs=programs.PROGRAMS,
            places=Places.of(os.environ, programs.PROGRAMS),
            launcher=Launcher(
                (str(interpreter(root)), str(root / "launch.py")), root
            ),
            apps=apps.APPS,
            keyboard=keyboard,
            design=look.DESIGN,
            bar=island,
            badges=windows.BADGES,
            keymap=windows.KEYMAP,
            indicator=windows.INDICATOR,
            marker=windows.MARKER,
            switcher=windows.SWITCHER,
            tray=windows.TRAY_ICON,
            placement=placement.PLACEMENT,
            pager=bar.PAGER,
        )
    )


if __name__ == "__main__":
    main()
