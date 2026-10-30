"""Atomic agent edits of the local canvas; Qt retains all persistence ownership.

The token covers editable structure and user pins. Routine activity captures and
automatic layout positions do not invalidate a structural edit. Commands apply
to the latest document, preserving those independent observations.
"""

import hashlib
from dataclasses import dataclass, field, replace
from typing import Annotated, Literal, assert_never

from pydantic import Field, TypeAdapter

from assistant.work_canvas_context import topology
from assistant.work_canvas_model import (
    DOCUMENT,
    CanvasCollection,
    CanvasDocument,
    CanvasNote,
    CanvasRelation,
    Placement,
    nest,
    release_subtree,
    save_collection,
    save_note,
    save_view,
    toggle_expansion,
    view_state,
)
from automation.personal_work import Catalog, Identity, Title


@dataclass(frozen=True, slots=True)
class PutNote:
    note: CanvasNote
    kind: Literal["note"] = "note"


@dataclass(frozen=True, slots=True)
class PutGroup:
    id: Identity
    title: Title
    parent_id: Identity | None = None
    kind: Literal["group"] = "group"


@dataclass(frozen=True, slots=True)
class MoveBubble:
    id: Identity
    parent_id: Identity | None
    kind: Literal["move"] = "move"


@dataclass(frozen=True, slots=True)
class ExpandBubble:
    id: Identity
    scope_id: Identity | None = None
    expanded: bool = field(default=False, kw_only=True)
    kind: Literal["expand"] = "expand"


@dataclass(frozen=True, slots=True)
class ArrangeCanvas:
    scope_id: Identity | None = None
    placements: Annotated[tuple[Placement, ...], Field(max_length=200)] = ()
    kind: Literal["arrange"] = "arrange"


@dataclass(frozen=True, slots=True)
class PutRelation:
    relation: CanvasRelation
    kind: Literal["link"] = "link"


@dataclass(frozen=True, slots=True)
class RemoveRelation:
    start: Identity
    end: Identity
    kind: Literal["unlink"] = "unlink"


type CanvasEdit = Annotated[
    PutNote | PutGroup | MoveBubble | ExpandBubble | ArrangeCanvas | PutRelation | RemoveRelation, Field(discriminator="kind")
]


@dataclass(frozen=True, slots=True)
class ReadCanvas:
    offset: Annotated[int, Field(strict=True, ge=0)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 20
    operation: Literal["work_canvas_read"] = "work_canvas_read"


@dataclass(frozen=True, slots=True)
class UpdateCanvas:
    expected_revision: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    edits: Annotated[tuple[CanvasEdit, ...], Field(min_length=1, max_length=40)]
    operation: Literal["work_canvas_update"] = "work_canvas_update"


type CanvasCommand = Annotated[ReadCanvas | UpdateCanvas, Field(discriminator="operation")]


@dataclass(frozen=True, slots=True)
class CanvasSnapshot:
    revision: str
    document: CanvasDocument
    work_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    total_pieces: int
    next_offset: int | None
    kind: Literal["canvas"] = "canvas"


@dataclass(frozen=True, slots=True)
class CanvasUpdated:
    previous_revision: str
    revision: str
    changed: bool = field(kw_only=True)
    kind: Literal["canvas_updated"] = "canvas_updated"


@dataclass(frozen=True, slots=True)
class CanvasRefused:
    error: str
    kind: Literal["canvas_refused"] = "canvas_refused"


type CanvasResponse = Annotated[CanvasSnapshot | CanvasUpdated | CanvasRefused, Field(discriminator="kind")]
CANVAS_COMMAND = TypeAdapter(CanvasCommand)
CANVAS_RESPONSE = TypeAdapter(CanvasResponse)


def snapshot(document: CanvasDocument, catalog: Catalog, request: ReadCanvas) -> CanvasSnapshot:
    pieces = (*document.notes, *document.activity)
    count = min(request.limit, max(0, len(pieces) - request.offset))
    while True:
        offered = frozenset(piece.id for piece in pieces[request.offset : request.offset + count])
        result = CanvasSnapshot(
            revision(document),
            replace(
                document,
                notes=tuple(note for note in document.notes if note.id in offered),
                activity=tuple(item for item in document.activity if item.id in offered),
                runs=(),
            ),
            tuple(work.id for work in catalog.works),
            tuple(source.id for source in catalog.sources),
            len(pieces),
            request.offset + count if request.offset + count < len(pieces) else None,
        )
        if len(CANVAS_RESPONSE.dump_json(result)) <= 500000:
            return result
        if count == 0:
            raise ValueError("Canvas structure exceeds the bounded bridge response. Narrow its saved topology.")
        count -= 1


def revision(document: CanvasDocument) -> str:
    def pinned(state: tuple[Placement, ...], ids: frozenset[str]) -> tuple[Placement, ...]:
        return tuple(p for p in state if p.id in ids)

    structure = replace(
        document,
        activity=(),
        runs=(),
        placements=pinned(document.placements, document.pinned),
        views=tuple(
            replace(view, placements=pinned(view.placements, view.pinned))
            for view in document.views
            if view.pinned or view.expanded or view.collapsed
        ),
    )
    return hashlib.sha256(DOCUMENT.dump_json(structure)).hexdigest()


def identities(catalog: Catalog, document: CanvasDocument) -> frozenset[str]:
    return frozenset(item.id for item in (*catalog.works, *catalog.sources, *document.notes, *document.collections, *document.activity)) | {
        "inbox:unconnected"
    }


def require(identity: str | None, known: frozenset[str]) -> None:
    if identity is not None and identity not in known:
        raise ValueError("Unknown canvas identity: " + identity)


def detached(document: CanvasDocument, identity: str) -> CanvasDocument:
    return replace(
        document,
        collections=tuple(
            replace(group, parent_id=None) if group.id == identity else replace(group, members=tuple(i for i in group.members if i != identity))
            for group in document.collections
        ),
        notes=tuple(replace(note, context_id=None) if note.id == identity else note for note in document.notes),
        nesting=tuple(replace(node, members=tuple(i for i in node.members if i != identity)) for node in document.nesting),
    )


def edited(document: CanvasDocument, command: UpdateCanvas, catalog: Catalog) -> CanvasDocument:
    if command.expected_revision != revision(document):
        raise ValueError("The canvas changed. Read work_canvas_read again before editing.")
    current = document
    for edit in command.edits:
        known = identities(catalog, current)

        match edit:
            case PutNote(note):
                require(note.context_id, known)
                if note.context_id is not None:
                    current = detached(current, note.id)
                current = save_note(current, note)
            case PutGroup(id=identity, title=title, parent_id=parent):
                require(parent, known)
                existing = next((group for group in current.collections if group.id == identity), CanvasCollection(identity, title))
                current = save_collection(current, replace(existing, title=title, parent_id=parent))
            case MoveBubble(id=identity, parent_id=parent):
                require(identity, known)
                require(parent, known)
                members = frozenset(item for item, path in topology(catalog, current).paths.items() if identity in path) | {identity}
                current = detached(current, identity)
                current = release_subtree(nest(current, parent, identity), members)
            case PutRelation(relation=relation):
                require(relation.start, known)
                require(relation.end, known)
                current = replace(
                    current, relations=(*(item for item in current.relations if (item.start, item.end) != (relation.start, relation.end)), relation)
                )
            case RemoveRelation(start=start, end=end):
                current = replace(current, relations=tuple(item for item in current.relations if (item.start, item.end) != (start, end)))
            case ExpandBubble(id=identity, scope_id=scope, expanded=expanded):
                require(identity, known)
                require(scope, known)
                current = toggle_expansion(current, scope, identity, expanded=expanded)
            case ArrangeCanvas(scope_id=scope, placements=placements):
                require(scope, known)
                for placement in placements:
                    require(placement.id, known)
                state = view_state(current, scope)
                # Empty placements restores the shared measured layout. Explicit
                # positions are a deliberate replacement of this scope's pins.
                current = save_view(current, replace(state, placements=placements, pinned=frozenset(p.id for p in placements)))
            case _:
                assert_never(edit)
    return DOCUMENT.validate_python(current)
