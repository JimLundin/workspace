import os
import sys

from protocol import Places
from settings import layout, programs
lazy from keyboard.win import Exit, run, show_error


def main() -> None:
    if sys.platform != "win32":
        sys.exit("keyboard only runs on Windows")
    match run(
        layout.LAYOUT,
        programs.PROGRAMS,
        Places.of(os.environ, programs.PROGRAMS),
    ):
        case Exit.QUIT:
            sys.exit(0)
        case Exit.ALREADY_RUNNING:
            show_error("The Workspace keyboard is already running.")
            sys.exit(0)
        case Exit.HOOK_REFUSED:
            show_error("Windows refused the keyboard hook.")
            sys.exit(2)


if __name__ == "__main__":
    main()
