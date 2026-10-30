"""Workspace containment, shared identity, layout and scoped arrangement policy."""

import sqlite3
from contextlib import closing
from dataclasses import replace
from itertools import islice
from pathlib import Path
from unittest import TestCase

from assistant.canvas_activity import Attention, CanvasQuestion, CanvasRun, CanvasUpdate, TaskRequest
from assistant.work_canvas import WorkCanvas
from assistant.work_canvas_connections import CanvasConnection, RelationConnection, connections
from assistant.work_canvas_context import CanvasMode, CanvasScene, CanvasScope, context_path, project, scene_contents
from assistant.work_canvas_layout import Box, Measurements, Size, layout
from assistant.work_canvas_model import (
    DOCUMENT,
    CanvasCollection,
    CanvasDocument,
    CanvasNote,
    CanvasRelation,
    CanvasViewState,
    Placement,
    collect,
    contents,
    nest,
    save_collection,
    save_note,
    save_view,
    toggle_expansion,
    view_state,
)
from automation.personal_work import Association, Catalog, DismissedWork, SourceKind, WorkDefinition, WorkThread, source_id
from tests.personal_work_fixture import source


def queue_nothing(_run: CanvasRun) -> None:
    pass


def local_canvas(folder: Path) -> WorkCanvas:
    return WorkCanvas(folder / "canvas.sqlite3", queue_nothing, autonomous=False)


def seeded(canvas: WorkCanvas, document: CanvasDocument) -> None:
    """Store a fixture document; the owner itself accepts only edits and observations."""
    with closing(sqlite3.connect(canvas.path)) as connection, connection:
        connection.execute("UPDATE canvas SET payload=? WHERE id=1", (DOCUMENT.dump_json(document),))


def catalog() -> Catalog:
    shared, other = source(SourceKind.OUTLOOK), source(SourceKind.KANBAN)
    one = WorkThread("work:one", 0, WorkDefinition("First context", "Complete first"), (Association(shared.id, "Shared approval"),), 10, 10)
    two = replace(one, id="work:two", links=(Association(shared.id, "Shared approval"), Association(other.id, "Tracks the outcome")))
    return Catalog(works=(one, two), sources=(shared, other))


def measure(scene: CanvasScene) -> Measurements:
    return Measurements(frozendict((item.id, Size(360, 160)) for item in scene_contents(scene)), 1500)


def assert_separated(state: CanvasViewState, measurements: Measurements) -> None:
    boxes = tuple(
        Box(p.x, p.y, measurements.sizes[p.id].width, measurements.sizes[p.id].height) for p in state.placements if p.id in measurements.sizes
    )
    assert all(not one.overlaps(two) for index, one in enumerate(boxes) for two in boxes[index + 1 :])


def test_work_is_a_container_and_shared_sources_keep_one_identity_per_canvas() -> None:
    # Defect: classifying a ticket creates another content bubble, or shared
    # evidence is duplicated globally and disappears from its other context.
    data = catalog()
    document = CanvasDocument()
    assert contents(data, document) == data.sources
    overview = project(data, document, CanvasScope())
    assert tuple(group.id for group in overview.groups) == ("work:one", "work:two")
    assert scene_contents(overview) == data.sources
    focused = project(data, document, CanvasScope(("work:two",)))
    assert focused.groups[0].container == data.works[1] and focused.groups[0].expanded
    assert scene_contents(focused) == data.sources
    corrected = replace(data, works=(replace(data.works[0], links=()), data.works[1]))
    assert scene_contents(project(corrected, document, CanvasScope())) == data.sources


def test_unconnected_references_have_a_collapsed_container_and_a_real_navigation_route() -> None:
    # Defect: unclassified source observations become loose bubbles far below
    # work, or grouping them makes source redirects unable to reveal them.
    loose = source(SourceKind.OUTLOOK)
    data = Catalog(sources=(loose,))
    overview = project(data, CanvasDocument(), CanvasScope())
    assert not overview.items and len(overview.groups) == 1
    inbox = overview.groups[0]
    assert inbox.id == "inbox:unconnected" and not inbox.expanded
    assert not scene_contents(overview)
    assert context_path(loose.id, data, CanvasDocument()) == (inbox.id, loose.id)
    focused = project(data, CanvasDocument(), CanvasScope((inbox.id,)))
    assert scene_contents(focused) == (loose,)


def test_dismissed_work_hides_its_nested_context_but_retains_shared_sources() -> None:
    # Defect: removing a work header leaves its questions/notes/documents loose,
    # or dismissal hides a shared source still needed by another work.
    data = catalog()
    dismissed, active = data.works
    note = CanvasNote("note:dismissed", "Private context", "Belongs to dismissed work", dismissed.id)
    result = CanvasUpdate("result:nested", "Research finding", "Belongs to the hidden note", 20, (note.id,))
    document = CanvasDocument(notes=(note,), activity=(result,))
    revised = replace(data, works=(active,), dismissed=(DismissedWork(dismissed, "Not mine"),))
    scene = project(revised, document, CanvasScope())
    assert all(group.id != dismissed.id for group in scene.groups)
    assert note not in scene_contents(scene) and data.sources[0] in scene_contents(scene)
    assert result not in contents(revised, document)


def test_dismissal_preserves_shared_conversation_context_and_routes_to_active_work() -> None:
    # Defect: linking an individual email to active work hides its conversation
    # after the original work is dismissed, or redirects follow the dismissed work.
    data = catalog()
    conversation = data.sources[0]
    message = replace(
        conversation, id=source_id(SourceKind.OUTLOOK, "message", parent_id=conversation.id), identity="message", parent_id=conversation.id
    )
    dismissed, active = data.works
    active = replace(active, links=(Association(message.id, "Specific approval"),))
    question = CanvasQuestion(
        "question:shared",
        "Which version?",
        "Choose the approved version.",
        12,
        TaskRequest("task", "version"),
        Attention.WAITING,
        (dismissed.id, active.id),
    )
    revised = replace(data, sources=(conversation, message), works=(active,), dismissed=(DismissedWork(dismissed, "Not mine"),))
    document = CanvasDocument(activity=(question,))
    assert conversation in contents(revised, document) and message in contents(revised, document)
    assert context_path(message.id, revised, document) == (active.id, conversation.id, message.id)
    assert context_path(question.id, revised, document) == (active.id, question.id)


def test_factual_connections_follow_shared_evidence_through_collapsed_containers() -> None:
    # Defect: a shared reference disappears when its containing work collapses,
    # produces a redundant containment line, or retains a removed association.
    data = catalog()
    document = CanvasDocument()
    source = data.sources[0]
    assert connections(data, project(data, document, CanvasScope())) == (CanvasConnection("work:two", source.id, "Shared approval"),)
    document = toggle_expansion(document, None, "work:one", expanded=False)
    assert connections(data, project(data, document, CanvasScope())) == (CanvasConnection("work:two", "work:one", "Shared approval"),)
    assert not connections(data, project(data, document, CanvasScope(("work:two",))))
    corrected = replace(data, works=(data.works[0], replace(data.works[1], links=())))
    assert not connections(corrected, project(corrected, document, CanvasScope()))
    document = save_collection(document, CanvasCollection("group:both", "Shared project"))
    document = nest(nest(document, "group:both", "work:one"), "group:both", "work:two")
    document = toggle_expansion(document, None, "group:both", expanded=False)
    assert not connections(data, project(data, document, CanvasScope()))


def test_nested_groups_and_corrections_preserve_canonical_membership() -> None:
    # Defect: nesting copies the work/source instead of grouping it, a cycle
    # hides the group tree, or a local grouping removes factual source links.
    data = catalog()
    group = CanvasCollection("group:project", "Project")
    child = CanvasCollection("group:handoff", "Handoff", parent_id=group.id)
    document = save_collection(save_collection(CanvasDocument(), group), child)
    document = collect(document, child.id, data.works[1].id)
    assert context_path(data.works[1].id, data, document) == (group.id, child.id, data.works[1].id)
    note = CanvasNote("note:decision", "Receiving owner", "Contoso", child.id)
    document = save_note(document, note)
    focused = project(data, document, CanvasScope((group.id, child.id)))
    assert focused.groups[0].children[0].container == data.works[1]
    assert note in focused.groups[0].items and tuple(scene_contents(focused)).count(data.sources[0]) == 1
    assert data.works[1].links == catalog().works[1].links
    with TestCase().assertRaisesRegex(ValueError, "cycle"):
        collect(document, child.id, group.id)
    with TestCase().assertRaisesRegex(ValueError, "cycle"):
        save_collection(document, replace(group, parent_id=data.works[1].id))


def test_scoped_positions_survive_reopen_and_collapsing_groups(tmp_path: Path) -> None:
    # Defect: arranging a focused canvas overwrites overview positions, or
    # collapsing its group discards the hidden source's user placement.
    data = catalog()
    document = CanvasDocument()
    overview = project(data, document, CanvasScope())
    initial = layout(overview, view_state(document, None), measure(overview))
    pinned = Placement(data.sources[0].id, 1150, 720)
    root = replace(initial.state, placements=(*(p for p in initial.state.placements if p.id != pinned.id), pinned), pinned=frozenset((pinned.id,)))
    document = save_view(document, root)
    focused = CanvasViewState("work:two", (Placement(pinned.id, -120, 84),), frozenset((pinned.id,)))
    document = save_view(document, focused)
    seeded(local_canvas(tmp_path), document)
    restored = local_canvas(tmp_path).read()
    assert view_state(restored, None) == root and view_state(restored, "work:two") == focused
    collapsed = project(data, restored, CanvasScope(mode=CanvasMode.CONTEXTS))
    arranged = layout(collapsed, root, measure(collapsed))
    assert pinned in arranged.state.placements and arranged.state.pinned == root.pinned
    expanded = layout(overview, arranged.state, measure(overview))
    assert pinned in expanded.state.placements
    assert_separated(expanded.state, measure(overview))


def test_measured_nested_containers_separate_content_and_preserve_pins() -> None:
    # Defect: actual card heights overlap, nested frames omit their children,
    # or automatic layout ignores a source moved into another card's space.
    data = catalog()
    extra = source(SourceKind.DOCUMENT)
    data = replace(
        data,
        sources=(*data.sources, extra),
        works=(replace(data.works[0], links=(*data.works[0].links, Association(extra.id, "Evidence"))), data.works[1]),
    )
    group = CanvasCollection("group:project", "Project", ("work:one", "work:two"))
    document = save_collection(CanvasDocument(), group)
    scene = project(data, document, CanvasScope())
    measurements = measure(scene)
    arranged = layout(scene, view_state(document, None), measurements)
    assert len(arranged.frames) == 3
    outer = arranged.frames[0].box
    assert all(
        outer.x <= f.box.x
        and outer.y <= f.box.y
        and outer.x + outer.width >= f.box.x + f.box.width
        and outer.y + outer.height >= f.box.y + f.box.height
        for f in islice(arranged.frames, 1, None)
    )
    assert_separated(arranged.state, measurements)
    first = next(p for p in arranged.state.placements if p.id == data.sources[0].id)
    pinned = Placement(extra.id, first.x, first.y)
    state = replace(arranged.state, placements=(*(p for p in arranged.state.placements if p.id != pinned.id), pinned), pinned=frozenset((pinned.id,)))
    updated = layout(scene, state, measurements)
    assert pinned in updated.state.placements
    assert_separated(updated.state, measurements)
    assert layout(scene, updated.state, measurements) == updated


def test_explicit_grouping_moves_visible_content_and_retains_factual_connections() -> None:
    # Defect: a source moved into a group still renders in its old context, or
    # conflicting persisted parents make navigation depend on collection order.
    data = catalog()
    group = CanvasCollection("group:review", "Review")
    document = collect(save_collection(CanvasDocument(), group), group.id, data.sources[0].id)
    overview = project(data, document, CanvasScope())
    grouped = next(item for item in overview.groups if item.id == group.id)
    assert grouped.items == (data.sources[0],)
    assert all(data.sources[0] not in item.items for item in overview.groups if item.id != group.id)
    focused = project(data, document, CanvasScope((data.works[0].id,)))
    assert data.sources[0] in focused.groups[0].items and scene_contents(overview) == (data.sources[1], data.sources[0])
    with TestCase().assertRaisesRegex(ValueError, "one explicit"):
        save_collection(document, CanvasCollection("group:other", "Other", (data.sources[0].id,)))


def nested_bubbles() -> tuple[Catalog, CanvasDocument]:
    data = catalog()
    conversation = data.sources[0]
    document = source(SourceKind.DOCUMENT)
    pieces = tuple(
        replace(
            source(SourceKind.OUTLOOK, "message:" + str(index)),
            parent_id=conversation.id,
            id=source_id(SourceKind.OUTLOOK, "message:" + str(index), parent_id=conversation.id),
            title="Reply " + str(index),
        )
        for index in range(8)
    )
    data = replace(data, sources=(*data.sources, document, *pieces))
    canvas = nest(CanvasDocument(), pieces[0].id, document.id)
    canvas = nest(canvas, document.id, "note:annotation")
    canvas = save_note(canvas, CanvasNote("note:annotation", "Runbook decision", "Approved with the receiving team"))
    return data, canvas


def test_bubbles_can_contain_documents_messages_and_further_bubbles() -> None:
    # Defect: containment only accepts named groups, makes a duplicate source,
    # drops work references, or allows a cycle through ordinary bubbles.
    data, canvas = nested_bubbles()
    conversation = data.sources[0]
    document = next(item for item in data.sources if item.kind is SourceKind.DOCUMENT)
    first = next(item for item in data.sources if item.parent_id == conversation.id)
    assert context_path("note:annotation", data, canvas) == ("work:one", conversation.id, first.id, document.id, "note:annotation")
    overview = project(data, canvas, CanvasScope())
    assert frozenset(item.id for item in scene_contents(overview)) == frozenset((conversation.id, data.sources[1].id))
    focused = project(data, canvas, CanvasScope(("work:two", conversation.id)))
    assert focused.groups[0].content == conversation and first not in focused.groups[0].items
    first_group = next(group for group in focused.groups[0].children if group.id == first.id)
    assert not first_group.expanded and first_group.content == first
    assert data.works[0].links == catalog().works[0].links
    with TestCase().assertRaisesRegex(ValueError, "cycle"):
        nest(canvas, "note:annotation", first.id)
    # Factual references may point back into their own containment; that is not
    # a containment cycle and must not make arbitrary work nesting impossible.
    nested_work = nest(CanvasDocument(), conversation.id, data.works[0].id)
    assert context_path(data.works[0].id, data, nested_work) == ("work:two", conversation.id, data.works[0].id)
    assert scene_contents(project(data, nested_work, CanvasScope()))

    # Defect exposed by mutations: moving from a pre-existing group erases its
    # peers, or returns without establishing the new bubble parent.
    group = CanvasCollection("group:review", "Review", (conversation.id, data.sources[1].id))
    manual = save_collection(canvas, group)
    grouped = project(data, manual, CanvasScope())
    review = next(item for item in grouped.groups if item.id == group.id)
    assert review.children[0].content == conversation
    assert all(not item.children for item in grouped.groups if item.id != group.id)
    moved = nest(manual, document.id, data.sources[1].id)
    assert moved.collections[0].members == (conversation.id,)
    assert context_path(data.sources[1].id, data, moved)[-2:] == (document.id, data.sources[1].id)
    restored = nest(moved, group.id, data.sources[1].id)
    assert restored.collections[0].members == group.members
    assert next(node for node in restored.nesting if node.parent_id == document.id).members == ("note:annotation",)


def test_per_bubble_expansion_is_complete_scoped_and_preserves_hidden_pins(tmp_path: Path) -> None:
    # Defect: one disclosure opens all siblings, navigating changes its overview
    # setting, hidden pins vanish, or expansion silently hides later messages.
    data, canvas = nested_bubbles()
    conversation = data.sources[0]
    first = next(item for item in data.sources if item.parent_id == conversation.id)
    canvas = toggle_expansion(canvas, None, conversation.id, expanded=True)
    canvas = toggle_expansion(canvas, None, first.id, expanded=True)
    overview = project(data, canvas, CanvasScope())
    group = overview.groups[0].children[0]
    assert group.id == conversation.id and group.expanded
    assert len(group.items) + len(group.children) == 8
    assert all(item.id in frozenset(piece.id for piece in scene_contents(overview)) for item in data.sources if item.parent_id == conversation.id)
    # Every explicitly expanded level retains its contents, regardless of depth.
    first_group = group.children[0]
    assert first_group.expanded and not first_group.children[0].expanded
    document = first_group.children[0]
    canvas = toggle_expansion(canvas, None, document.id, expanded=True)
    assert "note:annotation" in frozenset(item.id for item in scene_contents(project(data, canvas, CanvasScope())))
    focused = project(data, canvas, CanvasScope(("work:two", conversation.id)))
    assert len(scene_contents(focused)) == 9
    pins = Placement(data.sources[-1].id, 900, 200)
    canvas = save_view(canvas, replace(view_state(canvas, None), placements=(pins,), pinned=frozenset((pins.id,))))
    collapsed = toggle_expansion(canvas, None, conversation.id, expanded=False)
    seeded(local_canvas(tmp_path), collapsed)
    reopened = local_canvas(tmp_path).read()
    scene = project(data, reopened, CanvasScope())
    arranged = layout(scene, view_state(reopened, None), measure(scene))
    assert pins in arranged.state.placements and pins.id in arranged.state.pinned
    assert first.id in view_state(reopened, None).expanded
    assert conversation.id not in view_state(reopened, "work:two").collapsed


def test_relationships_project_collapsed_endpoints_without_losing_edit_identity(tmp_path: Path) -> None:
    # Defect: collapse deletes a user relationship or edits its representative
    # instead of the original bubble pair; containment must remain unchanged.
    data = catalog()
    relation = CanvasRelation(data.sources[0].id, data.sources[1].id, "Supports the outcome")
    document = CanvasDocument(relations=(relation,), collapsed=frozenset(work.id for work in data.works))
    store = local_canvas(tmp_path)
    seeded(store, document)
    scene = project(data, store.read(), CanvasScope())
    assert RelationConnection(data.works[0].id, data.works[1].id, relation) in connections(data, scene, store.read().relations)
    assert not document.nesting
    expanded = project(data, document, CanvasScope((data.works[1].id,)))
    assert RelationConnection(relation.start, relation.end, relation) in connections(data, expanded, document.relations)


def test_moving_inferred_evidence_to_overview_preserves_its_factual_link() -> None:
    # Defect: removing explicit nesting reassigns the evidence to its inferred
    # work or Inbox, making an intentional overview placement impossible.
    data = catalog()
    document = nest(CanvasDocument(), None, data.sources[0].id)
    overview = project(data, document, CanvasScope())
    assert data.sources[0] in overview.items
    assert context_path(data.sources[0].id, data, document) == (data.sources[0].id,)
    assert data.works[0].links[0].source_id == data.sources[0].id
