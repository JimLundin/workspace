"""Whole-tree lint, format and type standards for `Dev.cmd check`.

CI's standards job runs these tools against the native Windows dependencies.
The editing quality review runs only Ruff's signature rules, so without this
step type and lint errors anywhere else in the tree still produced receipts.
The protected selfcheck and CI keep their own unchanged invocations.
"""

import subprocess
import sys
import tempfile
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from scripts.check_results import Failure

# Whole-tree runs; a cold full pyright run measured 132 s from WSL source.
TIMEOUT = 600


@dataclass(frozen=True, slots=True)
class Standard:
    """One tool run over the checkout root; any nonzero exit fails the check."""

    node: str
    command: tuple[str, ...]


LINT = Standard("ruff check", (sys.executable, "-m", "ruff", "check", "--no-fix", "."))
FORMAT = Standard("ruff format", (sys.executable, "-m", "ruff", "format", "--check", "."))
# The same invocation as `Dev.cmd typecheck`: the development venv's dependencies.
TYPES = Standard("pyright", (sys.executable, "-m", "pyright", "--pythonpath", sys.executable))


def outcome(standard: Standard, status: int, output: str) -> tuple[Failure, ...]:
    if status == 0:
        return ()
    return (Failure(standard.node, f"{standard.node} exited with status {status}", f"{standard.node} failed:\n{output.strip()}"),)


def completed(standard: Standard, root: Path) -> tuple[Failure, ...]:
    result = subprocess.run(
        standard.command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=TIMEOUT
    )
    return outcome(standard, result.returncode, result.stdout + result.stderr)


def run(standards: Iterable[Standard], root: Path) -> tuple[Failure, ...]:
    """Fast standards, run in order before any test executes."""
    return tuple(failure for standard in standards for failure in completed(standard, root))


@contextmanager
def background(standard: Standard, root: Path) -> Generator[Callable[[], tuple[Failure, ...]]]:
    """Run a slow standard alongside the tests; collect it before publishing results.

    This owner holds the child process and its spooled output file. Output goes
    to a file rather than a pipe so a long report never blocks the child while
    tests run. A child still running at exit is killed.
    """
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(standard.command, cwd=root, stdout=output, stderr=subprocess.STDOUT)

        def collect() -> tuple[Failure, ...]:
            try:
                status = process.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return (Failure(standard.node, f"{standard.node} timed out", f"{standard.node} did not finish within {TIMEOUT} s."),)
            output.seek(0)
            return outcome(standard, status, output.read().decode("utf-8", errors="replace"))

        try:
            yield collect
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def unchecked() -> tuple[Failure, ...]:
    """The collector when this check was not asked to apply the standards."""
    return ()
