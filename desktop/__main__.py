"""Run the desktop: `pythonw -m desktop`. The keeper starts it with the assistant;
either runs without the other. Quit in its tray menu quits Workspace."""

import sys

from runtime import activate
lazy from desktop_ui.desktop_app import run

activate()


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Workspace only runs on Windows")
    run()


if __name__ == "__main__":
    main()
