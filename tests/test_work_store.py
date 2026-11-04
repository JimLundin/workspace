"""Durable work behavior through the real SQLite store and immutable values."""

import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest import TestCase

from automation.store import TaskStore
from automation.task import (
    ActionNotApplied,
    ActionReturned,
    ActionSpec,
    ActionUncertain,
    ActionVerified,
    Blocked,
    Completed,
    Control,
    Failed,
    FileDigest,
    Interrupted,
    Question,
    RequestSource,
    Running,
    RunRef,
    TaskStatus,
    TextAnswer,
    Until,
    Waiting,
)
from tests.work_fixture import seed_tasks


def specification(operation: str = "write notes") -> ActionSpec:
    return ActionSpec("write_file", "Update project notes", hashlib.sha256(operation.encode()).hexdigest(), ("project-notes",))


def test_submitted_work_survives_reopen_and_new_conversations(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    first = TaskStore(path)
    first.submit("draft", "Project briefing", "Prepare a project briefing.", RequestSource("morning-chat"), at=10)
    first.submit("review", "Review notes", "Review the saved meeting notes.", RequestSource("afternoon-chat"), at=20)
    reopened = TaskStore(path)
    claim = reopened.claim("worker", "briefing-run", at=30)
    assert claim is not None and claim.task.id == "draft"
    assert claim.task.prompt == "Prepare a project briefing."
    assert reopened.progress(claim.run, "Found the latest project notes.", at=31) is not None
    assert reopened.finish(claim.run, Completed("Briefing saved.", ("Read back the saved briefing.",)), at=32) is not None
    later = TaskStore(path)
    saved = later.get("draft")
    assert saved is not None and isinstance(saved.state, Completed)
    assert saved.checkpoint is not None and "latest project notes" in saved.checkpoint.summary
    second = later.claim("worker", "review-run", at=40)
    assert second is not None and second.task.id == "review"
    assert {task.id for task in later.list_tasks()} == {"draft", "review"}


def test_batch_reads_keep_requested_order_and_omit_missing_or_repeated_tasks(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    store = TaskStore(path)
    store.submit("older", "Older notes", "Review the earlier notes.", RequestSource("old-chat"), at=1)
    store.control("older", Control.PAUSE, at=2)
    store.submit("middle", "Meeting notes", "Summarize the meeting.", RequestSource("meeting-chat"), at=3)
    store.submit("newest", "Latest request", "Prepare a new briefing.", RequestSource("new-chat"), at=4)
    reopened = TaskStore(path)
    assert [task.id for task in reopened.list_tasks(limit=1)] == ["newest"]
    selected = reopened.get_many(("middle", "missing", "older", "middle", "also-missing"))
    assert [task.id for task in selected] == ["middle", "older"]
    assert selected[1].state is TaskStatus.PAUSED and selected[1].prompt == "Review the earlier notes."
    assert reopened.get_many(()) == ()
    assert reopened.get_many(("missing",)) == ()


def test_batch_reads_validate_the_requested_tasks_pending_input_relationships(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    store = TaskStore(path)
    store.submit("waiting", "Notes", "Choose the notes format.", RequestSource("chat"), at=1)
    run = store.claim("worker", "run", at=2)
    assert run is not None
    store.finish(run.run, Waiting(Question("format", "Which format?", "")), at=3)
    store.submit("other", "Other request", "Prepare a briefing.", RequestSource("other-chat"), at=4)
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("UPDATE requests SET closed_at=5 WHERE task_id='waiting' AND id='format'")
    assert [task.id for task in store.get_many(("other",))] == ["other"]
    with TestCase().assertRaises(ValueError):
        store.get_many(("other", "waiting"))


def test_batch_reads_validate_all_identifiers_and_the_supplied_batch_bound(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    store.submit("task", "Notes", "Review the notes.", RequestSource("chat"), at=1)
    maximum = ("task", *(f"missing-{index}" for index in range(999)))
    assert [task.id for task in store.get_many(maximum)] == ["task"]
    for task_ids in (("task", ""), ("task", "bad\0identity"), ("task", "x" * 129), ("task",) * 1_001):
        with TestCase().assertRaises(ValueError):
            store.get_many(task_ids)


def test_claim_is_atomic_across_independent_connections_and_respects_priority(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    first, second = TaskStore(path), TaskStore(path)
    first.submit("ordinary", "Ordinary", "Write the routine summary.", RequestSource("chat"), at=10)
    first.submit("urgent", "Urgent", "Finish the urgent request.", RequestSource("chat"), at=20, priority=10)
    gate = threading.Barrier(2)

    def claim(store: TaskStore, owner: str, run_id: str) -> str | None:
        gate.wait(timeout=5)
        value = store.claim(owner, run_id, at=30)
        return value.task.id if value is not None else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = [pool.submit(claim, first, "worker-one", "run-one"), pool.submit(claim, second, "worker-two", "run-two")]
        claimed = [future.result(10) for future in claims]
    assert claimed.count("urgent") == 1 and claimed.count(None) == 1
    running = first.get("urgent")
    assert running is not None and isinstance(running.state, Running)
    assert second.claim("another-worker", "run-three", at=31) is None
    assert first.finish(running.state.run, Completed("Urgent request finished.", ("Saved output inspected.",)), at=32) is not None
    following = second.claim("worker-two", "run-four", at=33)
    assert following is not None and following.task.id == "ordinary"


def test_failed_claim_rolls_back_the_execution_identity(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    store = TaskStore(path)
    store.submit("task", "Task", "Prepare the notes.", RequestSource("chat"), at=1)
    with closing(sqlite3.connect(path)) as database, database:
        database.execute(
            "CREATE TRIGGER reject_claim BEFORE UPDATE ON tasks WHEN NEW.phase='running' BEGIN SELECT RAISE(ABORT,'fixture write failure'); END"
        )
    with TestCase().assertRaises(sqlite3.DatabaseError):
        store.claim("worker", "run", at=2)
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("DROP TRIGGER reject_claim")
    claim = TaskStore(path).claim("worker", "run", at=3)
    assert claim is not None, "The failed transaction must not consume its run identity."
    assert store.finish(claim.run, Completed("Notes prepared.", ("Output inspected.",)), at=4) is not None


def test_pause_resume_and_cancellation_fence_old_worker_updates(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    store.submit("task", "Task", "Prepare the notes.", RequestSource("chat"), at=1)
    first = store.claim("worker", "old-run", at=2)
    assert first is not None
    assert store.progress(first.run, "Read the source notes.", at=3) is not None
    assert store.control("task", Control.PAUSE, at=4) is not None
    assert store.progress(first.run, "An old worker kept going.", at=5) is None
    assert store.begin_action(first.run, "stale-action", specification(), at=5) is None
    assert store.control("task", Control.RESUME, at=6) is not None
    resumed = store.claim("worker", "new-run", at=7)
    assert resumed is not None
    assert store.finish(first.run, Completed("Old result.", ("Wrong execution.",)), at=8) is None
    assert store.interrupt(first.run, "Old interruption.", at=8) is None
    assert store.control("task", Control.CANCEL, at=9) is not None
    assert store.finish(resumed.run, Completed("Late result.", ("Execution was cancelled.",)), at=10) is None
    assert store.control("task", Control.RESUME, at=11) is None
    saved = store.get("task")
    assert saved is not None and saved.state is TaskStatus.CANCELLED
    assert saved.checkpoint is not None and saved.checkpoint.summary == "Read the source notes."
    assert store.actions("task") == ()


def test_recovery_preserves_checkpoint_and_requires_a_new_run_identity(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    store = TaskStore(path)
    store.submit("task", "Task", "Update the project notes.", RequestSource("chat"), at=1)
    abandoned = store.claim("old-process", "old-run", at=2)
    assert abandoned is not None
    store.progress(abandoned.run, "The source notes have been read.", at=3)
    assert store.recover("old-process", at=4) == (), "Recovery must not sweep its own live run."
    reopened = TaskStore(path)
    recovered = reopened.recover("new-process", at=5)
    assert len(recovered) == 1 and isinstance(recovered[0].state, Interrupted)
    assert reopened.progress(abandoned.run, "Stale checkpoint.", at=6) is None
    assert reopened.claim("new-process", "old-run", at=6) is None
    resumed = reopened.claim("new-process", "new-run", at=7)
    assert resumed is not None and isinstance(resumed.previous, Interrupted)
    assert resumed.task.checkpoint is not None and "source notes" in resumed.task.checkpoint.summary
    assert reopened.finish(resumed.run, Completed("Notes updated.", ("Saved notes inspected.",)), at=8) is not None
    assert reopened.recover("third-process", at=9) == ()
    saved = reopened.get("task")
    assert saved is not None and isinstance(saved.state, Completed)


def test_graceful_interruption_is_recoverable_but_cancellation_stays_terminal(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    store = TaskStore(path)
    store.submit("paused", "Paused work", "Keep this for later.", RequestSource("chat"), at=1)
    store.submit("cancelled", "Cancelled work", "This will be cancelled.", RequestSource("chat"), at=2)
    store.control("cancelled", Control.CANCEL, at=3)
    run = store.claim("worker", "run", at=4)
    assert run is not None and run.task.id == "paused"
    store.interrupt(run.run, "Workspace is shutting down.", at=5)
    reopened = TaskStore(path)
    assert reopened.recover("new-worker", at=6) == ()
    later = reopened.claim("new-worker", "later-run", at=7)
    assert later is not None and isinstance(later.previous, Interrupted)
    assert "shutting down" in later.previous.reason
    cancelled = reopened.get("cancelled")
    assert cancelled is not None and cancelled.state is TaskStatus.CANCELLED


def test_waiting_questions_survive_restart_and_only_the_exact_reply_resumes(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    store = TaskStore(path)
    store.submit("task", "Task", "Update a project.", RequestSource("chat"), at=1)
    run = store.claim("worker", "run", at=2)
    assert run is not None
    question = Question("choose-project", "Which project?", "Choose the project whose notes should change.")
    store.finish(run.run, Waiting(question), at=3)
    reopened = TaskStore(path)
    assert reopened.recover("new-worker", at=4) == ()
    assert reopened.claim("new-worker", "too-early", at=5) is None
    assert reopened.control("task", Control.RESUME, at=5) is None
    assert reopened.control("task", Control.PAUSE, at=5) is None
    assert reopened.answer("task", "another-question", TextAnswer("Project A"), at=5) is None
    assert reopened.answer("task", question.id, TextAnswer("Project A"), at=6) is not None
    assert reopened.answer("task", question.id, TextAnswer("Project B"), at=7) is None
    responses = TaskStore(path).responses("task")
    assert len(responses) == 1 and responses[0].request == question and responses[0].reply == TextAnswer("Project A")
    resumed = reopened.claim("new-worker", "new-run", at=8)
    assert resumed is not None
    assert reopened.finish(run.run, Completed("Old run.", ("Stale.",)), at=9) is None


def test_answer_and_ready_state_commit_together(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    store = TaskStore(path)
    store.submit("task", "Task", "Prepare a briefing.", RequestSource("chat"), at=1)
    run = store.claim("worker", "run", at=2)
    assert run is not None
    store.finish(run.run, Waiting(Question("format", "Which format?", "")), at=3)
    with closing(sqlite3.connect(path)) as database, database:
        database.execute(
            "CREATE TRIGGER reject_reply BEFORE UPDATE ON tasks WHEN OLD.phase='waiting' BEGIN SELECT RAISE(ABORT,'fixture reply failure'); END"
        )
    with TestCase().assertRaises(sqlite3.DatabaseError):
        store.answer("task", "format", TextAnswer("Markdown"), at=4)
    assert TaskStore(path).responses("task") == ()
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("DROP TRIGGER reject_reply")
    assert store.answer("task", "format", TextAnswer("Markdown"), at=5) is not None
    assert len(TaskStore(path).responses("task")) == 1
    assert store.claim("worker", "new-run", at=6) is not None


def test_timed_waits_wake_at_the_deadline_and_blocked_work_requires_explicit_resume(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    store.submit("task", "Task", "Wait for the export.", RequestSource("chat"), at=1)
    run = store.claim("worker", "run", at=2)
    assert run is not None
    store.finish(run.run, Waiting(Until(10, "The export is still being prepared.")), at=3)
    assert store.claim("worker", "early-run", at=9.99) is None
    due = store.claim("worker", "due-run", at=10)
    assert due is not None
    store.finish(due.run, Waiting(Blocked("The destination is unavailable.")), at=11)
    assert store.claim("worker", "blocked-run", at=1_000) is None
    store.control("task", Control.RESUME, at=1_001)
    assert store.claim("worker", "retry-run", at=1_002) is not None


def test_revise_records_new_goal_and_retains_observations_while_fencing_old_run(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    store = TaskStore(path)
    store.submit("task", "Briefing", "Write a long briefing.", RequestSource("chat"), at=1)
    run = store.claim("worker", "old-run", at=2)
    assert run is not None
    store.progress(run.run, "Read the project documents.", at=3)
    store.begin_action(run.run, "observed-action", specification(), at=4)
    store.finish_action("observed-action", ActionVerified("Existing notes were read back."), at=5)
    revised = store.revise("task", "Write a one-page briefing instead.", at=6)
    assert revised is not None
    assert store.finish(run.run, Completed("Long briefing finished.", ("Wrong goal.",)), at=7) is None
    reopened = TaskStore(path)
    following = reopened.claim("worker", "new-run", at=8)
    assert following is not None and following.task.prompt == "Write a one-page briefing instead."
    assert following.task.checkpoint is not None and "project documents" in following.task.checkpoint.summary
    assert isinstance(reopened.actions("task")[0].outcome, ActionVerified)
    assert [entry.prompt for entry in reopened.revisions("task")] == ["Write a long briefing.", "Write a one-page briefing instead."]
    assert reopened.finish(following.run, Completed("One-page briefing saved.", ("Saved briefing checked.",)), at=9) is not None


def test_durable_attempt_requires_reconciliation_before_replay_or_completion(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    target = tmp_path / "notes.md"
    contents = b"The agreed project actions.\n"
    expected = hashlib.sha256(contents).hexdigest()
    spec = ActionSpec(
        "write_file", "Update project notes", hashlib.sha256(b"notes update").hexdigest(), (str(target),), FileDigest(str(target), expected)
    )
    store = TaskStore(path)
    store.submit("task", "Notes", "Update the project notes.", RequestSource("chat"), at=1)
    old = store.claim("old-worker", "old-run", at=2)
    assert old is not None
    assert store.begin_action(old.run, "write-notes", spec, at=3) is not None
    target.write_bytes(contents)
    reopened = TaskStore(path)
    reopened.recover("new-worker", at=4)
    resumed = reopened.claim("new-worker", "new-run", at=5)
    assert resumed is not None
    assert [action.id for action in reopened.unresolved_actions("task")] == ["write-notes"]
    assert reopened.begin_action(resumed.run, "duplicate-write", spec, at=6) is None
    assert reopened.finish(resumed.run, Completed("Assumed done.", ("No readback.",)), at=6) is None
    assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
    assert reopened.finish_action("write-notes", ActionVerified("Readback matches the intended notes."), at=7) is not None
    assert reopened.unresolved_actions("task") == ()
    assert reopened.finish(resumed.run, Completed("Notes recovered.", (str(target),)), at=8) is not None
    assert target.read_bytes() == contents


def test_action_finishing_in_the_same_clock_tick_is_saved_and_can_complete(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    target = tmp_path / "notes.md"
    contents = b"The agreed project actions.\n"
    expected = hashlib.sha256(contents).hexdigest()
    spec = ActionSpec(
        "write_file", "Update project notes", hashlib.sha256(b"notes update").hexdigest(), (str(target),), FileDigest(str(target), expected)
    )
    store = TaskStore(path)
    store.submit("task", "Notes", "Update the project notes.", RequestSource("chat"), at=1)
    run = store.claim("worker", "run", at=2)
    assert run is not None
    assert store.begin_action(run.run, "write-notes", spec, at=3) is not None
    target.write_bytes(contents)
    assert store.finish_action("write-notes", ActionReturned("The file write returned."), at=3) is not None
    assert hashlib.sha256(target.read_bytes()).hexdigest() == expected
    verified = ActionVerified("Readback matches the intended notes.")
    assert store.finish_action("write-notes", verified, at=3) is not None
    reopened = TaskStore(path)
    assert reopened.actions("task")[0].outcome == verified
    assert reopened.unverified_actions("task") == ()
    assert reopened.finish(run.run, Completed("Notes saved.", (str(target),)), at=4) is not None
    saved = TaskStore(path).get("task")
    assert saved is not None and isinstance(saved.state, Completed)


def test_late_action_results_survive_cancellation_without_reviving_work(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    store.submit("task", "Task", "Write the notes.", RequestSource("chat"), at=1)
    run = store.claim("worker", "run", at=2)
    assert run is not None
    store.begin_action(run.run, "write", specification(), at=3)
    store.control("task", Control.CANCEL, at=4)
    store.finish_action("write", ActionUncertain("The operation was still in flight at cancellation."), at=5)
    assert store.finish_action("write", ActionVerified("The saved notes match the requested update."), at=6) is not None
    assert store.finish_action("write", ActionUncertain("A late timeout callback arrived."), at=7) is None
    assert store.finish_action("write", ActionReturned("An even later callback returned."), at=8) is None
    saved = TaskStore(store.path).get("task")
    assert saved is not None and saved.state is TaskStatus.CANCELLED
    assert isinstance(store.actions("task")[0].outcome, ActionVerified)
    assert store.finish(run.run, Completed("Done.", ("The task was cancelled.",)), at=9) is None


def test_uncertain_and_definitely_unapplied_actions_have_distinct_replay_rules(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    store.submit("task", "Task", "Write notes.", RequestSource("chat"), at=1)
    run = store.claim("worker", "run", at=2)
    assert run is not None
    spec = specification()
    store.begin_action(run.run, "first", spec, at=3)
    assert store.begin_action(run.run, "first", spec, at=4) is None
    store.finish_action("first", ActionUncertain("The app disconnected."), at=5)
    assert store.finish(run.run, Completed("Assumed finished.", ("No verification.",)), at=6) is None
    assert store.begin_action(run.run, "second", spec, at=6) is None
    assert store.finish_action("first", ActionNotApplied("Readback proves the prior action was not applied."), at=7) is not None
    assert store.finish_action("first", ActionReturned("Late success callback."), at=8) is None
    assert store.begin_action(run.run, "second", spec, at=9) is not None
    assert store.finish_action("second", ActionReturned("The adapter returned successfully."), at=10) is not None
    assert store.finish_action("second", ActionUncertain("A stale callback."), at=9) is None
    assert store.finish_action("second", ActionVerified("A fresh readback matches."), at=11) is not None
    assert store.finish(run.run, Completed("Notes saved.", ("Verified notes.",)), at=12) is not None


def test_conversation_stop_reaches_hidden_tasks_and_preserves_other_sources(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    seed_tasks(store, tuple(f"selected-{index:03d}" for index in range(105)), RequestSource("selected-chat"), at=0)
    seed_tasks(store, tuple(f"other-{index:04d}" for index in range(1_005)), RequestSource("other-chat"), at=1_000)
    background = store.submit("background", "Background work", "Keep the background work.", RequestSource("background-chat"), at=3_000)
    assert not any(task.id.startswith("selected-") for task in store.list_tasks(limit=1_000))
    assert store.control_conversation("selected-chat", Control.CANCEL, at=4_000) == 105
    assert store.control_conversation("selected-chat", Control.CANCEL, at=4_001) == 0
    for index in range(105):
        task = store.get(f"selected-{index:03d}")
        assert task is not None and task.state is TaskStatus.CANCELLED
    assert store.get("background") == background
    following = store.claim("worker", "other-run", at=4_002)
    assert following is not None and following.task.source == RequestSource("other-chat")


def test_failed_work_can_be_explicitly_retried_but_completion_is_terminal(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    store.submit("task", "Task", "Fetch the project document.", RequestSource("chat"), at=1)
    run = store.claim("worker", "run", at=2)
    assert run is not None
    store.finish(run.run, Failed("The document could not be read."), at=3)
    failed = store.get("task")
    assert failed is not None and isinstance(failed.state, Failed)
    assert store.claim("worker", "automatic-retry", at=4) is None
    assert store.control("task", Control.RESUME, at=5) is not None
    retry = store.claim("worker", "retry", at=6)
    assert retry is not None
    store.finish(retry.run, Completed("Document retrieved.", ("Document contents inspected.",)), at=7)
    assert store.control("task", Control.RESUME, at=8) is None
    assert store.control("task", Control.CANCEL, at=8) is None


def test_invalid_rows_are_rejected_before_execution(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    store = TaskStore(path)
    store.submit("task", "Task", "Prepare notes.", RequestSource("chat"), at=1)
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("UPDATE tasks SET state=? WHERE id='task'", ('{"kind":"failed","reason":"Stopped.","unexpected":true}',))
    with TestCase().assertRaises(ValueError):
        store.claim("worker", "run", at=2)
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("UPDATE tasks SET state=?,priority='urgent' WHERE id='task'", ('"ready"',))
    with TestCase().assertRaises(ValueError):
        store.get("task")
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("UPDATE tasks SET priority=0,phase='running' WHERE id='task'")
    with TestCase().assertRaises(ValueError):
        store.list_tasks()


def test_invalid_action_and_reply_rows_do_not_enter_typed_interfaces(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite3"
    store = TaskStore(path)
    store.submit("task", "Task", "Prepare notes.", RequestSource("chat"), at=1)
    run = store.claim("worker", "run", at=2)
    assert run is not None
    store.begin_action(run.run, "action", specification(), at=3)
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("UPDATE actions SET outcome=?,outcome_kind='verified' WHERE id='action'", ('{"kind":"verified","evidence":42}',))
    with TestCase().assertRaises(ValueError):
        store.actions("task")
    store.finish(run.run, Waiting(Question("format", "Which format?", "")), at=4)
    store.answer("task", "format", TextAnswer("Markdown"), at=5)
    with closing(sqlite3.connect(path)) as database, database:
        database.execute("UPDATE responses SET reply=? WHERE task_id='task'", ('{"kind":"answer","text":42}',))
    with TestCase().assertRaises(ValueError):
        store.responses("task")


def test_input_validation_rejects_invalid_limits_and_nonfinite_times_without_writes(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    with TestCase().assertRaises(ValueError):
        store.submit("bad", "Bad time", "Do work.", RequestSource("chat"), at=float("nan"))
    with TestCase().assertRaises(ValueError):
        store.submit("bad", "Bad priority", "Do work.", RequestSource("chat"), at=1, priority=1_000_000)
    with TestCase().assertRaises(ValueError):
        store.list_tasks(limit=0)
    with TestCase().assertRaises(ValueError):
        store.actions("missing", limit=1_001)
    assert store.list_tasks() == ()


def test_run_identity_cannot_be_borrowed_from_another_task(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "work.sqlite3")
    store.submit("first", "First", "Prepare notes.", RequestSource("chat"), at=1)
    store.submit("second", "Second", "Prepare a briefing.", RequestSource("chat"), at=2)
    run = store.claim("worker", "run", at=3)
    assert run is not None
    forged = RunRef("second", run.run.run_id)
    assert store.progress(forged, "A forged update.", at=4) is None
    assert store.begin_action(forged, "wrong-task-action", specification(), at=4) is None
    assert store.finish(forged, Completed("Forged result.", ("Wrong task.",)), at=4) is None
    assert store.finish(run.run, Completed("Notes prepared.", ("Notes inspected.",)), at=5) is not None
    next_run = store.claim("worker", "another-run", at=6)
    assert next_run is not None and next_run.task.id == "second"
