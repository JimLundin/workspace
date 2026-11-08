"""Agent construction and investigation policies, through immutable observations."""

from dataclasses import replace
from unittest import TestCase

from assistant.work_canvas import pending, retained
from contracts.canvas_activity import CanvasIntake, CanvasResearch, CanvasRun, CanvasUpdate
from contracts.personal_work import Association, Catalog, OutlookSource, SourceKind, SourceOrigin, TeamsSource, WorkState, source_id
from contracts.task import Completed, Question, Waiting
from contracts.work_canvas_commands import (
    CANVAS_RESPONSE,
    ArrangeCanvas,
    ExpandBubble,
    MoveBubble,
    PutGroup,
    PutNote,
    PutRelation,
    ReadCanvas,
    RemoveRelation,
    UpdateCanvas,
    edited,
    revision,
    snapshot,
)
from contracts.work_canvas_context import context_path
from contracts.work_canvas_model import CanvasDocument, CanvasNote, CanvasRelation, CanvasViewState, Placement, view_state
from tests.personal_work_fixture import source
from tests.test_work_canvas import catalog
from tests.test_work_window import work_task


def test_agent_batch_builds_nested_evidence_and_arranges_without_changing_connections() -> None:
    # Defect: agent edits copy sources, lose factual work links, fail to move
    # between containers, or overwrite unrelated layout/activity observations.
    data = catalog()
    mail = data.sources[0]
    result = CanvasUpdate("result:research", "Compared documents", "The email names version two.", 20, ("work:one",))
    original = CanvasDocument(activity=(result,), runs=(CanvasRun("run", "work:one"),))
    edits = (
        PutGroup("group:documents", "Document candidates", "work:one"),
        PutNote(CanvasNote("note:version", "Version evidence", "Two different approvals.", "work:one")),
        MoveBubble("note:version", "group:documents"),
        MoveBubble(mail.id, "group:documents"),
        MoveBubble("note:version", mail.id),
        ExpandBubble(mail.id, "work:one", expanded=False),
        ArrangeCanvas("work:one", (Placement("group:documents", 50, 80),)),
    )
    current = edited(original, UpdateCanvas(revision(original), edits), data)
    assert context_path("note:version", data, current) == ("work:one", "group:documents", mail.id, "note:version")
    assert current.collections[0].members == (mail.id,)
    assert current.activity == original.activity and current.runs == original.runs
    assert view_state(current, "work:one").pinned == frozenset({"group:documents"})
    assert mail.id in view_state(current, "work:one").collapsed
    renamed = edited(current, UpdateCanvas(revision(current), (PutGroup("group:documents", "Reviewed candidates", "work:one"),)), data)
    assert renamed.collections[0].members == (mail.id,)
    assert data == catalog()
    released = edited(renamed, UpdateCanvas(revision(renamed), (MoveBubble("note:version", None), ArrangeCanvas("work:one"))), data)
    assert context_path("note:version", data, released) == ("note:version",)
    assert not view_state(released, "work:one").pinned
    assert released.placements == original.placements


def test_stale_invalid_and_cyclic_batches_never_produce_partial_documents() -> None:
    # Defect: a batch overwrites a concurrent user edit or accepts an early
    # valid addition before a later unknown identity/cycle is rejected.
    data = catalog()
    original = CanvasDocument()
    note = PutNote(CanvasNote("note:evidence", "Evidence", "Original"))
    changed = edited(original, UpdateCanvas(revision(original), (note,)), data)
    cases = (
        UpdateCanvas(revision(original), (PutNote(CanvasNote("note:evidence", "Stale")),)),
        UpdateCanvas(revision(changed), (PutGroup("group:one", "New group"), MoveBubble("missing", "group:one"))),
        UpdateCanvas(
            revision(changed),
            (PutGroup("group:one", "New group"), MoveBubble("note:evidence", "group:one"), MoveBubble("group:one", "note:evidence")),
        ),
    )
    for command in cases:
        with TestCase().assertRaises(ValueError):
            edited(changed, command, data)
    assert changed.notes == (note.note,) and not changed.collections


def test_background_layout_and_activity_preserve_edit_token_but_user_pins_invalidate_it() -> None:
    # Defect: background reflow constantly rejects valid agent edits, or a pin
    # added by the user gets overwritten by an old arrangement command.
    data = catalog()
    original = CanvasDocument()
    reflow = replace(original, placements=(Placement(data.sources[0].id, 30, 40),), runs=(CanvasRun("run", "work:one"),))
    assert revision(reflow) == revision(original)
    changed = edited(reflow, UpdateCanvas(revision(original), (PutNote(CanvasNote("note:one", "Observed fact")),)), data)
    assert changed.placements == reflow.placements and changed.runs == reflow.runs
    pinned = replace(reflow, pinned=frozenset({data.sources[0].id}))
    with TestCase().assertRaisesRegex(ValueError, "changed"):
        edited(pinned, UpdateCanvas(revision(original), (ArrangeCanvas(),)), data)


def test_investigations_deduplicate_research_and_wait_for_the_same_question() -> None:
    # Defect: polling starts duplicate work, agent-written summaries/documents
    # loop into new research, or changed mail starts another task while asking.
    data = catalog()
    data = replace(data, works=(replace(data.works[0], links=data.works[1].links),))
    planned = pending(data, CanvasDocument(), ())
    assert len(planned) == 1 and all(run.evidence for run in planned)
    document = CanvasDocument(runs=planned)
    completed = tuple(replace(work_task(identity=run.task_id), state=Completed("Collected context", ())) for run in planned)
    assert not pending(data, document, completed)
    own_references = tuple(replace(source(kind, "decision"), origin=SourceOrigin.AGENT) for kind in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE))
    own_update = replace(
        data,
        sources=(*data.sources, *own_references),
        works=tuple(
            replace(
                work,
                definition=replace(work.definition, summary="Useful findings"),
                links=(*work.links, *(Association(item.id, "Research evidence") for item in own_references)),
            )
            for work in data.works
        ),
    )
    assert not pending(own_update, document, completed)
    mail = data.sources[0]
    assert isinstance(mail, TeamsSource | OutlookSource)
    changed_mail = replace(mail, revision="changed-mail")
    changed = replace(data, sources=(changed_mail, data.sources[1]))
    waiting = tuple(replace(task, state=Waiting(Question("choose-version", "Which version?", "Two observed candidates"))) for task in completed)
    assert not pending(changed, document, waiting)
    next_runs = pending(changed, document, completed)
    assert len(next_runs) == 1 and next_runs[0].task_id != planned[0].task_id
    recorded = replace(document, runs=(*planned, *next_runs, CanvasRun("manual", "work:one")))
    assert retained(recorded, completed).runs == (*next_runs, CanvasRun("manual", "work:one"))
    closed = replace(changed, works=tuple(replace(work, definition=replace(work.definition, state=WorkState.DONE)) for work in changed.works))
    assert not pending(closed, document, completed)


def test_child_message_changes_trigger_research_and_capacity_stays_bounded() -> None:
    # Defect: a conversation's unchanged aggregate hides a new email, or a
    # burst creates unbounded investigations instead of serialized work.
    data = catalog()
    original = pending(data, CanvasDocument(), ())
    completed = tuple(replace(work_task(identity=run.task_id), state=Completed("Done", ())) for run in original)
    root = data.sources[0]
    assert isinstance(root, TeamsSource | OutlookSource)
    child = replace(root, id=source_id(root.kind, "child", parent_id=root.id), identity="child", parent_id=root.id, revision="child-v1")
    updated = replace(data, sources=(*data.sources, child))
    assert len(pending(updated, CanvasDocument(runs=original), completed)) == 1
    crowded = replace(data, works=tuple(replace(data.works[0], id="work:" + str(i)) for i in range(10)))
    first = pending(crowded, CanvasDocument(), ())
    assert len(first) == 1
    assert not pending(crowded, CanvasDocument(runs=first), ())
    one_finished = (replace(work_task(identity=first[0].task_id), state=Completed("Done", ())),)
    assert len(pending(crowded, CanvasDocument(runs=first), one_finished)) == 1


def test_unconnected_evidence_is_reviewed_once_and_bursts_wait_in_order() -> None:
    # Defect: evidence outside work links never reaches the agent, duplicate
    # observations launch more work, or a burst loses sources while intake is busy.
    mail, chat = source(SourceKind.OUTLOOK), source(SourceKind.TEAMS)
    data = Catalog(sources=(mail, chat))
    first = pending(data, CanvasDocument(), ())
    assert len(first) == 1 and first[0].work_id == mail.id and isinstance(first[0].intent, CanvasIntake)
    document = CanvasDocument(runs=first)
    assert not pending(data, document, ())
    # Defect: an unanswered clarification stalls intake for unrelated arrivals,
    # even though the paused task consumes no execution slot.
    waiting = replace(work_task(identity=first[0].task_id), state=Waiting(Question("owner", "Who owns this?", "")))
    resumed_intake = pending(data, document, (waiting,))
    assert len(resumed_intake) == 1 and resumed_intake[0].work_id == chat.id
    completed = replace(work_task(identity=first[0].task_id), state=Completed("Reviewed", ()))
    second = pending(data, document, (completed,))
    assert len(second) == 1 and second[0].work_id == chat.id
    document = replace(document, runs=(*first, *second))
    completed_both = (completed, replace(work_task(identity=second[0].task_id), state=Completed("Reviewed", ())))
    assert not pending(data, document, completed_both)
    compacted = retained(document, completed_both)
    assert not compacted.runs and len(compacted.reviewed) == 2
    assert not pending(data, compacted, completed_both)
    changed = replace(data, sources=(replace(mail, revision="new-mail"), chat))
    assert pending(changed, document, completed_both)[0].task_id != first[0].task_id
    authored = replace(source(SourceKind.DOCUMENT), origin=SourceOrigin.AGENT)
    manual = replace(authored, origin=SourceOrigin.USER)
    assert not pending(Catalog(sources=(authored,)), CanvasDocument(), ())
    assert pending(Catalog(sources=(manual,)), CanvasDocument(), ())[0].work_id == manual.id
    sources = tuple(source(SourceKind.OUTLOOK, str(index)) for index in range(4))
    waiting_runs = tuple(CanvasRun("intake:" + str(index), item.id, CanvasIntake(item.revision)) for index, item in enumerate(sources[:3]))
    waiting_tasks = tuple(
        replace(work_task(identity=run.task_id), state=Waiting(Question("owner:" + str(index), "Who owns this?", "")))
        for index, run in enumerate(waiting_runs)
    )
    assert not pending(Catalog(sources=sources), CanvasDocument(runs=waiting_runs), waiting_tasks)


def test_waiting_research_backlog_does_not_prevent_new_evidence_intake() -> None:
    # Defect: four existing unanswered research tasks exhaust the global budget
    # and prevent any new meeting, email or user note from reaching the agent.
    prior = tuple(CanvasRun("research:" + str(index), "work:" + str(index), CanvasResearch("revision")) for index in range(4))
    tasks = tuple(
        replace(work_task(identity=run.task_id), state=Waiting(Question("owner:" + str(index), "Who owns this?", "")))
        for index, run in enumerate(prior)
    )
    mail = source(SourceKind.OUTLOOK)
    document = CanvasDocument(runs=prior)
    intake = pending(Catalog(sources=(mail,)), document, tasks)
    assert len(intake) == 1 and intake[0].work_id == mail.id and isinstance(intake[0].intent, CanvasIntake)
    assert not pending(Catalog(sources=(mail,)), replace(document, runs=(*prior, *intake)), tasks)
    note = CanvasNote("note:arrival", "New evidence", "Supplier approval arrived.")
    assert pending(Catalog(), replace(document, notes=(note,)), tasks)[0].work_id == note.id
    # Starting further work research still waits for its unanswered predecessors.
    assert not pending(catalog(), document, tasks)


def test_canvas_read_pages_keep_full_topology_and_bound_large_activity_bodies() -> None:
    # Defect: large research results truncate bridge JSON, or paging loses the
    # edit token and pieces needed to navigate the same work canvas.
    document = CanvasDocument(activity=tuple(CanvasUpdate("result:" + str(i), "Research", "Evidence " * 3400, 20, ("work:one",)) for i in range(25)))
    first = snapshot(document, catalog(), ReadCanvas())
    assert first.next_offset is not None and first.next_offset < 20
    assert len(CANVAS_RESPONSE.dump_json(first)) <= 500000
    second = snapshot(document, catalog(), ReadCanvas(offset=first.next_offset))
    assert first.revision == second.revision == revision(document)
    assert (*first.document.activity, *second.document.activity) == document.activity and second.next_offset is None
    assert first.source_ids == second.source_ids


def test_agent_relationship_edits_validate_endpoints_and_keep_containment() -> None:
    # Defect: an agent link is absent from the revision contract, mutates
    # containment, or commits a relationship to an unknown bubble.
    data = catalog()
    original = CanvasDocument()
    relation = CanvasRelation(data.sources[0].id, data.sources[1].id, "Supports the outcome")
    linked = edited(original, UpdateCanvas(revision(original), (PutRelation(relation),)), data)
    assert linked.relations == (relation,) and not linked.nesting
    assert revision(linked) != revision(original)
    with TestCase().assertRaisesRegex(ValueError, "Unknown"):
        edited(linked, UpdateCanvas(revision(linked), (PutRelation(CanvasRelation(relation.start, "missing")),)), data)
    unlinked = edited(linked, UpdateCanvas(revision(linked), (RemoveRelation(relation.start, relation.end),)), data)
    assert unlinked == original


def test_agent_reparent_releases_subtree_pins_in_every_scope() -> None:
    # Defect: pins from the old owner survive a structural move and override
    # the new container's arrangement on its next expansion.
    data = catalog()
    parent, child = "note:parent", "note:child"
    document = CanvasDocument(
        notes=(CanvasNote(parent, "Context"), CanvasNote(child, "Evidence", context_id=parent)),
        placements=(Placement(parent, 30, 40), Placement(child, 50, 80)),
        pinned=frozenset((parent, child)),
        views=(CanvasViewState(parent, placements=(Placement(child, 100, 120),), pinned=frozenset((child,))),),
    )
    updated = edited(document, UpdateCanvas(revision(document), (MoveBubble(parent, data.works[0].id),)), data)
    assert not updated.pinned and not updated.placements
    assert not updated.views[0].pinned and not updated.views[0].placements
    assert context_path(child, data, updated) == (data.works[0].id, parent, child)
