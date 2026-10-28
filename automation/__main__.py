"""Start the supervised work process with the pinned runtime."""

import os
import sys

from runtime import activate
lazy from assistant.llm import settings_from
lazy from automation.app import report, run


def main() -> None:
    if sys.platform != "win32":
        sys.exit("the work process only runs on Windows")
    activate()
    try:
        run(settings_from(os.environ))
    except Exception as error:
        report(f"Work process stopped: {type(error).__name__}.")
        print(f"Work process stopped ({type(error).__name__}); see workspace/work/worker.log and the work overview.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
