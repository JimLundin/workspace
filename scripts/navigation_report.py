"""Print the navigation report: what navigation cost and which layout change would have cost least.

python -m scripts.navigation_report [--days N] [--setup home|work|laptop_only]

It reads the navigation log read-only and changes nothing; docs/window-placement.md
explains the report.
"""

import argparse
import inspect
import sys
from datetime import datetime, timedelta
from pathlib import Path

from desktop_ui.navigation_log import NAVIGATION_LOG, rotated, setup_name
from desktop_ui.window_layout import Setup
from scripts.navigation_analysis import CHORDED, Log, read, report, selected


def lines(path: Path) -> tuple[str, ...]:
    return tuple(path.read_text(encoding="utf-8").splitlines()) if path.exists() else ()


def main() -> None:
    parser = argparse.ArgumentParser(description="Report what navigation cost and suggest layout changes.")
    parser.add_argument("--days", type=int, default=7, help="how many days back to read (default 7)")
    parser.add_argument("--setup", choices=("home", "work", "laptop_only"), help="only this monitor setup")
    parser.add_argument("--log", type=Path, default=NAVIGATION_LOG, help="the log; its rotated file is read first")
    match dict(inspect.getmembers(parser.parse_args())):
        case {"days": int() as days, "setup": (str() | None) as name, "log": Path() as log}:
            setup = next((setup for setup in Setup if setup_name(setup) == name), None)
        case _:
            parser.error("unexpected arguments")
    read_log = read((*lines(rotated(log)), *lines(log)))
    since = datetime.now().astimezone() - timedelta(days=days)
    entries = selected(read_log.entries, since, setup)
    sys.stdout.write(f"Navigation report, last {days} days, from {log}\n")
    sys.stdout.write(report(Log(entries, read_log.malformed), CHORDED))


if __name__ == "__main__":
    main()
