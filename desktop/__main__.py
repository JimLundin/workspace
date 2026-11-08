"""Run Workspace's desktop: `pythonw -m desktop`. `launch.py` starts it with the gateway and the layout.

The desktop owns the bar, the tray, window placement, dictation and meetings.
Quit in its tray menu quits Workspace.
"""

import sys

lazy from desktop_ui.desktop_app import run


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Workspace only runs on Windows")
    run()


if __name__ == "__main__":
    main()
