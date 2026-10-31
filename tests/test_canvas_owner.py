"""The canvas owner's observation, attention, answer and user-edit policy."""

from dataclasses import replace
from pathlib import Path
from unittest import TestCase

import automation.task
from assistant.agent_session import Session
from assistant.canvas_activity import CanvasInstruction, CanvasQuestion, CanvasRequest, CanvasRun, CanvasUpdate, SessionRequest
from assistant.work_canvas import (
    Announcement,
    AnswerQuestion,
    Investigating,
    NotQueued,
    Queued,
    ResumeTask,
    SpeechRoute,
    WorkCanvas,
)
from assistant.work_canvas_commands import ArrangeCanvas, CanvasUpdated, MoveBubble, PutNote, PutRelation, UpdateCanvas, revision
from assistant.work_canvas_context import CanvasScope, context_path
from assistant.work_canvas_edits import ArrangeView, RenameGroup, UserEdit
from assistant.work_canvas_gestures import NestBubble, PlaceBubbles
from assistant.work_canvas_model import CanvasCollection, CanvasDocument, CanvasNote, CanvasRelation, Placement, view_state
from assistant.work_snapshot import WorkSnapshot
from automation.personal_work import DismissedWork, WorkState
from automation.task import Blocked, Completed, TextAnswer, Waiting
from tests.agent_requests import asked
from tests.test_work_canvas import catalog, local_canvas, nested_bubbles, seeded
from tests.test_work_window import work_task


def test_changed_evidence_queues_one_bounded_investigation_and_refusal_releases_it(tmp_path: Path) -> None:
    # Defect: catalog publication never investigates, repeats queued work,
    # announces the silent baseline, or a refused queue marks evidence handled.
    queued: list[CanvasRun] = []
    canvas = WorkCanvas(tmp_path / "canvas.sqlite3", queued.append, autonomous=True)
    first = canvas.observe_catalog(catalog())
    assert queued and first.document.runs == tuple(queued) == canvas.read().runs and first.notice is None
    repeated = canvas.observe_catalog(catalog())
    assert len(queued) == 2 and repeated.document.runs == tuple(queued) and repeated.notice is None

    def refuse(_run: CanvasRun) -> None:
        raise ValueError("The queue is full.")

    refused = WorkCanvas(tmp_path / "refused.sqlite3", refuse, autonomous=True)
    assert not refused.observe_catalog(catalog()).document.runs and not refused.read().runs
    manual = WorkCanvas(tmp_path / "manual.sqlite3", queued.append, autonomous=False)
    assert not manual.observe_catalog(catalog()).document.runs and len(queued) == 2


def test_attention_is_announced_once_and_never_from_dismissed_work(tmp_path: Path) -> None:
    # Defect: repeated snapshots duplicate desktop prompts, dismissed work
    # announces late results, or a work state change stays silent.
    data = catalog()
    active, dismissed = data.works
    research, late = work_task(identity="research"), work_task(identity="late")
    canvas = local_canvas(tmp_path)
    seeded(canvas, CanvasDocument(runs=(CanvasRun(research.id, active.id), CanvasRun(late.id, dismissed.id))))
    shown = replace(data, works=(active,), dismissed=(DismissedWork(dismissed, "Wrong owner"),))
    assert canvas.observe_catalog(shown).notice is None
    assert canvas.observe_work(WorkSnapshot(tasks=(research, late))).notice is None
    completed = WorkSnapshot(tasks=tuple(replace(task, state=Completed("Handoff confirmed", ())) for task in (research, late)))
    assert canvas.observe_work(completed).notice == Announcement(research.title, "result:" + research.id)
    assert canvas.observe_work(completed).notice is None
    done = replace(shown, works=(replace(active, definition=replace(active.definition, state=WorkState.DONE)),))
    assert canvas.observe_catalog(done).notice == Announcement("Canvas updated · " + active.definition.title, active.id)


def test_answers_reach_only_visible_waiting_questions_and_record_one_reply(tmp_path: Path) -> None:
    # Defect: a reply reaches an expired or dismissed request, a rejected
    # delivery is recorded as answered, or a question can be answered twice.
    data = catalog()
    active, dismissed = data.works
    canvas = local_canvas(tmp_path)
    canvas.observe_catalog(replace(data, works=(active,), dismissed=(DismissedWork(dismissed, "Wrong owner"),)))
    current = work_task(Waiting(automation.task.Question("current", "Current question", "")), identity="current-task")
    hidden = work_task(Waiting(automation.task.Question("hidden", "Hidden question", "")), identity="hidden-task")
    finding = CanvasUpdate("result:finding", "Finding", "Version two is approved.", 5, (active.id,))
    seeded(canvas, CanvasDocument(runs=(CanvasRun(current.id, active.id), CanvasRun(hidden.id, dismissed.id)), activity=(finding,)))
    canvas.observe_session(Session(identity="session", messages=(asked("chat", "Which supplier?", "", 10),)))
    document = canvas.observe_work(WorkSnapshot(tasks=(current, hidden))).document
    assert [question.id for question in canvas.waiting()] == ["question:chat", "question:current"]
    assert canvas.settled(document) == frozenset(("question:hidden",))
    delivered: list[tuple[CanvasRequest, TextAnswer]] = []

    def accept(request: CanvasRequest, value: TextAnswer) -> bool:
        delivered.append((request, value))
        return True

    def reject(_request: CanvasRequest, _value: TextAnswer) -> bool:
        return False

    hidden_request = next(item.request for item in document.activity if isinstance(item, CanvasQuestion) and item.id == "question:hidden")
    assert canvas.answer(SessionRequest("expired", "chat"), TextAnswer("Contoso"), accept) is None
    assert canvas.answer(hidden_request, TextAnswer("Contoso"), accept) is None and not delivered
    assert canvas.answer(SessionRequest("session", "chat"), TextAnswer("Contoso"), reject) is None
    assert [question.id for question in canvas.waiting()] == ["question:chat", "question:current"]
    answered = canvas.answer(SessionRequest("session", "chat"), TextAnswer("Contoso"), accept)
    assert answered is not None and answered == canvas.read()
    chat = next(item for item in answered.activity if item.id == "question:chat")
    assert isinstance(chat, CanvasQuestion) and chat.reply == TextAnswer("Contoso")
    assert finding in answered.activity
    assert canvas.answer(SessionRequest("session", "chat"), TextAnswer("Fabrikam"), accept) is None
    assert delivered == [(SessionRequest("session", "chat"), TextAnswer("Contoso"))]


def test_speech_answers_the_selected_question_or_instructs_only_an_open_canvas(tmp_path: Path) -> None:
    # Defect: speech answers an unselected question, becomes a task while a
    # question is selected, or instructs a canvas the user cannot see.
    canvas = local_canvas(tmp_path)
    canvas.observe_session(Session(identity="session", messages=(asked("chat", "Which supplier?", "", 10),)))
    assert canvas.speech("question:chat", visible=True) == AnswerQuestion(SessionRequest("session", "chat"))
    assert canvas.speech("work:one", visible=True) is SpeechRoute.INSTRUCT
    assert canvas.speech(None, visible=True) is SpeechRoute.INSTRUCT
    assert canvas.speech("question:chat", visible=False) is SpeechRoute.FALLBACK


def test_directions_are_saved_before_queueing_and_retries_reuse_their_binding(tmp_path: Path) -> None:
    # Defect: a failed handoff loses the user's direction, the task is queued
    # before its context is durable, or a retry records a duplicate binding.
    attempts: list[CanvasRun] = []
    path = tmp_path / "canvas.sqlite3"

    def queue(run: CanvasRun) -> None:
        assert run in WorkCanvas(path, queue, autonomous=False).read().runs
        attempts.append(run)
        if len(attempts) == 1:
            raise OSError("Queue unavailable")

    canvas = WorkCanvas(path, queue, autonomous=False)
    run = CanvasRun("canvas:instruction:one", "canvas:root", CanvasInstruction("Compare the two versions."))
    assert canvas.start(run) == NotQueued(CanvasDocument(runs=(run,)), "Queue unavailable")
    assert canvas.start(run) == Queued(CanvasDocument(runs=(run,)))
    assert attempts == [run, run] and canvas.read().runs == (run,)


def test_continue_resumes_or_reports_existing_work_before_queueing_another(tmp_path: Path) -> None:
    # Defect: Continue queues a fresh task while research is blocked or still
    # running, losing its durable recovery context.
    queued: list[CanvasRun] = []
    canvas = WorkCanvas(tmp_path / "canvas.sqlite3", queued.append, autonomous=False)
    blocked = work_task(Waiting(Blocked("Needs recovery")))
    seeded(canvas, CanvasDocument(runs=(CanvasRun(blocked.id, "work:one"),)))
    canvas.observe_work(WorkSnapshot(tasks=(blocked,)))
    assert canvas.continue_work("work:one") == ResumeTask(blocked.id)
    canvas.observe_work(WorkSnapshot(tasks=(work_task(),)))
    assert canvas.continue_work("work:one") is Investigating.ALREADY
    canvas.observe_work(WorkSnapshot(tasks=(replace(blocked, state=Completed("Done", ())),)))
    started = canvas.continue_work("work:one")
    assert isinstance(started, Queued) and queued == [started.document.runs[-1]] and queued[0].work_id == "work:one"
    assert canvas.read().runs == (CanvasRun(blocked.id, "work:one"), queued[0])


def test_released_gestures_commit_placement_and_nesting_or_save_nothing(tmp_path: Path) -> None:
    # Defect: a drop saves a cycle, a nested subtree keeps stale pins that pull
    # it back, a moved bubble is not pinned, or the new parent stays collapsed.
    data, document = nested_bubbles()
    canvas = local_canvas(tmp_path)
    seeded(canvas, replace(document, placements=(Placement("note:annotation", 5, 5),), pinned=frozenset(("note:annotation",))))
    canvas.observe_catalog(data)
    before = canvas.read()
    parent = data.sources[0].id
    with TestCase().assertRaisesRegex(ValueError, "contain"):
        canvas.commit(UserEdit(CanvasScope(), NestBubble(parent, parent, (), frozenset((parent,)))))
    assert canvas.read() == before
    nested = canvas.commit(UserEdit(CanvasScope(), NestBubble("note:annotation", "work:two", (), frozenset(("note:annotation",)))))
    assert context_path("note:annotation", data, nested)[-2:] == ("work:two", "note:annotation")
    assert "note:annotation" not in nested.pinned and "work:two" in view_state(nested, None).expanded
    placed = canvas.commit(UserEdit(CanvasScope(), PlaceBubbles("note:annotation", (Placement("note:annotation", 40, 60),))))
    assert placed == canvas.read() and "note:annotation" in placed.pinned
    rooted = canvas.commit(UserEdit(CanvasScope(), NestBubble("note:annotation", None, (Placement("note:annotation", 90, 30),), frozenset())))
    assert Placement("note:annotation", 90, 30) in rooted.placements and context_path("note:annotation", data, rooted) == ("note:annotation",)


def test_user_edits_apply_to_the_latest_document_and_keep_bridge_updates(tmp_path: Path) -> None:
    # Defect: a user edit saves the panel's rendered copy, or a layout measured
    # before an agent's arrangement replaces that arrangement.
    canvas = local_canvas(tmp_path)
    seeded(canvas, CanvasDocument(collections=(CanvasCollection("group:drafts", "Drafts"),)))
    canvas.observe_catalog(catalog())
    rendered = canvas.read()
    finding = CanvasNote("note:finding", "Finding", "Version two is approved.")
    pinned = Placement("work:one", 300, 40)
    bridge = UpdateCanvas(revision(rendered), (PutNote(finding), MoveBubble("group:drafts", "work:one"), ArrangeCanvas(None, (pinned,))))
    assert isinstance(canvas.command(bridge), CanvasUpdated)
    stale = view_state(rendered, None)
    canvas.commit(UserEdit(CanvasScope(), ArrangeView(stale, replace(stale, placements=(Placement("work:one", 0, 64),)))))
    relation = CanvasRelation("work:one", "work:two", "Same approval")
    canvas.commit(UserEdit(CanvasScope(), PutRelation(relation)))
    current = canvas.commit(UserEdit(CanvasScope(), RenameGroup("group:drafts", "Approvals")))
    assert current == canvas.read() and current.notes == (finding,) and current.relations == (relation,)
    assert current.collections == (CanvasCollection("group:drafts", "Approvals", parent_id="work:one"),)
    assert current.placements == (pinned,) and current.pinned == frozenset(("work:one",))
    fresh = view_state(current, None)
    arranged = replace(fresh, placements=(pinned, Placement("work:two", 0, 64)))
    assert view_state(canvas.commit(UserEdit(CanvasScope(), ArrangeView(fresh, arranged))), None) == arranged == view_state(canvas.read(), None)
