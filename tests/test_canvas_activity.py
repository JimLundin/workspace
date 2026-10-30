"""Agent activity, request identity and Workspace's quiet attention policy."""

from dataclasses import replace
from pathlib import Path

import assistant.agent_session
import automation.task
from assistant.agent_session import Answered, Approval, CanvasNotice, CanvasSettled, ChatMessage, Question, Session, transition
from assistant.canvas_activity import (
    ActionState,
    Attention,
    CanvasAction,
    CanvasInstruction,
    CanvasQuestion,
    CanvasRun,
    CanvasUpdate,
    TaskRequest,
    history_session,
    important_changes,
    redirect_session,
)
from assistant.notifications import Tone, active, observe, tone
from assistant.work_canvas_model import DOCUMENT, CanvasCollection, CanvasDocument, CanvasNote, Placement, observe_activity
from assistant.work_canvas_store import CanvasStore
from assistant.work_window import ReplyProblem, WorkSnapshot
from automation.actions import plan
from automation.personal_work import Catalog, SourceKind, WorkDefinition, WorkState, WorkThread
from automation.task import ActionReturned, ActionSpec, ActionUncertain, ActionVerified, Completed, RequestSource, Waiting
from tests.personal_work_fixture import source
from tests.test_work_agent import WorkRig
from tests.test_work_window import work_task


def test_saved_questions_keep_their_route_state_and_thread_after_session_mirroring(tmp_path: Path) -> None:
    # Defect: storage flattens a clarification into an update, a conversation
    # mirror replaces its durable task route, or a stale mirror erases context.
    task = work_task(Waiting(automation.task.Question("request-1", "Which supplier?", "Choose a deployment supplier.")))
    store = CanvasStore(tmp_path / "canvas.sqlite3")
    store.save(CanvasDocument(runs=(CanvasRun(task.id, "work:atlas"),)))
    document = store.observe_tasks(WorkSnapshot(tasks=(task,)))
    question = document.activity[0]
    assert isinstance(question, CanvasQuestion)
    assert question.request == TaskRequest(task.id, "request-1") and question.work_ids == ("work:atlas",)
    mirror = Question("request-1", "Which supplier?", "", 201)
    session = Session(identity="session-one", messages=(mirror,))
    document = store.observe_session(session)
    mirrored = document.activity[0]
    assert isinstance(mirrored, CanvasQuestion) and mirrored.request == question.request
    accepted = replace(question, reply=Answered("Use Contoso"))
    store.save(observe_activity(document, (accepted,)))
    cancelled = replace(session, messages=(replace(mirror, reply=assistant.agent_session.Cancelled()),))
    document = store.observe_session(cancelled)
    assert document.activity == (accepted,)
    # A failure receipt reopens only the exact live request, retaining the draft
    # in the native editor rather than displaying an unconfirmed answer forever.
    problem = ReplyProblem(task_id=task.id, request_id="request-1", receipt_id="reply-1", reason="Disk unavailable")
    restored = store.observe_tasks(WorkSnapshot(tasks=(task,), reply_problems=(problem,)))
    retry = restored.activity[0]
    assert isinstance(retry, CanvasQuestion) and retry.reply is Attention.WAITING
    closed = store.observe_tasks(WorkSnapshot(tasks=(replace(task, state=Completed("Supplier confirmed", ())),)))
    resolved = closed.activity[0]
    assert isinstance(resolved, CanvasQuestion) and resolved.reply is Attention.CLOSED
    assert isinstance(closed.activity[1], CanvasUpdate) and closed.activity[1].work_ids == ("work:atlas",)
    assert CanvasStore(store.path).read() == closed


def test_new_session_closes_old_questions_without_closing_live_durable_questions(tmp_path: Path) -> None:
    # Defect: a restarted assistant leaves old questions actionable or closes
    # a task question merely because it is no longer in the visible conversation.
    store = CanvasStore(tmp_path / "canvas.sqlite3")
    store.observe_session(Session(identity="old", messages=(Question("old-request", "Which workbook?", "", 10),)))
    task = work_task(Waiting(automation.task.Question("task-request", "Which supplier?", "")))
    store.observe_tasks(WorkSnapshot(tasks=(task,)))
    document = store.observe_session(Session(identity="new"))
    old, durable = document.activity
    assert isinstance(old, CanvasQuestion) and isinstance(durable, CanvasQuestion)
    assert old.reply is Attention.CLOSED and durable.reply is Attention.WAITING


def test_floating_attention_has_exact_persistent_redirects_and_retains_approval_guards() -> None:
    # Defect: app context or routine progress becomes an alert, a pending question
    # expires, or a guarded approval is lost when the floating surface redirects.
    question = Question("question with spaces", "Which supplier?", "Background context", 10)
    approval = Approval("approval", "Publish reply?", "Exact reply preview", 11)
    session = Session(messages=(ChatMessage("Workspace", "Fetched the next mail", 9), question, approval), phase="running")
    redirected = redirect_session(session)
    assert len(redirected.messages) == 2 and redirected.messages[1] == approval
    prompt = redirected.messages[0]
    assert isinstance(prompt, ChatMessage) and "target=question%3Aquestion+with+spaces" in prompt.text
    assert prompt.source is not None and prompt.source.identity == "canvas:question:question with spaces"
    assert not redirected.busy
    assert history_session(session).messages == session.messages
    content = observe(redirected)[0]
    assert active(content) and tone(content) is Tone.QUESTION
    announced = transition(Session(), CanvasNotice("Needs you", "question:request", 10))
    settled = transition(announced, CanvasSettled(frozenset(("question:request",))))
    assert not redirect_session(settled).messages


def test_classification_stays_quiet_and_state_transitions_redirect_to_the_context() -> None:
    # Defect: classification or source refresh demands attention, or a completed
    # outcome fails to redirect to its existing work context.
    work = WorkThread("work:atlas", 0, WorkDefinition("Atlas", "Deploy Atlas"), (), 10, 10)
    catalog = Catalog(works=(work,))
    assert not important_changes(Catalog(), catalog)
    quiet = replace(
        catalog, works=(replace(work, revision=1, definition=replace(work.definition, summary="New evidence")),), sources=(source(SourceKind.TEAMS),)
    )
    assert not important_changes(catalog, quiet)
    done = replace(quiet, works=(replace(work, revision=2, definition=replace(work.definition, state=WorkState.DONE)),))
    assert important_changes(quiet, done) == (work.id,)


def test_startup_removes_retired_fetch_projections_from_the_saved_canvas(tmp_path: Path) -> None:
    # Defect: retired fetches are only hidden in memory, so every subsequent
    # load reparses them and old execution attempts remain canvas context.
    store = CanvasStore(tmp_path / "canvas.sqlite3")
    fetched = CanvasAction("action:fetch", "Browser fetch", "Attempted navigation", 1, ActionState.RETURNED, ("work:atlas",))
    finding = CanvasUpdate("result:research", "Verified conclusion", "Useful evidence", 2, ("work:atlas",))
    store.save(CanvasDocument(activity=(fetched, finding)))
    reopened = CanvasStore(store.path)
    with reopened.connection() as connection:
        assert reopened.loaded(connection).activity == (finding,)


def test_action_history_stays_out_of_the_canvas_while_prepared_content_remains(tmp_path: Path) -> None:
    # Defect: observed action attempts or acknowledgments still become cards,
    # or suppressing the ledger also removes actual prepared content.
    rig = WorkRig(tmp_path)
    canvas = CanvasStore(tmp_path / "canvas.sqlite3")
    try:
        task = rig.tasks.submit("canvas-task", "Prepare handoff", "Draft a handoff reply", RequestSource("canvas"), at=1)
        claim = rig.tasks.claim("worker", "run", at=2)
        assert claim is not None
        canvas.save(CanvasDocument(runs=(CanvasRun(task.id, "work:atlas"),)))
        fetch_spec = plan("browser_open", {"url": "https://example.test/research"})
        assert isinstance(fetch_spec, ActionSpec)
        fetch = rig.tasks.begin_action(claim.run, "fetch", fetch_spec, at=2.5)
        assert fetch is not None
        rig.tasks.finish_action(fetch.id, ActionReturned("Fetched a page"), at=2.6)
        draft_spec = plan("outlook_web_draft_reply", {"body": "Proposed handoff"})
        assert isinstance(draft_spec, ActionSpec)
        draft = rig.tasks.begin_action(claim.run, "draft", draft_spec, at=3)
        assert draft is not None
        assert not rig.refresh().actions
        rig.agent.watch((task.id,), owner="canvas")
        pending = canvas.observe_tasks(rig.refresh()).activity
        assert not pending
        returned = rig.tasks.finish_action(draft.id, ActionReturned("Reply draft is available in Outlook"), at=4)
        assert returned is not None
        document = canvas.observe_tasks(rig.refresh())
        assert not document.activity
        artifact = CanvasNote("note:handoff", "Handoff reply", "Proposed handoff", "work:atlas")
        canvas.save(replace(document, notes=(artifact,)))
        ticket_spec = plan("kanban_update_task", {"id": "AT-42"})
        assert isinstance(ticket_spec, ActionSpec)
        ticket = rig.tasks.begin_action(claim.run, "ticket", ticket_spec, at=5)
        assert ticket is not None
        rig.tasks.finish_action(ticket.id, ActionUncertain("Readback unavailable"), at=6)
        metadata_spec = plan("work_items_save", {"title": "Atlas"})
        assert isinstance(metadata_spec, ActionSpec)
        metadata = rig.tasks.begin_action(claim.run, "classification", metadata_spec, at=7)
        assert metadata is not None
        document = canvas.observe_tasks(rig.refresh())
        assert not document.activity and document.notes == (artifact,)
        rig.tasks.finish_action(ticket.id, ActionVerified("AT-42 now has the agreed owner"), at=8)
        final = canvas.observe_tasks(rig.refresh())
        assert not final.activity and final.notes == (artifact,)
        assert len(rig.refresh().actions) == 4 and CanvasStore(canvas.path).read() == final
    finally:
        rig.close()


def test_existing_request_scaffolding_is_removed_without_losing_its_results(tmp_path: Path) -> None:
    # Defect: cleanup leaves generated instructions/action reports visible or
    # deletes, unnests, or moves the useful content collected beneath them.
    store = CanvasStore(tmp_path / "canvas.sqlite3")
    request = CanvasNote("note:instruction:old", "Agent request · Arrange Atlas", "Arrange the bubbles", "group:atlas")
    followup = CanvasNote("note:instruction:followup", "Agent request · More detail", "Compare the dates", request.id)
    finding = CanvasNote("note:plan", "Deployment plan", "Verified deployment dates", followup.id)
    placed = Placement(finding.id, 120, 80)
    report = CanvasUpdate("result:arrange", "Arrangement done", "Moved two bubbles", 3, (request.id,))
    legacy = CanvasDocument(
        notes=(request, followup, finding),
        placements=(placed, Placement(request.id, 10, 10)),
        runs=(CanvasRun("arrange", request.id, CanvasInstruction("Arrange Atlas")),),
        activity=(report,),
        pinned=frozenset((finding.id, request.id)),
        collections=(CanvasCollection("group:atlas", "Atlas", (request.id,)),),
    )
    with store.connection() as connection:
        connection.execute("UPDATE canvas SET payload=? WHERE id=1", (DOCUMENT.dump_json(legacy),))
    restored = CanvasStore(store.path).read()
    assert restored.notes == (replace(finding, context_id="group:atlas"),)
    assert restored.placements == (placed,) and restored.pinned == frozenset((finding.id,))
    assert restored.collections[0].members == (finding.id,) and not restored.activity
    assert restored.runs[0].work_id == "group:atlas"
    with store.connection() as connection:
        assert store.loaded(connection) == restored


def test_another_research_run_does_not_turn_an_arrangement_report_into_context(tmp_path: Path) -> None:
    # Defect: a research binding for another task mistakenly qualifies every
    # completed instruction as a substantive research result.
    store = CanvasStore(tmp_path / "canvas.sqlite3")
    store.save(
        CanvasDocument(runs=(CanvasRun("arrange", "work:atlas", CanvasInstruction("Arrange these bubbles")), CanvasRun("research", "work:atlas")))
    )
    arrangement = work_task(Completed("Moved the bubbles", ()), identity="arrange")
    research = work_task(Completed("The current plan is version 3", ()), identity="research")
    document = store.observe_tasks(WorkSnapshot(tasks=(arrangement, research)))
    assert document.activity == (CanvasUpdate("result:research", research.title, "The current plan is version 3", 200, ("work:atlas",)),)
