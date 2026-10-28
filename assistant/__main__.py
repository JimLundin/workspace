"""Run Workspace: `pythonw -m assistant` (or double-click `workspace.pyw`). It starts
the layout too, puts an icon in the notification area, and runs until you choose
Quit there. See the README for the keys and the settings.
"""

import os
import sys

from assistant.lifecycle import Timings
from assistant.llm import settings_from
from runtime import activate
lazy from assistant.app import Exit, run, show_error

activate()


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Workspace only runs on Windows")
    timings = Timings("startup")
    timings.mark("application imports")
    match run(settings_from(os.environ), timings=timings):
        case Exit.QUIT:
            pass
        case Exit.ALREADY_RUNNING:
            show_error("Workspace is already running (its icon is in the notification area).")


if __name__ == "__main__":
    main()
