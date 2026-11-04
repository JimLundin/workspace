"""The agent's review of its own runs and the lessons it keeps, through the runner and its tools."""

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from assistant.agent_execution import AgentExecution
from assistant.llm import Settings
from assistant.task_profiles import GeneralEffects, Profiles, unseen
from assistant.workspace import Workspace
from automation.context import ContextStore, Preference
from automation.execution import Log
from automation.self_review import ReviewingRunner, TaskRecord, describe_history, describe_history_page
from automation.store import TaskStore
from automation.task import (
    Action,
    ActionOutcome,
    ActionPending,
    ActionReturned,
    ActionSpec,
    ActionVerified,
    Blocked,
    Claim,
    Completed,
    Failed,
    Outcome,
    Question,
    RequestSource,
    SelfReview,
    Waiting,
)
from tests.fake_endpoint import fake_endpoint
from tests.test_agent import FakeMachine, FakeWindow, calls, no_feed, says
from tests.test_workspace import live_tree

NOW = datetime(2026, 11, 3, 9, 30).astimezone()


class Settles:
    """A runner whose run ends with a chosen outcome."""

    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome

    def run_work(self, claim: Claim, store: TaskStore, log: Log, stop: threading.Event) -> Outcome:
        return self.outcome


def settle(store: TaskStore, identity: str, outcome: Outcome, source: RequestSource | None = None, *, revised: str = "") -> None:
    at = NOW.timestamp()
    store.submit(identity, "Requested work", "Do the work.", source or RequestSource("chat"), at=at)
    if revised:
        assert store.revise(identity, revised, at=at) is not None
    claim = store.claim("worker", identity + "-run", at=at)
    assert claim is not None and claim.task.id == identity
    result = ReviewingRunner(Settles(outcome), lambda: NOW).run_work(claim, store, FakeWindow(), threading.Event())
    assert store.finish(claim.run, result, at=at) is not None


def reviews(store: TaskStore) -> list[tuple[str, str]]:
    return sorted(
        (task.id, task.source.profile.subject)
        for task in store.list_tasks()
        if isinstance(task.source, RequestSource) and isinstance(task.source.profile, SelfReview)
    )


def test_only_settled_runs_with_evidence_of_a_problem_are_reviewed(tmp_path: Path) -> None:
    # Defect: every run spends a review, a run still waiting on the user is reviewed
    # before it settles, or failures and goal corrections go unreviewed.
    store = TaskStore(tmp_path / "work.sqlite3")
    settle(store, "clean", Completed("Done.", ()))
    settle(store, "waiting", Waiting(Question("q", "Which folder?", "")))
    settle(store, "failed", Failed("The report could not be found."))
    settle(store, "redirected", Completed("Done.", ()), revised="Do it in the Finance folder instead.")
    assert [subject for _, subject in reviews(store)] == ["failed", "redirected"]
    prompts = {
        task.source.profile.subject: task.prompt
        for task in store.list_tasks()
        if isinstance(task.source, RequestSource) and isinstance(task.source.profile, SelfReview)
    }
    assert "the task failed" in prompts["failed"] and "the user revised the goal" in prompts["redirected"]


def test_a_review_is_never_reviewed_and_each_day_is_reviewed_once(tmp_path: Path) -> None:
    # Defect: a blocked review queues a review of itself without end, or every run
    # after midnight queues another review of the previous day.
    store = TaskStore(tmp_path / "work.sqlite3")
    yesterday = (NOW - timedelta(days=1)).timestamp()
    store.submit("earlier", "Earlier work", "Do the earlier work.", RequestSource("chat"), at=yesterday)
    earlier = store.claim("worker", "earlier-run", at=yesterday)
    assert earlier is not None and store.finish(earlier.run, Completed("Done.", ()), at=yesterday) is not None
    settle(store, "review", Waiting(Blocked("Stopped.")), RequestSource("self-review", SelfReview("earlier")))
    assert reviews(store) == [("review", "earlier")]
    settle(store, "first", Completed("Done.", ()))
    settle(store, "second", Completed("Done.", ()))
    assert reviews(store) == [("review", "earlier"), ("self-review:day:2026-11-02", "2026-11-02")]


def test_history_shows_what_went_wrong_in_each_task(tmp_path: Path) -> None:
    # Defect: the review cannot see the failure, the user's correction or the
    # question it asked, so it has nothing to learn from.
    store = TaskStore(tmp_path / "work.sqlite3")
    settle(store, "failed", Failed("The report could not be found."), revised="Use the Finance folder.")
    task = store.get("failed")
    assert task is not None
    text = describe_history((TaskRecord(task, store.actions(task.id), store.revisions(task.id), store.responses(task.id)),))
    assert "failed: The report could not be found." in text
    assert "Goal revision 1: Use the Finance folder." in text


def test_history_preserves_install_evidence_and_unsettled_actions(tmp_path: Path) -> None:
    # Defect: a stopped task hides its successful install and returned failures,
    # making reviews confuse conversation status with the actual repair outcome.
    store = TaskStore(tmp_path / "work.sqlite3")
    settle(store, "stopped", Waiting(Blocked("Stopped.")))
    task = store.get("stopped")
    assert task is not None
    outcomes: tuple[ActionOutcome, ...] = (
        ActionVerified("Installed and pushed as abc123."),
        ActionReturned("Command exited with code 1; effect not verified."),
        ActionPending.RUNNING,
    )
    actions = tuple(
        Action(f"action-{index}", task.id, "original-run", ActionSpec("apply_changes", "Install", "a" * 64), 1, 2, outcome)
        for index, outcome in enumerate(outcomes)
    )
    text = describe_history((TaskRecord(task, actions, store.revisions(task.id), ()),))
    assert "Installed and pushed as abc123." in text
    assert "Command exited with code 1; effect not verified." in text
    assert "No settled outcome recorded." in text
    assert "action-0; run original-run" in text
    assert "1 returned, 1 running, 1 verified" in text


def test_summary_pages_keep_whole_outcomes_and_explicit_continuation(tmp_path: Path) -> None:
    # Defect: long results truncate later identities, recent is ignored, or paging
    # skips an outcome. Summary enumeration must not load verbose action records.
    store = TaskStore(tmp_path / "work.sqlite3")
    for index in range(23):
        store.submit(f"task-{index:02}", "Requested work", "Do it.", RequestSource("chat"), at=NOW.timestamp() + index)
    tasks = store.list_tasks()
    first = describe_history_page(tasks, 0, 100)
    second = describe_history_page(tasks, 20, 100)
    assert first.count("## ") == 20 and "next_offset: 20" in first
    assert second.count("## ") == 3 and "next_offset: none" in second
    assert "task-03:" in first and "task-02:" not in first
    assert "task-02:" in second and "task-03:" not in second
    assert describe_history_page(tasks, 0, 2).count("## ") == 2
    assert "No tasks match." in describe_history_page(tasks, 23, 2)


def test_history_tool_pages_day_and_recent_then_drills_into_diagnostics(tmp_path: Path) -> None:
    # Defect: tool wiring ignores day page size/offset or replaces task diagnostics
    # with summaries, leaving daily reviews without a route to their evidence.
    store = TaskStore(tmp_path / "work.sqlite3")
    settle(store, "failed", Failed("Missing report."), revised="Use Finance.")
    store.submit("older", "Old work", "Old goal.", RequestSource("chat"), at=(NOW - timedelta(days=2)).timestamp())
    machine, errors = FakeMachine(), list[str]()
    with fake_endpoint() as endpoint:
        execution = AgentExecution(
            Settings(endpoint.url, "fixture", "transcribe", "", ""),
            machine,
            Profiles(Workspace(live_tree(tmp_path / "live"), tmp_path / "workspace"), GeneralEffects(unseen, no_feed, ContextStore(store.path))),
            record=lambda _record: None,
            report_error=errors.append,
            close_background=machine.close_background,
        )
        endpoint.replies = [
            calls(("work_history", {"day": "2026-11-03", "recent": 1})),
            calls(("work_history", {"day": "2026-11-03", "recent": 1, "offset": 1})),
            calls(("work_history", {"recent": 1})),
            calls(("work_history", {"task_id": "failed"})),
            says("Reviewed."),
        ]
        store.submit("inspection", "Inspection", "Read history.", RequestSource("self-review", SelfReview("day")), at=NOW.timestamp(), priority=10)
        claim = store.claim("worker", "inspection-run", at=NOW.timestamp())
        assert claim is not None and claim.task.id == "inspection"
        outcome = execution.run_work(claim, store, FakeWindow(), threading.Event())
    assert isinstance(outcome, Completed), (outcome, errors)
    bodies = tuple(request.body.decode("utf-8") for request in endpoint.received)
    assert "failed: Missing report." in bodies[1] and "next_offset: none" in bodies[1]
    assert "Goal revision 1: Use Finance." not in bodies[1]
    assert "No tasks match." in bodies[2]
    assert "next_offset: 1" in bodies[3]
    assert "Goal revision 1: Use Finance." in bodies[4]
    assert "Detail coverage: newest 100 actions" in bodies[4]


def test_saved_lessons_are_verified_and_user_preferences_stay_the_users(tmp_path: Path) -> None:
    # Defect: a saved lesson stays unverified so the task cannot complete, or the
    # agent overwrites or removes a preference the user wrote.
    store = TaskStore(tmp_path / "work.sqlite3")
    lessons = ContextStore(tmp_path / "work.sqlite3")
    lessons.save(Preference("mine", "Reports", "Save reports as PDF.", "Work panel", 1))
    machine, errors = FakeMachine(), list[str]()
    with fake_endpoint() as endpoint:
        execution = AgentExecution(
            Settings(endpoint.url, "fixture", "transcribe", "", ""),
            machine,
            Profiles(Workspace(live_tree(tmp_path / "live"), tmp_path / "workspace"), GeneralEffects(unseen, no_feed, lessons)),
            record=lambda _record: None,
            report_error=errors.append,
            close_background=machine.close_background,
        )
        endpoint.replies = [
            calls(("save_lesson", {"name": "Outlook search", "rule": "Search Outlook by sender before subject."})),
            calls(("remove_lesson", {"id": "mine"})),
            says("Saved the lesson."),
        ]
        store.submit("task", "Requested work", "Remember to search Outlook by sender first.", RequestSource("chat"), at=time.time())
        claim = store.claim("worker", "run", at=time.time())
        assert claim is not None
        outcome = execution.run_work(claim, store, FakeWindow(), threading.Event())
    assert isinstance(outcome, Completed), (outcome, errors)
    saved = {record.id: record for record in lessons.list()}
    assert saved["mine"] == Preference("mine", "Reports", "Save reports as PDF.", "Work panel", 1)
    learned = [record for record in saved.values() if record.id != "mine"]
    assert [(record.name, record.value) for record in learned if isinstance(record, Preference)] == [
        ("Outlook search", "Search Outlook by sender before subject.")
    ]
    assert "only lessons you saved can be removed" in endpoint.received[-1].body.decode("utf-8")
