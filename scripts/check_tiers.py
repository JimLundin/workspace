"""Which tests the editing check runs, and the time each may take there.

The editing tier runs the affected portable tests. Native modules
(tests/test_windows_*.py) and the slow portable tests below run only with
--native or --full, before a merge or a deploy.
"""

import ast
from pathlib import Path
from typing import Final

from scripts.check_results import Failure, Selection

BUDGET_S: Final = 1.0
"""A test in a narrow editing check that takes longer fails the check by name.

Only a narrow check runs its tests one at a time beside a small type check;
a broad run's worker pool and whole-diff pyright slow every test, and timing
there blamed tests that take 0.3 s alone.
"""

SLOW: Final = frozenset(
    {
        "tests/test_agent.py::test_agent_preserves_reasoning_between_tool_calls_and_follow_ups",
        "tests/test_agent.py::test_apply_needs_a_passing_check_of_exactly_these_changes",
        "tests/test_agent.py::test_failed_turn_keeps_completed_actions_for_the_follow_up",
        "tests/test_agent.py::test_permanent_and_exhausted_endpoint_failures_end_the_turn",
        "tests/test_agent.py::test_runtime_failure_returns_to_the_agent_to_fix_before_installing",
        "tests/test_agent.py::test_the_agent_edits_checks_and_applies_a_change",
        "tests/test_agent.py::test_transient_endpoint_failures_resume_without_repeating_completed_effects",
        "tests/test_architecture.py::test_explicit_test_scope_cannot_bypass_architecture_or_write_a_receipt",
        "tests/test_computer_tools.py::test_automatic_and_explicit_screenshots_share_the_same_history_limit",
        "tests/test_feed_dates.py::test_a_new_day_reconsiders_cached_work_without_a_new_notification",
        "tests/test_feed_triage_service.py::test_only_reviewed_actionable_notifications_activate_work_with_retry",
        "tests/test_keeper.py::test_a_deploy_without_a_keeper_installs_a_version_undo_can_restore",
        "tests/test_keeper.py::test_versions_install_and_restore_exact_bytes_beside_an_untouched_runtime",
        "tests/test_llm.py::test_failures_for_an_unreachable_endpoint",
        "tests/test_meetings.py::test_batch_reads_capture_completion_and_audio_from_one_snapshot",
        "tests/test_meetings.py::test_recording_and_transcription_continue_while_the_markdown_file_is_locked",
        "tests/test_meetings.py::test_slow_transcription_does_not_block_capture_stop_or_shutdown",
        "tests/test_project_context.py::test_context_capacity_rejects_new_records_but_allows_existing_edits",
        "tests/test_publishing.py::test_an_installed_change_lands_on_main_once_and_never_over_newer_work",
        "tests/test_publishing.py::test_durable_publication_records_before_candidate_code_and_remote_push",
        "tests/test_publishing.py::test_failed_checks_and_diverged_base_refuse_publication",
        "tests/test_publishing.py::test_git_commits_land_in_the_named_folder_whatever_repository_the_parent_locates",
        "tests/test_quality.py::test_explicit_test_scope_cannot_bypass_quality_or_write_a_receipt",
        "tests/test_quality.py::test_standards_fail_on_a_lint_error_outside_the_selected_tests_before_tests_or_a_receipt",
        "tests/test_restart_plan.py::test_restart_plan_tracks_shared_removed_lazy_and_package_dependencies",
        "tests/test_self_review.py::test_history_tool_pages_day_and_recent_then_drills_into_diagnostics",
        "tests/test_selfcheck.py::test_a_change_runs_only_the_tests_that_import_it",
        "tests/test_selfcheck.py::test_fast_checks_defer_native_tests_but_the_default_install_gate_runs_them",
        "tests/test_selfcheck.py::test_worker_modules_report_their_passes_and_failures",
        "tests/test_source_analysis.py::test_cached_quality_cannot_accept_changed_boolean_signature_or_import_ownership",
        "tests/test_work_execution.py::test_cancelling_a_check_terminates_its_candidate_process",
        "tests/test_work_execution.py::test_endpoint_failure_and_step_limit_never_report_completion",
        "tests/test_work_execution.py::test_runtime_checks_are_recorded_before_candidate_import_and_failures_remain_fixable",
        "tests/test_work_execution.py::test_sdk_history_and_source_drafts_are_scoped_to_the_conversation",
        "tests/test_work_submissions.py::test_unrelated_failures_cannot_evict_a_watched_identity_collision",
        "tests/test_workspace.py::test_check_runs_selfcheck_on_the_workspace",
        "tests/test_workspace.py::test_editing_checks_fail_on_the_standards_report_after_tests_pass",
        "tests/test_workspace.py::test_runtime_checks_cannot_change_the_source_that_was_checked",
    }
)
"""Portable tests measured over 0.9 s alone, or over the budget in narrow checks, on the development laptop."""


def test_functions(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    return tuple(node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"))


def editing(selection: Selection, root: Path) -> Selection:
    """The selection without native modules and slow tests; a module with slow tests is named by its other tests."""
    modules = {test.partition("::")[0] for test in SLOW}
    tests: list[str] = []
    for selector in selection.tests:
        if Path(selector).name.startswith("test_windows_") or selector in SLOW:
            continue
        if selector in modules:
            tests.extend(f"{selector}::{name}" for name in test_functions(root / selector) if f"{selector}::{name}" not in SLOW)
        else:
            tests.append(selector)
    return Selection(tuple(tests), selection.changed, selection.reason)


def node(label: str) -> str | None:
    """The test selector a duration label times, or None for a phase or module import."""
    label = label.removeprefix("worker:")
    if label.startswith(("phase:", "module:")):
        return None
    module, _, function = label.rpartition(".")
    return f"{module.replace('.', '/')}.py::{function}" if function.startswith("test_") else None


def over_budget(durations: tuple[tuple[float, str], ...]) -> tuple[Failure, ...]:
    failures: list[Failure] = []
    for seconds, label in durations:
        selector = node(label)
        if selector is not None and seconds > BUDGET_S:
            summary = f"took {seconds:.1f} s, over the {BUDGET_S:.0f} s editing budget"
            report = f"{selector} {summary}. Make it faster, or add it to SLOW in scripts/check_tiers.py so it runs with --native and --full."
            failures.append(Failure(selector, summary, report))
    return tuple(failures)
