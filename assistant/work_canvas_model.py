"""Local canvas arrangement, independent of work content and agent revisions."""

from dataclasses import dataclass, replace
from typing import Annotated, assert_never

from pydantic import Field, StringConstraints, TypeAdapter

from assistant.canvas_activity import (
    ROOT_CONTEXT,
    CanvasAction,
    CanvasActivity,
    CanvasInstruction,
    CanvasQuestion,
    CanvasRun,
    CanvasUpdate,
    merge_activity,
)
from automation.personal_work import Catalog, Detail, Identity, SourceKind, Title, WorkSource, source_context

type Coordinate = Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)]


@dataclass(frozen=True, slots=True)
class Placement:
    id: Identity
    x: Coordinate
    y: Coordinate


@dataclass(frozen=True, slots=True)
class CanvasNote:
    id: Identity
    title: Title
    text: Detail = ""
    context_id: Identity | None = None


@dataclass(frozen=True, slots=True)
class CanvasCollection:
    id: Identity
    title: Title
    members: tuple[Identity, ...] = ()
    parent_id: Identity | None = None

    def __post_init__(self) -> None:
        if not self.id.startswith("group:") or self.id == self.parent_id or self.id in self.members:
            raise ValueError("A canvas group cannot contain itself.")
        if len(frozenset(self.members)) != len(self.members):
            raise ValueError("Group members must have distinct identities.")


@dataclass(frozen=True, slots=True)
class CanvasNest:
    # None is deliberate placement on the overview, overriding inferred
    # containment while preserving the source's factual work connections.
    parent_id: Identity | None
    members: tuple[Identity, ...] = ()


@dataclass(frozen=True, slots=True)
class CanvasRelation:
    start: Identity
    end: Identity
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)] = "Related"

    def __post_init__(self) -> None:
        if self.start == self.end:
            raise ValueError("A relationship needs two different bubbles.")


@dataclass(frozen=True, slots=True)
class CanvasViewState:
    context_id: Identity | None
    placements: tuple[Placement, ...] = ()
    pinned: frozenset[Identity] = frozenset()
    expanded: frozenset[Identity] = frozenset()
    collapsed: frozenset[Identity] = frozenset()

    def __post_init__(self) -> None:
        if len(frozenset(p.id for p in self.placements)) != len(self.placements):
            raise ValueError("Canvas placements must have distinct identities.")


@dataclass(frozen=True, slots=True)
class CanvasDocument:
    placements: tuple[Placement, ...] = ()
    notes: tuple[CanvasNote, ...] = ()
    activity: tuple[CanvasActivity, ...] = ()
    pinned: frozenset[str] = frozenset()
    runs: tuple[CanvasRun, ...] = ()
    collections: tuple[CanvasCollection, ...] = ()
    views: tuple[CanvasViewState, ...] = ()
    nesting: tuple[CanvasNest, ...] = ()
    expanded: frozenset[Identity] = frozenset()
    collapsed: frozenset[Identity] = frozenset()
    relations: Annotated[tuple[CanvasRelation, ...], Field(max_length=1000)] = ()

    def __post_init__(self) -> None:
        if len(frozenset(item.id for item in self.placements)) != len(self.placements):
            raise ValueError("Canvas placements must have distinct identities.")
        if len(frozenset(item.id for item in self.notes)) != len(self.notes) or any(not item.id.startswith("note:") for item in self.notes):
            raise ValueError("Canvas notes must have distinct note identities.")
        if len(frozenset(item.id for item in self.activity)) != len(self.activity):
            raise ValueError("Canvas activity must have distinct identities.")
        if len(frozenset(item.id for item in self.collections)) != len(self.collections):
            raise ValueError("Canvas groups must have distinct identities.")
        memberships = tuple(member for group in self.collections for member in group.members) + tuple(
            member for node in self.nesting for member in node.members
        )
        if len(frozenset(memberships)) != len(memberships):
            raise ValueError("A piece can have only one explicit canvas group.")
        if len(frozenset(item.context_id for item in self.views)) != len(self.views) or any(item.context_id is None for item in self.views):
            raise ValueError("Focused canvas arrangements must have distinct contexts.")
        if len(frozenset(node.parent_id for node in self.nesting)) != len(self.nesting):
            raise ValueError("Bubble contents need distinct parents.")
        if len(frozenset((relation.start, relation.end) for relation in self.relations)) != len(self.relations):
            raise ValueError("A relationship needs distinct endpoints.")
        parents = frozendict(
            (
                *((note.id, note.context_id) for note in self.notes if note.context_id is not None),
                *((member, node.parent_id) for node in self.nesting for member in node.members),
                *((group.id, group.parent_id) for group in self.collections),
                *((member, group.id) for group in self.collections for member in group.members),
            )
        )
        for identity in parents:
            path: frozenset[str] = frozenset()
            current: str | None = identity
            while current is not None:
                if current in path:
                    raise ValueError("Canvas groups cannot form a cycle.")
                path = path | {current}
                current = parents.get(current)


type CanvasContent = WorkSource | CanvasNote | CanvasActivity

DOCUMENT = TypeAdapter(CanvasDocument)
NOTE = TypeAdapter(CanvasNote)
COLLECTION = TypeAdapter(CanvasCollection)
VIEW_STATE = TypeAdapter(CanvasViewState)


def contents(catalog: Catalog, document: CanvasDocument) -> tuple[CanvasContent, ...]:
    hidden = hidden_ids(catalog, document)
    return tuple(item for item in (*catalog.sources, *document.activity, *document.notes) if item.id not in hidden)


def hidden_ids(catalog: Catalog, document: CanvasDocument) -> frozenset[str]:
    shared = source_context(catalog.sources, frozenset(link.source_id for work in catalog.works for link in work.links))
    # An active email/message keeps its conversation context, and a linked
    # conversation keeps its observed pieces. Dismissal hides only exclusive context.
    hidden = frozenset(item.work.id for item in catalog.dismissed)
    hidden |= frozenset(link.source_id for item in catalog.dismissed for link in item.work.links if link.source_id not in shared)
    parents = frozendict(
        (
            *((source.id, source.parent_id) for source in catalog.sources if source.parent_id is not None),
            *((note.id, note.context_id) for note in document.notes if note.context_id is not None),
            *((group.id, group.parent_id) for group in document.collections if group.parent_id is not None),
            *((member, group.id) for group in document.collections for member in group.members),
            *((member, node.parent_id) for node in document.nesting for member in node.members),
        )
    )
    while True:
        revised = hidden | frozenset(identity for identity, parent in parents.items() if parent in hidden and identity not in shared)
        revised |= frozenset(item.id for item in document.activity if item.work_ids and all(identity in hidden for identity in item.work_ids))
        if revised == hidden:
            return hidden
        hidden = revised


def view_state(document: CanvasDocument, context_id: str | None) -> CanvasViewState:
    if context_id is None:
        return CanvasViewState(None, document.placements, document.pinned, document.expanded, document.collapsed)
    return next((item for item in document.views if item.context_id == context_id), CanvasViewState(context_id))


def save_view(document: CanvasDocument, state: CanvasViewState) -> CanvasDocument:
    checked = VIEW_STATE.validate_python(state)
    if checked.context_id is None:
        return replace(document, placements=checked.placements, pinned=checked.pinned, expanded=checked.expanded, collapsed=checked.collapsed)
    return replace(document, views=(*(item for item in document.views if item.context_id != checked.context_id), checked))


def save_collection(document: CanvasDocument, collection: CanvasCollection) -> CanvasDocument:
    checked = COLLECTION.validate_python(collection)
    return replace(document, collections=(*(item for item in document.collections if item.id != checked.id), checked))


def collect(document: CanvasDocument, group_id: str, identity: str) -> CanvasDocument:
    groups = document.collections
    target = next((group for group in groups if group.id == group_id), None)
    if target is None:
        raise ValueError("The target group is unavailable.")
    nested = next((group for group in groups if group.id == identity), None)
    if nested is not None:
        return save_collection(document, replace(nested, parent_id=target.id))
    # Contexts have one navigation parent. Shared source relationships stay in
    # the catalog; moving their visual grouping never removes those links.
    revised = replace(
        document, collections=tuple(replace(group, members=tuple(item for item in group.members if item != identity)) for group in groups)
    )
    return save_collection(revised, replace(target, members=(*tuple(item for item in target.members if item != identity), identity)))


def save_note(document: CanvasDocument, note: CanvasNote) -> CanvasDocument:
    checked = NOTE.validate_python(note)
    return replace(document, notes=(*(item for item in document.notes if item.id != checked.id), checked))


def caption(content: CanvasContent) -> str:
    match content:
        case WorkSource(kind=kind, parent_id=parent):
            return source_caption(kind, parent)
        case CanvasNote():
            return "Note"
        case CanvasUpdate():
            return "Research result"
        case CanvasQuestion():
            return "Your input is needed"
        case CanvasAction(state=state):
            return state.value
        case _ as unreachable:
            assert_never(unreachable)


def source_caption(kind: SourceKind, parent: str | None) -> str:
    match kind:
        case SourceKind.TEAMS:
            return "Teams conversation" if parent is None else "Teams message"
        case SourceKind.OUTLOOK:
            return "Outlook conversation" if parent is None else "Outlook email"
        case SourceKind.KANBAN:
            return "Kanban ticket"
        case SourceKind.DOCUMENT:
            return "Document"
        case SourceKind.WEB_PAGE:
            return "Web reference"
        case _ as unreachable:
            assert_never(unreachable)


def title(content: CanvasContent) -> str:
    match content:
        case WorkSource(title=value) | CanvasNote(title=value) | CanvasUpdate(title=value) | CanvasQuestion(title=value) | CanvasAction(title=value):
            return value


def summary(content: CanvasContent) -> str:
    match content:
        case WorkSource(excerpt=value) | CanvasNote(text=value) | CanvasUpdate(text=value) | CanvasQuestion(text=value) | CanvasAction(text=value):
            return value


def observe_activity(document: CanvasDocument, updates: tuple[CanvasActivity, ...]) -> CanvasDocument:
    existing = frozendict((item.id, item) for item in document.activity)
    refreshed = frozendict((item.id, merge_activity(existing[item.id], item) if item.id in existing else item) for item in updates)
    activity = (*tuple(refreshed.get(item.id, item) for item in document.activity), *(item for item in refreshed.values() if item.id not in existing))
    return replace(document, activity=activity)


def result_document(document: CanvasDocument) -> CanvasDocument:
    """Remove generated request scaffolding, preserving its substantive children."""
    original_scopes = frozendict((note.id, note.context_id) for note in document.notes if note.id.startswith("note:instruction:"))

    def scope(identity: str | None) -> str | None:
        # CanvasDocument already validates acyclic containment at the boundary.
        while identity is not None and identity in original_scopes:
            identity = original_scopes[identity]
        return identity

    requests = frozendict((identity, scope(parent)) for identity, parent in original_scopes.items())
    reports = frozenset("result:" + run.task_id for run in document.runs if isinstance(run.intent, CanvasInstruction)) & frozenset(
        item.id for item in document.activity
    )
    removed = frozenset(requests) | reports | frozenset(item.id for item in document.activity if isinstance(item, CanvasAction))
    if not removed:
        return document

    for identity, parent in requests.items():
        children = frozenset(note.id for note in document.notes if note.context_id == identity)
        children |= frozenset(group.id for group in document.collections if group.parent_id == identity)
        children |= frozenset(member for node in document.nesting if node.parent_id == identity for member in node.members)
        for child in children - removed:
            document = nest(document, parent, child)

    def state(view: CanvasViewState) -> CanvasViewState:
        return replace(
            view,
            placements=tuple(item for item in view.placements if item.id not in removed),
            pinned=view.pinned - removed,
            expanded=view.expanded - removed,
            collapsed=view.collapsed - removed,
        )

    activity = tuple(
        replace(
            item, work_ids=tuple(requests.get(identity) or identity for identity in item.work_ids if identity not in requests or requests[identity])
        )
        for item in document.activity
        if item.id not in removed
    )
    root = state(view_state(document, None))
    return replace(
        document,
        notes=tuple(replace(note, context_id=scope(note.context_id)) for note in document.notes if note.id not in removed),
        activity=activity,
        runs=tuple(replace(run, work_id=requests.get(run.work_id) or ROOT_CONTEXT) if run.work_id in requests else run for run in document.runs),
        collections=tuple(
            replace(group, parent_id=scope(group.parent_id), members=tuple(member for member in group.members if member not in removed))
            for group in document.collections
        ),
        nesting=tuple(
            replace(node, members=tuple(member for member in node.members if member not in removed))
            for node in document.nesting
            if node.parent_id not in removed
        ),
        views=tuple(state(view) for view in document.views if view.context_id not in removed),
        placements=root.placements,
        pinned=root.pinned,
        expanded=root.expanded,
        collapsed=root.collapsed,
        relations=tuple(relation for relation in document.relations if relation.start not in removed and relation.end not in removed),
    )


def nest(document: CanvasDocument, parent_id: str | None, identity: str) -> CanvasDocument:
    """Move visual containment without touching any factual work connection."""
    if parent_id == identity:
        raise ValueError("A bubble cannot contain itself.")
    groups = tuple(
        replace(group, parent_id=parent_id)
        if group.id == identity
        else replace(group, members=tuple(member for member in group.members if member != identity))
        for group in document.collections
    )
    revised = replace(
        document,
        collections=groups,
        nesting=tuple(replace(node, members=tuple(member for member in node.members if member != identity)) for node in document.nesting),
    )
    if parent_id is not None and any(group.id == identity for group in groups):
        return revised
    if parent_id is not None and any(group.id == parent_id for group in groups):
        return collect(revised, parent_id, identity)
    current = next((node for node in revised.nesting if node.parent_id == parent_id), CanvasNest(parent_id))
    return replace(
        revised,
        nesting=(*tuple(node for node in revised.nesting if node.parent_id != parent_id), replace(current, members=(*current.members, identity))),
    )


def release_subtree(document: CanvasDocument, members: frozenset[str]) -> CanvasDocument:
    """A new container owns layout; stale per-scope pins must not pull it back."""

    def released(state: CanvasViewState) -> CanvasViewState:
        return replace(state, placements=tuple(p for p in state.placements if p.id not in members), pinned=state.pinned - members)

    root = released(view_state(document, None))
    return replace(document, placements=root.placements, pinned=root.pinned, views=tuple(released(state) for state in document.views))


def toggle_expansion(document: CanvasDocument, scope_id: str | None, identity: str, *, expanded: bool) -> CanvasDocument:
    # Scope, bubble identity and requested visibility bind one presentation edit.
    state = view_state(document, scope_id)
    changed = replace(
        state,
        expanded=state.expanded | {identity} if expanded else state.expanded - {identity},
        collapsed=state.collapsed - {identity} if expanded else state.collapsed | {identity},
    )
    return save_view(document, changed)
