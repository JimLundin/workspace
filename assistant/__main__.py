"""Run the assistant: `pythonw -m assistant`. It has no window of its own: the
desktop (`python -m desktop`) shows its work over a loopback link, and either runs
without the other. `launch.py` starts both, with the gateway and
the layout. See the README for the keys and the settings.
"""

import os
import sys

from assistant.lifecycle import Timings
from assistant.llm import settings_from
from components import endpoint
lazy from assistant.app import Exit, run, show_error


def main() -> None:
    if sys.platform != "win32":
        sys.exit("Workspace only runs on Windows")
    timings = Timings("startup")
    timings.mark("application imports")
    match run(settings_from(os.environ, endpoint("gateway")), timings=timings):
        case Exit.QUIT:
            pass
        case Exit.ALREADY_RUNNING:
            show_error("The Workspace assistant is already running.")


if __name__ == "__main__":
    main()
