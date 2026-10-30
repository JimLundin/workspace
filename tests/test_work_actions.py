"""Durable effects through real SQLite, files, and cancellable ownership."""

import hashlib
import json
import sqlite3
import threading
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from unittest import TestCase

from assistant.agent import Agent
from assistant.agent_tools import Output
from assistant.agent_toolsets import General
from assistant.llm import Json, Settings
from automation.actions import ActionCancelledError, Actions, Change, LostRunError, Operation, Resources, UncertainEffectError
from automation.execution import ApprovalReview, Reconciliation, Reported, WorkExecution
from automation.store import TaskStore
from automation.task import (
    Action,
    ActionNotApplied,
    ActionPending,
    ActionSpec,
    ActionVerified,
    Approval,
    ApprovalDecision,
    Blocked,
    Claim,
    Completed,
    Control,
    FileDigest,
    NoVerification,
    RequestSource,
    RunRef,
    Waiting,
)
from tests.test_agent import FakeMachine, FakeWindow
from tests.work_fixture import seed_verified_actions


@dataclass(slots=True)
class Clock:
    value: float = 2

    def __call__(self) -> float:
        self.value += 1
        return self.value


def claimed(tmp_path: Path) -> tuple[TaskStore, Claim, Clock]:
    store = TaskStore(tmp_path / "work.sqlite3")
    store.submit("task", "Prepare notes", "Save the project notes.", RequestSource("chat"), at=1)
    claim = store.claim("worker", "run", at=2)
    assert claim is not None
    return store, claim, Clock()


def written(arguments: Mapping[str, Json], verification: FileDigest | None = None) -> ActionSpec:
    """A file write's record; journaling does not depend on a tool family's classification."""
    return Change(("filesystem",)).specification(Operation.of("write_file", arguments), verification or NoVerification.NONE)


def families(work: WorkExecution) -> Agent:
    """The registered tool families classify operations and decide what observations prove."""
    return Agent(Settings("", "", "", "", "", "", ""), FakeMachine(), FakeWindow(), threading.Event(), work=work, toolset=General)


def attempt(agent: Agent, tool: str, arguments: Mapping[str, Json]) -> None:
    agent.effect(Operation.of(tool, arguments), lambda: Output("Returned."))


def observe(agent: Agent, operation: Operation, result: str) -> str:
    return agent.effect(operation, lambda: Output(result)).observation


def reconcile(agent: Agent, request: Reconciliation) -> str:
    return agent.work.reconcile(request, agent.proof)


def test_storage_commit_precedes_effect_and_failure_refuses_the_effect(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    destination = tmp_path / "notes.txt"
    args = {"path": str(destination), "content": "notes"}
    actions = Actions(store, claim.run, Resources(), clock=clock)
    executed: list[str] = []

    def write() -> int:
        pending = TaskStore(tmp_path / "work.sqlite3").actions("task")
        assert len(pending) == 1 and pending[0].outcome is ActionPending.RUNNING
        executed.append("write")
        return destination.write_text("notes", encoding="utf-8")

    with closing(sqlite3.connect(tmp_path / "work.sqlite3")) as database, database:
        database.execute("CREATE TRIGGER refuse_attempt BEFORE INSERT ON actions BEGIN SELECT RAISE(ABORT,'fixture commit failure'); END")
    with TestCase().assertRaises(sqlite3.DatabaseError):
        actions.execute(written(args), write, lambda count: count > 0, threading.Event())
    assert not destination.exists() and not executed and not store.actions("task")
    with closing(sqlite3.connect(tmp_path / "work.sqlite3")) as database, database:
        database.execute("DROP TRIGGER refuse_attempt")
    expected = FileDigest(str(destination), hashlib.sha256(b"notes").hexdigest())
    actions.execute(written(args, expected), write, lambda count: count > 0, threading.Event())
    assert destination.read_text(encoding="utf-8") == "notes" and executed == ["write"]
    assert isinstance(TaskStore(tmp_path / "work.sqlite3").actions("task")[0].outcome, ActionVerified)


def test_lost_result_commit_recovers_by_readback_without_replaying(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    destination = tmp_path / "notes.txt"
    expected = FileDigest(str(destination), hashlib.sha256(b"written once").hexdigest())
    spec = written({"path": str(destination), "content": "written once"}, expected)
    actions = Actions(store, claim.run, Resources(), clock=clock)
    executions: list[str] = []

    def write() -> int:
        executions.append("write")
        return destination.write_text("written once", encoding="utf-8")

    with closing(sqlite3.connect(tmp_path / "work.sqlite3")) as database, database:
        database.execute("CREATE TRIGGER refuse_result BEFORE UPDATE ON actions BEGIN SELECT RAISE(ABORT,'fixture lost acknowledgement'); END")
    with TestCase().assertRaises(sqlite3.DatabaseError):
        actions.execute(spec, write, lambda count: count > 0, threading.Event())
    assert destination.read_text(encoding="utf-8") == "written once"
    assert store.actions("task")[0].outcome is ActionPending.RUNNING
    with TestCase().assertRaises(UncertainEffectError):
        actions.execute(spec, write, lambda count: count > 0, threading.Event())
    with closing(sqlite3.connect(tmp_path / "work.sqlite3")) as database, database:
        database.execute("DROP TRIGGER refuse_result")
    reopened = TaskStore(tmp_path / "work.sqlite3")
    assert reopened.recover("restarted-worker", at=clock())
    resumed = reopened.claim("restarted-worker", "second-run", at=clock())
    assert resumed is not None
    recovered = Actions(reopened, resumed.run, Resources(), clock=clock)
    assert recovered.reconcile(threading.Event()) == ()
    assert executions == ["write"] and isinstance(reopened.actions("task")[0].outcome, ActionVerified)


def test_mismatched_recovery_file_stays_uncertain_and_cannot_be_overwritten(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    destination = tmp_path / "notes.txt"
    spec = written({"path": str(destination), "content": "desired"}, FileDigest(str(destination), hashlib.sha256(b"desired").hexdigest()))
    actions = Actions(store, claim.run, Resources(), clock=clock)

    def interrupted_write() -> bool:
        destination.write_text("partial", encoding="utf-8")
        raise OSError("The application disconnected after changing the file.")

    with TestCase().assertRaises(OSError):
        actions.execute(spec, interrupted_write, bool, threading.Event())
    other = tmp_path / "another-project.txt"
    other.write_text("untouched", encoding="utf-8")
    different = written({"path": str(other), "content": "new notes"}, FileDigest(str(other), hashlib.sha256(b"new notes").hexdigest()))
    with TestCase().assertRaises(UncertainEffectError):
        actions.execute(different, lambda: other.write_text("new notes", encoding="utf-8"), bool, threading.Event())
    assert other.read_text(encoding="utf-8") == "untouched" and len(store.actions("task")) == 1
    assert len(actions.reconcile(threading.Event())) == 1
    with TestCase().assertRaises(UncertainEffectError):
        actions.execute(spec, lambda: destination.write_text("desired", encoding="utf-8"), bool, threading.Event())
    assert destination.read_text(encoding="utf-8") == "partial"
    destination.write_text("desired", encoding="utf-8")  # A later external repair can establish the intended state.
    assert actions.reconcile(threading.Event()) == ()
    actions.execute(different, lambda: other.write_text("new notes", encoding="utf-8"), bool, threading.Event())
    assert other.read_text(encoding="utf-8") == "new notes"


def test_stop_cancels_resource_wait_and_releases_the_next_owner(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    resources, stopped, entered = Resources(), threading.Event(), threading.Event()
    destination = tmp_path / "must-not-exist.txt"
    actions = Actions(store, claim.run, resources, clock=clock)

    def waiting() -> None:
        entered.set()
        actions.execute(written({"path": str(destination), "content": "no"}), lambda: destination.write_text("no", encoding="utf-8"), bool, stopped)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with resources.hold(("foreground",), threading.Event()):
            future = pool.submit(waiting)
            assert entered.wait(5)
            stopped.set()
            with TestCase().assertRaises(ActionCancelledError):
                future.result(5)
        with resources.hold(("clipboard",), threading.Event()):
            assert not destination.exists() and not store.actions("task")


class StoppingStore(TaskStore):
    """A real store whose public commit acknowledgement races cancellation."""

    __slots__ = ("stop",)

    def __init__(self, path: Path, stop: threading.Event) -> None:
        super().__init__(path)
        self.stop = stop

    def begin_action(self, run: RunRef, action_id: str, specification: ActionSpec, *, at: float) -> Action | None:
        result = super().begin_action(run, action_id, specification, at=at)
        self.stop.set()
        return result


def test_stale_run_and_stop_after_commit_cannot_enter_the_effect(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    destination = tmp_path / "must-not-exist.txt"
    spec = written({"path": str(destination), "content": "no"})
    store.control("task", Control.PAUSE, at=clock())
    store.control("task", Control.RESUME, at=clock())
    later = store.claim("worker", "new-run", at=clock())
    assert later is not None
    with TestCase().assertRaises(LostRunError):
        Actions(store, claim.run, Resources(), clock=clock).execute(
            spec,
            lambda: destination.write_text("no", encoding="utf-8"),
            bool,
            threading.Event(),
        )
    stop = threading.Event()
    cancelling = StoppingStore(tmp_path / "work.sqlite3", stop)
    with TestCase().assertRaises(ActionCancelledError):
        Actions(cancelling, later.run, Resources(), clock=clock).execute(
            spec,
            lambda: destination.write_text("no", encoding="utf-8"),
            bool,
            stop,
        )
    assert not destination.exists() and isinstance(store.actions("task")[0].outcome, ActionNotApplied)


def test_reconciliation_requires_post_attempt_same_target_and_is_durable(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    work = WorkExecution(claim, store, Resources(), clock=clock)
    agent = families(work)
    pages = {"target-tab": "before", "other-tab": "unrelated"}
    before = observe(agent, Operation.of("browser_snapshot", {"target_id": "target-tab"}), pages["target-tab"])

    def interrupted_save() -> Output:
        pages["target-tab"] = "Saved successfully"
        raise OSError("Lost the browser acknowledgement")

    with TestCase().assertRaises(OSError):
        agent.effect(Operation.of("browser_action", {"target_id": "target-tab", "id": "save", "action": "click"}), interrupted_save)
    action = store.actions("task")[0]
    with TestCase().assertRaisesRegex(ValueError, "after this action"):
        reconcile(agent, Reconciliation(action.id, before, applied=True))
    wrong = observe(agent, Operation.of("browser_snapshot", {"target_id": "other-tab"}), pages["other-tab"])
    with TestCase().assertRaisesRegex(ValueError, "target"):
        reconcile(agent, Reconciliation(action.id, wrong, applied=True))
    fresh = observe(agent, Operation.of("browser_snapshot", {"target_id": "target-tab"}), pages["target-tab"])
    assert "Saved" in pages["target-tab"]
    reconcile(agent, Reconciliation(action.id, fresh, applied=True))
    assert isinstance(work.outcome(Reported("Saved."), threading.Event()), Completed)
    assert isinstance(TaskStore(tmp_path / "work.sqlite3").actions("task")[0].outcome, ActionVerified)


def test_script_result_requires_explicit_inspection_and_reconciliation(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    work = WorkExecution(claim, store, Resources(), clock=clock)
    agent = families(work)
    destination = tmp_path / "script-output.txt"
    attempt(agent, "run_powershell", {"command": "script writes requested output"})
    destination.write_text("complete", encoding="utf-8")
    assert isinstance(work.outcome(Reported("Done"), threading.Event()), Waiting)
    action = store.actions("task")[0]
    # Defect: a status listing or the time stands in for inspecting the script's actual result.
    for general in (observe(agent, Operation.of("get_current_time", {}), "Local time"), observe(agent, Operation.of("browser_tabs", {}), "{}")):
        with TestCase().assertRaisesRegex(ValueError, "target"):
            reconcile(agent, Reconciliation(action.id, general, applied=True))
    content = destination.read_text(encoding="utf-8")
    observed = observe(agent, Operation.of("read_file", {"path": str(destination)}), content)
    assert content == "complete"
    reconcile(agent, Reconciliation(action.id, observed, applied=True))
    assert isinstance(work.outcome(Reported("The output was inspected."), threading.Event()), Completed)


def test_native_tab_verification_uses_the_listed_target_even_when_the_strip_is_paged(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    work = WorkExecution(claim, store, Resources(), clock=clock)
    agent = families(work)
    attempt(agent, "browser_tab", {"tab_id": 17, "action": "pin"})
    action = store.actions("task")[0]
    wrong = observe(agent, Operation.of("browser_tabs", {"view": "strip"}), '{"view":"strip","tabs":[{"tab_id":18,"pinned":true}],"next_offset":1}')
    with TestCase().assertRaisesRegex(ValueError, "target"):
        reconcile(agent, Reconciliation(action.id, wrong, applied=True))
    correct = observe(
        agent, Operation.of("browser_tabs", {"view": "strip", "offset": 1}), '{"view":"strip","tabs":[{"tab_id":17,"pinned":true}],"next_offset":2}'
    )
    reconcile(agent, Reconciliation(action.id, correct, applied=True))
    assert isinstance(work.outcome(Reported("Pinned the requested tab."), threading.Event()), Completed)


def test_old_unverified_action_cannot_fall_off_the_completion_page(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    work = WorkExecution(claim, store, Resources(), clock=clock)
    attempt(families(work), "set_clipboard", {"text": "needs verification"})
    spec = written({"path": "note.txt", "content": "verified"})
    assert store.begin_action(claim.run, "later-0", spec, at=clock()) is not None
    sample = store.finish_action("later-0", ActionVerified("Read back the file."), at=clock())
    assert sample is not None
    later = tuple(f"later-{index}" for index in range(1, 100))
    seed_verified_actions(store, sample, later)
    # Subsequent transitions happen after the fixture catalog's timestamps.
    clock.value = sample.updated_at + 2 * len(later)
    assert len(store.actions("task", limit=100)) == 100
    assert isinstance(work.outcome(Reported("Everything is complete."), threading.Event()), Waiting)


def test_exact_approval_is_once_only_and_private_review_never_enters_storage(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    reviews: list[ApprovalReview] = []

    def display(review: ApprovalReview) -> bool:
        reviews.append(review)
        return True

    original = WorkExecution(claim, store, Resources(), review=display, clock=clock)
    arguments: dict[str, Json] = {"target_id": "secret-tab", "id": "control", "action": "fill", "value": "private-message-content"}
    operation = Operation.of("browser_action", arguments)
    assert not original.approve(operation, "Fill this control?", "private-full-browser-review")
    waiting = original.outcome(Reported("Waiting."), threading.Event())
    assert isinstance(waiting, Waiting) and isinstance(waiting.reason, Approval)
    assert "private-message-content" in reviews[0].detail
    assert store.finish(claim.run, waiting, at=clock()) is not None
    assert store.answer("task", waiting.reason.id, ApprovalDecision.APPROVED, at=clock()) is not None
    resumed = store.claim("worker", "approved-run", at=clock())
    assert resumed is not None
    work = WorkExecution(resumed, store, Resources(), review=display, clock=clock)
    assert work.approve(operation, "Fill this control?", "private-full-browser-review")
    attempt(families(work), "browser_action", arguments)
    assert not work.approve(operation, "Fill this control?", "private-full-browser-review")
    assert len(reviews) == 2 and reviews[0].request.id != reviews[1].request.id
    work.checkpoint(
        [
            {"type": "reasoning", "encrypted_content": "private-reasoning"},
            {"type": "function_call", "name": "browser_action", "arguments": json.dumps(arguments)},
        ]
    )
    with closing(sqlite3.connect(tmp_path / "work.sqlite3")) as database, database:
        persisted = "\n".join(database.iterdump())
    assert all(secret not in persisted for secret in ("secret-tab", "private-message-content", "private-full-browser-review", "private-reasoning"))


def test_approval_needs_live_preview_and_cannot_authorize_changed_arguments_or_goal(tmp_path: Path) -> None:
    store, claim, clock = claimed(tmp_path)
    work = WorkExecution(claim, store, Resources(), clock=clock)
    draft = Operation.of("teams_web_draft_reply", {"target_id": "page", "chat_id": "recipient-one", "text": "first draft"})
    assert not work.approve(draft, "Prepare reply?", "Review the draft")
    assert isinstance(work.disposition, Waiting) and isinstance(work.disposition.reason, Blocked)
    reviews: list[ApprovalReview] = []

    def display(review: ApprovalReview) -> bool:
        reviews.append(review)
        return True

    original = WorkExecution(claim, store, Resources(), review=display, clock=clock)
    assert not original.approve(draft, "Prepare reply?", "Review the draft")
    assert original.disposition is not None
    assert store.finish(claim.run, original.disposition, at=clock()) is not None
    assert store.answer("task", reviews[0].request.id, ApprovalDecision.APPROVED, at=clock()) is not None
    resumed = store.claim("worker", "changed-arguments", at=clock())
    assert resumed is not None
    changed = WorkExecution(resumed, store, Resources(), review=display, clock=clock)
    assert not changed.approve(
        Operation.of("teams_web_draft_reply", {"target_id": "page", "chat_id": "recipient-two", "text": "first draft"}),
        "Prepare reply?",
        "Review the draft",
    )
    assert store.revise("task", "Only prepare a draft; do not send it.", at=clock()) is not None
    redirected = store.claim("worker", "changed-goal", at=clock())
    assert redirected is not None
    new_goal = WorkExecution(redirected, store, Resources(), review=display, clock=clock)
    assert not new_goal.approve(draft, "Prepare reply?", "Review the draft")
    assert not store.actions("task")
