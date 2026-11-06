"""What one edit check asks its executors to run, and what they report back.

Shared by the in-process executor in scripts.check and the Windows runner in
scripts.check_native.
"""

import traceback
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Selection:
    tests: tuple[str, ...]
    changed: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class Failure:
    """A failed test, import or check step.

    The node and summary identify it in the retained cost record; the report
    is the complete console text and is never recorded.
    """

    node: str
    summary: str
    report: str


@dataclass(frozen=True, slots=True)
class Results:
    """Counts, failures and labelled durations from one executor."""

    passed: int
    skipped: int
    failures: tuple[Failure, ...]
    durations: tuple[tuple[float, str], ...]


ROOT = Path(__file__).resolve().parent.parent


def raised_at(error: BaseException) -> str:
    """Where in Workspace's source the error was raised, innermost: `path:line`, or "" outside it.

    The retained record keeps only the summary; without this a flaky failure
    (a bare TimeoutError) can't be located once the console is gone."""
    inside = (frame for frame in reversed(traceback.extract_tb(error.__traceback__)) if Path(frame.filename).resolve().is_relative_to(ROOT))
    return next((f"{Path(frame.filename).resolve().relative_to(ROOT).as_posix()}:{frame.lineno}" for frame in inside), "")


def raised(node: str, error: BaseException, output: str = "") -> Failure:
    """Report an exception with the stderr its step wrote before failing, and where it was raised."""
    name = type(error).__qualname__
    message = str(error)
    captured = f"\nCaptured stderr:\n{output}" if output else ""
    where = f" at {at}" if (at := raised_at(error)) else ""
    return Failure(node, (f"{name}: {message}" if message else name) + where, f"{node}\n{''.join(traceback.format_exception(error))}{captured}")


def reported(node: str, report: str) -> Failure:
    """Adapt a free-text problem, such as selfcheck's, under the step that found it."""
    return Failure(node, report.partition("\n")[0], report)
