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

CHECK_PROCESS: Final = "runs real check subprocesses (selfcheck or scripts.check) on a temporary tree; the defect is in that process boundary"
REAL_GIT: Final = "drives real git repositories; the defect is in how publication or versions use git"

SLOW: Final[frozendict[str, str]] = frozendict(
    {
        "tests/test_agent.py::test_apply_needs_a_passing_check_of_exactly_these_changes": CHECK_PROCESS,
        "tests/test_agent.py::test_runtime_failure_returns_to_the_agent_to_fix_before_installing": CHECK_PROCESS,
        "tests/test_architecture.py::test_explicit_test_scope_cannot_bypass_architecture_or_write_a_receipt": CHECK_PROCESS,
        "tests/test_computer_tools.py::test_automatic_and_explicit_screenshots_share_the_same_history_limit": (
            "three full agent runs fill the screenshot history past its limit"
        ),
        "tests/test_keeper.py::test_a_deploy_without_a_keeper_installs_a_version_undo_can_restore": REAL_GIT,
        "tests/test_keeper.py::test_versions_install_and_restore_exact_bytes_beside_an_untouched_runtime": REAL_GIT,
        "tests/test_meetings.py::test_recording_and_transcription_continue_while_the_markdown_file_is_locked": (
            "waits through the meeting service's real publish pacing while the transcript is locked"
        ),
        "tests/test_meetings.py::test_slow_transcription_does_not_block_capture_stop_or_shutdown": (
            "waits through the meeting service's real publish pacing beside a slow transcription"
        ),
        "tests/test_publishing.py::test_an_installed_change_lands_on_main_once_and_never_over_newer_work": REAL_GIT,
        "tests/test_publishing.py::test_durable_publication_records_before_candidate_code_and_remote_push": REAL_GIT,
        "tests/test_publishing.py::test_failed_checks_and_diverged_base_refuse_publication": REAL_GIT,
        "tests/test_publishing.py::test_git_commits_land_in_the_named_folder_whatever_repository_the_parent_locates": (
            "starts a fresh interpreter so git sees only the environment it is given"
        ),
        "tests/test_quality.py::test_explicit_test_scope_cannot_bypass_quality_or_write_a_receipt": CHECK_PROCESS,
        "tests/test_quality.py::test_standards_fail_on_a_lint_error_outside_the_selected_tests_before_tests_or_a_receipt": CHECK_PROCESS,
        "tests/test_restart_plan.py::test_restart_plan_tracks_shared_removed_lazy_and_package_dependencies": (
            "parses 14 source trees' import graphs, one per restart case"
        ),
        "tests/test_self_review.py::test_history_tool_pages_day_and_recent_then_drills_into_diagnostics": (
            "several SDK turns against the fake endpoint, one per history page"
        ),
        "tests/test_selfcheck.py::test_a_change_runs_only_the_tests_that_import_it": CHECK_PROCESS,
        "tests/test_selfcheck.py::test_fast_checks_defer_native_tests_but_the_default_install_gate_runs_them": CHECK_PROCESS,
        "tests/test_selfcheck.py::test_fast_checks_still_compile_native_tests_and_import_production_modules": CHECK_PROCESS,
        "tests/test_selfcheck.py::test_worker_modules_report_their_passes_and_failures": CHECK_PROCESS,
        "tests/test_source_analysis.py::test_cached_quality_cannot_accept_changed_boolean_signature_or_import_ownership": (
            "real Ruff scans, before and after an edit"
        ),
        "tests/test_work_execution.py::test_cancelling_a_check_terminates_its_candidate_process": CHECK_PROCESS,
        "tests/test_work_execution.py::test_runtime_checks_are_recorded_before_candidate_import_and_failures_remain_fixable": CHECK_PROCESS,
        "tests/test_work_submissions.py::test_unrelated_failures_cannot_evict_a_watched_identity_collision": (
            "300 submissions, enough to pass the 256-problem limit"
        ),
        "tests/test_workspace.py::test_check_runs_selfcheck_on_the_workspace": CHECK_PROCESS,
        "tests/test_workspace.py::test_editing_checks_fail_on_the_standards_report_after_tests_pass": CHECK_PROCESS,
        "tests/test_workspace.py::test_runtime_checks_cannot_change_the_source_that_was_checked": CHECK_PROCESS,
        "tests/test_selfcheck.py::test_parallel_native_lanes_report_each_lanes_passes_failures_and_crashes": CHECK_PROCESS,
    }
)
"""Portable tests allowed over the editing budget, each with why it can't be faster.

They run with --native and --full. Before adding one, make it faster: a real
wait, sleep or retry backoff usually has a seam that removes it."""

SLOW_CAP: Final = 30
"""At most this many slow portable tests: adding one beyond it means removing or fixing another."""

NATIVE_BUDGET_S: Final = 3.0
"""A native test that takes longer fails --native and --full by name, unless NATIVE_SLOW lists it.

Native tests run in parallel lanes beside other work, so the budget sits well
above what a cheap native test takes there."""

NATIVE_SLOW: Final[frozendict[str, str]] = frozendict(
    {
        "tests/test_windows_recording.py::test_meeting_service_saves_speech_after_a_microphone_dropout": (
            "waits through the meeting service's real 2 s publish pacing; a pacing seam would remove it"
        ),
        "tests/test_windows_browser.py::test_attached_browser_dom_tabs_and_cancellation_share_a_personal_browser": (
            "a real personal Edge reached over CDP"
        ),
        "tests/test_windows_browser.py::test_managed_browser_dom_teams_persistence_and_cancellation": (
            "one managed Edge launch shared by DOM, Teams, business apps, meeting detection and cancellation"
        ),
        "tests/test_windows_computer.py::test_powershell_preserves_utf8_large_scripts_cwd_and_failure_status": (
            "real PowerShell runs: UTF-8, large scripts and exit codes"
        ),
        "tests/test_windows_computer.py::test_uia_controls_are_inspected_and_operated_across_separate_processes": (
            "a WPF window in PowerShell, inspected and operated through UI Automation across processes"
        ),
        "tests/test_windows_development.py::test_native_check_reviews_source_once_across_desktop_handoff": (
            "a real native check handed to a private desktop"
        ),
        "tests/test_windows_development.py::test_watch_rechecks_fresh_source_and_retains_baseline_after_failed_edits": (
            "real file watching and checks after each save"
        ),
        "tests/test_windows_run_alone.py::test_the_assistant_runs_reports_ready_and_quits_with_no_desktop": (
            "the whole assistant starts and quits in a fresh interpreter"
        ),
        "tests/test_windows_run_alone.py::test_the_desktop_runs_reports_ready_and_quits_with_no_assistant": (
            "the whole desktop starts and quits in a fresh interpreter"
        ),
        "tests/test_windows_runtime.py::test_keeper_allows_owned_cleanup_longer_than_five_seconds": ("waits past the keeper's real 5 s close grace"),
        "tests/test_windows_test_desktop.py::test_desktop_bootstrap_preserves_arguments_streams_and_failure_status": (
            "relaunches Python onto a private desktop"
        ),
    }
)
"""Native tests allowed over the native budget, each with the real thing only it can show."""

NATIVE_SLOW_CAP: Final = 12
"""At most this many slow native tests."""


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
