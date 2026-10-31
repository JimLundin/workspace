"""What one edit check asks its executors to run, and what they report back.

Shared by the in-process executor in scripts.check and the Windows runner in
scripts.check_native.
"""

import traceback
from dataclasses import dataclass


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


def raised(node: str, error: BaseException) -> Failure:
    name = type(error).__qualname__
    message = str(error)
    return Failure(node, f"{name}: {message}" if message else name, f"{node}\n{''.join(traceback.format_exception(error))}")


def reported(node: str, report: str) -> Failure:
    """Adapt a free-text problem, such as selfcheck's, under the step that found it."""
    return Failure(node, report.partition("\n")[0], report)
