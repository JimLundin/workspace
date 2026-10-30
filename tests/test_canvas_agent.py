"""Agent construction and investigation policies, through immutable observations."""

from dataclasses import replace
from unittest import TestCase

from assistant.canvas_activity import CanvasRun, CanvasUpdate
from assistant.work_canvas import pending, retained
from assistant.work_canvas_commands import (
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
from assistant.work_canvas_context import context_path
from assistant.work_canvas_model import CanvasDocument, CanvasNote, CanvasRelation, CanvasViewState, Placement, view_state
from automation.personal_work import Association, SourceKind, WorkState, source_id
from automation.task import Completed, Question, Waiting
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
    planned = pending(data, CanvasDocument(), ())
    assert len(planned) == 2 and all(run.evidence for run in planned)
    document = CanvasDocument(runs=planned)
    completed = tuple(replace(work_task(identity=run.task_id), state=Completed("Collected context", ())) for run in planned)
    assert not pending(data, document, completed)
    own_references = tuple(source(kind, "decision") for kind in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE))
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
    changed_mail = replace(data.sources[0], revision="changed-mail")
    changed = replace(data, sources=(changed_mail, data.sources[1]))
    waiting = tuple(replace(task, state=Waiting(Question("choose-version", "Which version?", "Two observed candidates"))) for task in completed)
    assert not pending(changed, document, waiting)
    next_runs = pending(changed, document, completed)
    assert len(next_runs) == 2 and next_runs[0].task_id != planned[0].task_id
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
    child = replace(root, id=source_id(root.kind, "child", parent_id=root.id), identity="child", parent_id=root.id, revision="child-v1")
    updated = replace(data, sources=(*data.sources, child))
    assert len(pending(updated, CanvasDocument(runs=original), completed)) == 2
    crowded = replace(data, works=tuple(replace(data.works[0], id="work:" + str(i)) for i in range(10)))
    first = pending(crowded, CanvasDocument(), ())
    assert len(first) == 3
    assert not pending(crowded, CanvasDocument(runs=first), ())
    one_finished = (replace(work_task(identity=first[0].task_id), state=Completed("Done", ())),)
    assert len(pending(crowded, CanvasDocument(runs=first), one_finished)) == 1


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
