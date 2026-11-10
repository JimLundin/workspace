"""Run the layout: `pythonw -m keyboard` (or double-click `keyboard.pyw`).

Set the Windows keyboard to English (US). The key left of 1 (§) is the escape
key: tap it to switch between this layout and your plain keyboard, hold it for
2 seconds to quit. Spacebar holds dictation; B toggles dictation.
Both need the assistant, started by `launch.py`.
"""

import os
import sys

from protocol import Places
from settings import layout, programs
lazy from keyboard.win import Exit, run, show_error


def main() -> None:
    if sys.platform != "win32":
        sys.exit("keyboard only runs on Windows")
    match run(layout.LAYOUT, programs.PROGRAMS, Places.of(os.environ, programs.PROGRAMS)):
        case Exit.QUIT:
            sys.exit(0)  # a normal quit: the assistant doesn't restart the layout
        case Exit.ALREADY_RUNNING:
            show_error("The Workspace keyboard is already running.")
            sys.exit(0)
        case Exit.HOOK_REFUSED:
            show_error("Windows refused the keyboard hook.")
            sys.exit(2)


if __name__ == "__main__":
    main()
