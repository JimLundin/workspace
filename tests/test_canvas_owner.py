"""The canvas owner's observation, attention, answer and user-edit policy."""

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

import contracts.task
from assistant.work_canvas import WorkCanvas
from contracts.agent_session import Session
from contracts.canvas_activity import CanvasInstruction, CanvasQuestion, CanvasRequest, CanvasRun, CanvasUpdate, SessionRequest
from contracts.personal_work import Catalog, DismissedWork, WorkState
from contracts.task import Blocked, Completed, TextAnswer, Waiting
from contracts.work_canvas_commands import (
    ArrangeCanvas,
    CanvasRefused,
    CanvasUpdated,
    MoveBubble,
    PutNote,
    PutRelation,
    ReadCanvas,
    UpdateCanvas,
    revision,
)
from contracts.work_canvas_context import CanvasScope, context_path
from contracts.work_canvas_contracts import Announcement, CanvasPublication, Investigating, NotQueued, Queued, ResumeTask
from contracts.work_canvas_edits import ArrangeView, NestBubble, PlaceBubbles, RenameGroup, SaveNote, UserEdit
from contracts.work_canvas_model import CanvasCollection, CanvasDocument, CanvasNote, CanvasRelation, Placement, view_state
from contracts.work_snapshot import WorkSnapshot
from tests.agent_requests import asked
from tests.test_work_canvas import catalog, local_canvas, nested_bubbles, publish_nothing, seeded
from tests.test_work_window import work_task


def test_canvas_serializes_commits_through_ordered_publication(tmp_path: Path) -> None:
    # Defect: another writer commits while the first transaction's publication
    # is still pending, exposing notifications out of order or losing an edit.
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
    publications: list[CanvasPublication] = []

    def publish(publication: CanvasPublication) -> None:
        if len(publication.document.notes) == 1:
            entered.set()
            assert release.wait(5)
        publications.append(publication)

    canvas = local_canvas(tmp_path, publish)
    first_note = CanvasNote("note:first", "First", "First finding")
    second_note = CanvasNote("note:second", "Second", "Second finding")
    first = UserEdit(CanvasScope(), SaveNote(first_note))
    second = UserEdit(CanvasScope(), SaveNote(second_note))

    def commit_second() -> CanvasDocument:
        second_started.set()
        return canvas.commit(second)

    with ThreadPoolExecutor(max_workers=2) as workers:
        committed_first = workers.submit(canvas.commit, first)
        try:
            assert entered.wait(5)
            committed_second = workers.submit(commit_second)
            assert second_started.wait(5)
            try:
                committed_second.result(timeout=0.1)
            except TimeoutError:
                pass
            else:
                raise AssertionError("A second writer bypassed the owner's publication order.")
        finally:
            release.set()
        assert committed_first.result(timeout=5).notes == (first_note,)
        assert committed_second.result(timeout=5).notes == (first_note, second_note)
    assert tuple(len(publication.document.notes) for publication in publications) == (1, 2)


def test_changed_evidence_queues_one_bounded_investigation_and_refusal_releases_it(tmp_path: Path) -> None:
    # Defect: catalog publication never investigates, repeats queued work,
    # announces the silent baseline, or a refused queue marks evidence handled.
    queued: list[CanvasRun] = []
    publications: list[CanvasPublication] = []
    canvas = WorkCanvas(tmp_path / "canvas.sqlite3", queued.append, publications.append, autonomous=True)
    canvas.observe_catalog(catalog())
    first = publications[-1]
    assert queued and first.document.runs == tuple(queued) == canvas.read().runs and first.notice is None
    canvas.observe_catalog(catalog())
    repeated = publications[-1]
    assert len(queued) == 1 and repeated.document.runs == tuple(queued) and repeated.notice is None
    assert len(publications) == 2

    def refuse(_run: CanvasRun) -> None:
        raise ValueError("The queue is full.")

    refused = WorkCanvas(tmp_path / "refused.sqlite3", refuse, publications.append, autonomous=True)
    refused.observe_catalog(catalog())
    assert not publications[-1].document.runs and not refused.read().runs and len(publications) == 3
    manual = WorkCanvas(tmp_path / "manual.sqlite3", queued.append, publications.append, autonomous=False)
    manual.observe_catalog(catalog())
    assert not publications[-1].document.runs and len(queued) == 1 and len(publications) == 4


def test_user_notes_wake_intake_and_agent_notes_do_not_launch_recursive_tasks(tmp_path: Path) -> None:
    # Defect: user-added evidence waits for unrelated polling, while an agent's
    # own conclusions launch endless new runs or invalidate its canvas edit token.
    queued: list[CanvasRun] = []
    canvas = WorkCanvas(tmp_path / "canvas.sqlite3", queued.append, publish_nothing, autonomous=True)
    canvas.observe_catalog(Catalog())
    authored = CanvasNote("note:agent", "Finding", "Approval is recorded in the supplier document.")
    response = canvas.command(UpdateCanvas(revision(canvas.read()), (PutNote(authored),)))
    assert isinstance(response, CanvasUpdated) and not queued
    canvas.observe_catalog(Catalog())
    assert not queued
    handwritten = CanvasNote("note:user", "New evidence", "The supplier moved the deadline to Friday.")
    canvas.commit(UserEdit(CanvasScope(), SaveNote(handwritten)))
    assert len(queued) == 1 and queued[0].work_id == handwritten.id
    canvas.observe_catalog(Catalog())
    assert len(queued) == 1


def test_attention_is_announced_once_and_never_from_dismissed_work(tmp_path: Path) -> None:
    # Defect: repeated snapshots duplicate desktop prompts, dismissed work
    # announces late results, or a work state change stays silent.
    data = catalog()
    active, dismissed = data.works
    research, late = work_task(identity="research"), work_task(identity="late")
    publications: list[CanvasPublication] = []
    canvas = local_canvas(tmp_path, publications.append)
    seeded(canvas, CanvasDocument(runs=(CanvasRun(research.id, active.id), CanvasRun(late.id, dismissed.id))))
    shown = replace(data, works=(active,), dismissed=(DismissedWork(dismissed, "Wrong owner"),))
    canvas.observe_catalog(shown)
    canvas.observe_work(WorkSnapshot(tasks=(research, late)))
    completed = WorkSnapshot(tasks=tuple(replace(task, state=Completed("Handoff confirmed", ())) for task in (research, late)))
    canvas.observe_work(completed)
    canvas.observe_work(completed)
    done = replace(shown, works=(replace(active, definition=replace(active.definition, state=WorkState.DONE)),))
    canvas.observe_catalog(done)
    assert tuple(publication.notice for publication in publications) == (
        None,
        None,
        Announcement(research.title, "result:" + research.id),
        None,
        Announcement("Canvas updated · " + active.definition.title, active.id),
    )


def test_answers_reach_only_visible_waiting_questions_and_record_one_reply(tmp_path: Path) -> None:
    # Defect: a reply reaches an expired or dismissed request, a rejected
    # delivery is recorded as answered, or a question can be answered twice.
    data = catalog()
    active, dismissed = data.works
    canvas = local_canvas(tmp_path)
    canvas.observe_catalog(replace(data, works=(active,), dismissed=(DismissedWork(dismissed, "Wrong owner"),)))
    current = work_task(Waiting(contracts.task.Question("current", "Current question", "")), identity="current-task")
    hidden = work_task(Waiting(contracts.task.Question("hidden", "Hidden question", "")), identity="hidden-task")
    finding = CanvasUpdate("result:finding", "Finding", "Version two is approved.", 5, (active.id,))
    seeded(canvas, CanvasDocument(runs=(CanvasRun(current.id, active.id), CanvasRun(hidden.id, dismissed.id)), activity=(finding,)))
    canvas.observe_session(Session(identity="session", messages=(asked("chat", "Which supplier?", "", 10),)))
    canvas.observe_work(WorkSnapshot(tasks=(current, hidden)))
    document = canvas.read()
    delivered: list[tuple[CanvasRequest, TextAnswer]] = []

    def accept(request: CanvasRequest, value: TextAnswer) -> bool:
        delivered.append((request, value))
        return True

    def reject(_request: CanvasRequest, _value: TextAnswer) -> bool:
        return False

    hidden_request = next(item.request for item in document.activity if isinstance(item, CanvasQuestion) and item.id == "question:hidden")
    assert not canvas.answer(SessionRequest("expired", "chat"), TextAnswer("Contoso"), accept)
    assert not canvas.answer(hidden_request, TextAnswer("Contoso"), accept) and not delivered
    assert not canvas.answer(SessionRequest("session", "chat"), TextAnswer("Contoso"), reject)
    assert canvas.answer(SessionRequest("session", "chat"), TextAnswer("Contoso"), accept)
    answered = canvas.read()
    chat = next(item for item in answered.activity if item.id == "question:chat")
    assert isinstance(chat, CanvasQuestion) and chat.reply == TextAnswer("Contoso")
    assert finding in answered.activity
    assert not canvas.answer(SessionRequest("session", "chat"), TextAnswer("Fabrikam"), accept)
    assert delivered == [(SessionRequest("session", "chat"), TextAnswer("Contoso"))]


def test_each_change_publishes_current_attention_and_bridge_moves_settle_hidden_questions(tmp_path: Path) -> None:
    # Defect: a write path saves without publishing, publishes more than once,
    # publishes stale attention after a bridge move, or publishes a refused/no-op edit.
    data = catalog()
    active, dismissed = data.works
    publications: list[CanvasPublication] = []
    canvas = local_canvas(tmp_path, publications.append)
    canvas.observe_catalog(replace(data, works=(active,), dismissed=(DismissedWork(dismissed, "Wrong owner"),)))
    current = work_task(Waiting(contracts.task.Question("current", "Current question", "")), identity="current-task")
    hidden = work_task(Waiting(contracts.task.Question("hidden", "Hidden question", "")), identity="hidden-task")
    seeded(
        canvas,
        CanvasDocument(
            collections=(CanvasCollection("group:archive", "Archive", parent_id=dismissed.id),),
            notes=(CanvasNote("note:stable", "Stable", "Keep this finding."),),
            runs=(CanvasRun(current.id, active.id), CanvasRun(hidden.id, dismissed.id)),
        ),
    )

    def expect(count: int, waiting: tuple[str, ...], settled: frozenset[str]) -> None:
        assert len(publications) == count
        publication = publications[-1]
        assert publication.document == canvas.read()
        assert tuple(question.id for question in publication.waiting) == waiting
        assert publication.settled == settled

    session = Session(identity="session", messages=(asked("chat", "Which supplier?", "", 10),))
    assert canvas.observe_session(session)
    expect(2, ("question:chat",), frozenset())
    assert not canvas.observe_session(session) and len(publications) == 2
    canvas.observe_work(WorkSnapshot(tasks=(current, hidden)))
    expect(3, ("question:chat", "question:current"), frozenset(("question:hidden",)))
    rename = UserEdit(CanvasScope(), RenameGroup("group:archive", "Archived work"))
    assert canvas.commit(rename) == canvas.read()
    expect(4, ("question:chat", "question:current"), frozenset(("question:hidden",)))
    assert isinstance(canvas.start(CanvasRun("manual", active.id)), Queued)
    expect(5, ("question:chat", "question:current"), frozenset(("question:hidden",)))
    command = UpdateCanvas(revision(canvas.read()), (MoveBubble("question:current", "group:archive"),))
    assert isinstance(canvas.command(command), CanvasUpdated)
    expect(6, ("question:chat",), frozenset(("question:hidden", "question:current")))
    delivered: list[tuple[CanvasRequest, TextAnswer]] = []

    def deliver(request: CanvasRequest, answer: TextAnswer) -> bool:
        delivered.append((request, answer))
        return True

    assert canvas.answer(SessionRequest("session", "chat"), TextAnswer("Contoso"), deliver)
    expect(7, (), frozenset(("question:hidden", "question:current", "question:chat")))
    assert delivered == [(SessionRequest("session", "chat"), TextAnswer("Contoso"))]
    canvas.command(ReadCanvas())
    canvas.commit(rename)
    assert isinstance(canvas.command(UpdateCanvas(revision(canvas.read()), (PutNote(canvas.read().notes[0]),))), CanvasUpdated)
    assert isinstance(canvas.command(command), CanvasRefused)
    assert not canvas.answer(SessionRequest("session", "chat"), TextAnswer("Again"), deliver)
    expect(7, (), frozenset(("question:hidden", "question:current", "question:chat")))


def test_directions_are_saved_before_queueing_and_retries_reuse_their_binding(tmp_path: Path) -> None:
    # Defect: a failed handoff loses the user's direction, the task is queued
    # before its context is durable, or a retry records a duplicate binding.
    attempts: list[CanvasRun] = []
    publications: list[CanvasPublication] = []
    path = tmp_path / "canvas.sqlite3"

    def queue(run: CanvasRun) -> None:
        assert run in WorkCanvas(path, queue, publish_nothing, autonomous=False).read().runs
        attempts.append(run)
        if len(attempts) == 1:
            raise OSError("Queue unavailable")

    canvas = WorkCanvas(path, queue, publications.append, autonomous=False)
    run = CanvasRun("canvas:instruction:one", "canvas:root", CanvasInstruction("Compare the two versions."))
    assert canvas.start(run) == NotQueued(CanvasDocument(runs=(run,)), "Queue unavailable")
    assert canvas.start(run) == Queued(CanvasDocument(runs=(run,)))
    assert attempts == [run, run] and canvas.read().runs == (run,)
    assert len(publications) == 2 and all(publication.document == canvas.read() for publication in publications)


def test_continue_resumes_or_reports_existing_work_before_queueing_another(tmp_path: Path) -> None:
    # Defect: Continue queues a fresh task while research is blocked or still
    # running, losing its durable recovery context.
    queued: list[CanvasRun] = []
    publications: list[CanvasPublication] = []
    canvas = WorkCanvas(tmp_path / "canvas.sqlite3", queued.append, publications.append, autonomous=False)
    blocked = work_task(Waiting(Blocked("Needs recovery")))
    seeded(canvas, CanvasDocument(runs=(CanvasRun(blocked.id, "work:one"),)))
    canvas.observe_work(WorkSnapshot(tasks=(blocked,)))
    assert canvas.continue_work("work:one") == ResumeTask(blocked.id)
    assert len(publications) == 1
    canvas.observe_work(WorkSnapshot(tasks=(work_task(),)))
    assert canvas.continue_work("work:one") is Investigating.ALREADY
    assert len(publications) == 2
    canvas.observe_work(WorkSnapshot(tasks=(replace(blocked, state=Completed("Done", ())),)))
    started = canvas.continue_work("work:one")
    assert isinstance(started, Queued) and queued == [started.document.runs[-1]] and queued[0].work_id == "work:one"
    assert canvas.read().runs == (CanvasRun(blocked.id, "work:one"), queued[0])
    assert len(publications) == 4 and publications[-1].document == canvas.read()


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
