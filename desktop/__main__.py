"""Run Workspace's desktop: `pythonw -m desktop`. `launch.py` starts it with the gateway and the layout.

This composes the desktop (`desktop_ui`) with the assistant (`assistant`), which
runs on its own thread in the same process; the two never import each other.
Quit in its tray menu quits Workspace.
"""

import os
import sys

lazy from assistant import app
lazy from assistant.llm import settings_from
lazy from components import endpoint
lazy from desktop_ui.desktop_app import run


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Workspace only runs on Windows")
    run(lambda publish: app.start(settings_from(os.environ, endpoint("gateway")), publish))


if __name__ == "__main__":
    main()
