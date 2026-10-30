"""A disposable component that announces its loaded source and exits cleanly."""

import sys
import time
from pathlib import Path


def main() -> None:
    match sys.argv:
        case [_, source, ready, stop]:
            Path(ready).write_text(Path(source).read_text(encoding="utf-8"), encoding="utf-8")
            while not Path(stop).exists():
                time.sleep(0.01)
        case _:
            raise ValueError("The fixture requires source, readiness and stop paths.")


if __name__ == "__main__":
    main()
