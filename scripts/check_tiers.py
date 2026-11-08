"""Which tests the editing check runs, and the time each may take there.

The editing tier runs the affected portable tests. Native modules
(tests/test_windows_*.py) and the slow portable tests below run only with
--native or --full, before a merge or a deploy.
"""

import ast
from pathlib import Path
from typing import Final

from scripts.check_results import Failure, Selection

BUDGET_S: Final = 1.5
"""A test in a narrow editing check that takes longer fails the check by name.

Only a narrow check runs its tests one at a time beside a small type check;
a broad run's worker pool and whole-diff pyright slow every test, and timing
there blamed tests that take 0.3 s alone. Tests that take 0.5 s warm took up
to 1.3 s on the first run after a commit, so the budget sits above that and
SLOW below it.
"""

CHECK_PROCESS: Final = "runs real check subprocesses on a temporary tree; the defect is in that process boundary"

SLOW: Final[frozendict[str, str]] = frozendict(
    {
        "tests/test_architecture.py::test_explicit_test_scope_cannot_bypass_architecture_or_write_a_receipt": CHECK_PROCESS,
        "tests/test_meetings.py::test_recording_and_transcription_continue_while_the_markdown_file_is_locked": (
            "waits through the meeting service's real publish pacing while the transcript is locked"
        ),
        "tests/test_meetings.py::test_slow_transcription_does_not_block_capture_stop_or_shutdown": (
            "waits through the meeting service's real publish pacing beside a slow transcription"
        ),
        "tests/test_quality.py::test_explicit_test_scope_cannot_bypass_quality_or_write_a_receipt": CHECK_PROCESS,
        "tests/test_quality.py::test_standards_fail_on_a_lint_error_outside_the_selected_tests_before_tests_or_a_receipt": CHECK_PROCESS,
        "tests/test_source_analysis.py::test_cached_quality_cannot_accept_changed_boolean_signature_or_import_ownership": (
            "real Ruff scans, before and after an edit"
        ),
    }
)
"""Portable tests allowed over the editing budget, each with why it can't be faster.

They run with --native and --full. Before adding one, make it faster: a real
wait, sleep or retry backoff usually has a seam that removes it."""

NATIVE_BUDGET_S: Final = 3.0
"""A native test that takes longer fails --native and --full by name, unless NATIVE_SLOW lists it.

Native tests run in parallel lanes beside other work, so the budget sits well
above what a cheap native test takes there."""

NATIVE_SLOW: Final[frozendict[str, str]] = frozendict()
"""Native tests allowed over the native budget, each with the real thing only it can show."""


def test_functions(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    return tuple(node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"))


def editing(selection: Selection, root: Path) -> Selection:
    """The selection without native modules and slow tests; a module with slow tests is named by its other tests."""
    modules = {test.partition("::")[0] for test in SLOW}
    kept = (selector for selector in selection.tests if not Path(selector).name.startswith("test_windows_") and selector not in SLOW)
    tests = tuple(
        test
        for selector in kept
        for test in (
            (f"{selector}::{name}" for name in test_functions(root / selector) if f"{selector}::{name}" not in SLOW)
            if selector in modules
            else (selector,)
        )
    )
    return Selection(tests, selection.changed, selection.reason)


def node(label: str) -> str | None:
    """The test selector a duration label times, or None for a phase or module import."""
    label = label.removeprefix("worker:")
    if label.startswith(("phase:", "module:")):
        return None
    module, _, function = label.rpartition(".")
    return f"{module.replace('.', '/')}.py::{function}" if function.startswith("test_") else None


def over_budget(durations: tuple[tuple[float, str], ...]) -> tuple[Failure, ...]:
    """Editing tests over the editing budget, by name."""
    return tuple(
        Failure(
            selector,
            f"took {seconds:.1f} s, over the {BUDGET_S:g} s editing budget",
            f"{selector} took {seconds:.1f} s, over the {BUDGET_S:g} s editing budget. "
            "Make it faster, or list it with its reason in SLOW in scripts/check_tiers.py so it runs with --native and --full.",
        )
        for seconds, label in durations
        if (selector := node(label)) is not None and seconds > BUDGET_S
    )


def over_native_budget(durations: tuple[tuple[float, str], ...]) -> tuple[Failure, ...]:
    """Native tests over the native budget that NATIVE_SLOW doesn't list, by name."""
    return tuple(
        Failure(
            selector,
            f"took {seconds:.1f} s, over the {NATIVE_BUDGET_S:g} s native budget",
            f"{selector} took {seconds:.1f} s, over the {NATIVE_BUDGET_S:g} s native budget. Make it faster (share an expensive "
            "launch with a neighbouring test, or test its decision portably), or list it with its reason in NATIVE_SLOW.",
        )
        for seconds, label in durations
        if (selector := node(label)) is not None
        and Path(selector.partition("::")[0]).name.startswith("test_windows_")
        and seconds > NATIVE_BUDGET_S
        and selector not in NATIVE_SLOW
    )
