"""Containment is independent of work references; every bubble can be a canvas.

A canonical piece has one visible copy per view. Navigation retains the route
through the work being viewed, including when another work shares that piece.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from enum import Enum
from functools import lru_cache
from itertools import chain, groupby

from assistant.canvas_activity import CanvasAction, CanvasActivity, CanvasQuestion, CanvasUpdate
from assistant.work_canvas_model import (
    CanvasCollection,
    CanvasContent,
    CanvasDocument,
    CanvasNest,
    CanvasNote,
    contents,
    hidden_ids,
    title,
    view_state,
)
from automation.personal_work import Catalog, WorkThread, source_context


@dataclass(frozen=True, slots=True)
class CanvasInbox:
    members: tuple[str, ...]
    id: str = "inbox:unconnected"


type CanvasContainer = WorkThread | CanvasCollection | CanvasInbox | CanvasContent


class CanvasMode(Enum):
    CONTENTS = "contents"
    CONTEXTS = "contexts"


@dataclass(frozen=True, slots=True)
class CanvasScope:
    path: tuple[str, ...] = ()
    mode: CanvasMode = CanvasMode.CONTENTS

    @property
    def identity(self) -> str | None:
        return self.path[-1] if self.path else None


@dataclass(frozen=True, slots=True)
class ContextGroup:
    container: CanvasContainer
    items: tuple[CanvasContent, ...]
    children: tuple[ContextGroup, ...] = ()
    expanded: bool = field(default=True, kw_only=True)

    @property
    def id(self) -> str:
        return self.container.id

    @property
    def title(self) -> str:
        return container_title(self.container)

    @property
    def content(self) -> CanvasContent | None:
        match self.container:
            case WorkThread() | CanvasCollection() | CanvasInbox():
                return None
            case _ as content:
                return content

    @property
    def pieces(self) -> tuple[CanvasContent, ...]:
        """All direct content, including a source bubble's own contribution."""
        content = self.content
        return self.items if content is None else (content, *self.items)


@dataclass(frozen=True, slots=True)
class CanvasScene:
    scope: CanvasScope
    groups: tuple[ContextGroup, ...]
    items: tuple[CanvasContent, ...]


def container_title(container: CanvasContainer) -> str:
    match container:
        case WorkThread(definition=definition):
            return definition.title
        case CanvasCollection(title=value):
            return value
        case CanvasInbox():
            return "Unconnected references"
        case _ as content:
            return title(content)


def containers(catalog: Catalog, document: CanvasDocument) -> tuple[CanvasContainer, ...]:
    hidden = hidden_ids(catalog, document)
    inbox = inbox_members(catalog, document)
    return (
        *catalog.works,
        *(group for group in document.collections if group.id not in hidden),
        *(
            (CanvasInbox(inbox),)
            if inbox
            or any(group.parent_id == "inbox:unconnected" for group in document.collections)
            or any(node.parent_id == "inbox:unconnected" or "inbox:unconnected" in node.members for node in document.nesting)
            else ()
        ),
        *contents(catalog, document),
    )


def saved_parents(catalog: Catalog, document: CanvasDocument) -> frozendict[str, str | None]:
    # User-directed runs can belong to any bubble, including an instruction
    # at the root. Their results and questions stay in that same context.
    active = frozenset(item.id for item in (*catalog.works, *document.collections, *contents(catalog, document)))
    return frozendict(
        (
            *(
                (item.id, identity)
                for item in document.activity
                for identity in tuple(identity for identity in item.work_ids if identity in active)[:1]
            ),
            *((source.id, source.parent_id) for source in catalog.sources if source.parent_id is not None),
            *((note.id, note.context_id) for note in document.notes if note.context_id is not None),
            *((group.id, group.parent_id) for group in document.collections if group.parent_id is not None),
            *((member, group.id) for group in document.collections for member in group.members),
            *((member, node.parent_id) for node in document.nesting for member in node.members),
        )
    )


def inbox_members(catalog: Catalog, document: CanvasDocument) -> tuple[str, ...]:
    parents = saved_parents(catalog, document)
    known = frozenset(item.id for item in (*catalog.works, *document.collections, *contents(catalog, document))) | {"inbox:unconnected"}
    linked = source_context(catalog.sources, frozenset(link.source_id for work in catalog.works for link in work.links))
    return tuple(
        item.id
        for item in catalog.sources
        if not (item.id in parents and parents[item.id] is None)
        and (item.id not in parents or parents[item.id] not in known or parents[item.id] == "inbox:unconnected")
        and item.id not in linked
    )


def explicit_parents(catalog: Catalog, document: CanvasDocument) -> frozendict[str, str | None]:
    return frozendict(
        (*saved_parents(catalog, document).items(), *((identity, "inbox:unconnected") for identity in inbox_members(catalog, document)))
    )


def context_paths(catalog: Catalog, document: CanvasDocument) -> frozendict[str, tuple[str, ...]]:
    known = frozenset(item.id for item in containers(catalog, document))
    parents = explicit_parents(catalog, document)

    def ancestry(start: str) -> tuple[str, ...]:
        path: tuple[str, ...] = ()
        current: str | None = start
        while current is not None and current in known:
            if current in path:
                raise ValueError("Canvas containment cannot form a cycle.")
            path = tuple(chain((current,), path))
            current = parents.get(current)
        return path

    explicit = frozendict((identity, ancestry(identity)) for identity in known)
    contexts = frozendict((work.id, source_context(catalog.sources, frozenset(link.source_id for link in work.links))) for work in catalog.works)
    linked = frozendict((source.id, tuple(work.id for work in catalog.works if source.id in contexts[work.id])) for source in catalog.sources)

    def routed(identity: str) -> tuple[str, ...]:
        path = explicit[identity]
        if path[0] in contexts or (path[0] in parents and parents[path[0]] is None):
            return path
        work = next((work for source_id in path for work in linked.get(source_id, ()) if not frozenset(explicit[work]) & frozenset(path)), None)
        return (*explicit[work], *path) if work is not None else path

    return frozendict((identity, routed(identity)) for identity in known)


def context_path(identity: str, catalog: Catalog, document: CanvasDocument) -> tuple[str, ...]:
    return topology(catalog, document).paths.get(identity, ())


def context_items(container: CanvasContainer, catalog: Catalog, document: CanvasDocument) -> tuple[CanvasContent, ...]:
    return topology(catalog, document).memberships.get(container.id, ())


def indexed_memberships(
    known: tuple[CanvasContainer, ...], pieces: tuple[CanvasContent, ...], parents: frozendict[str, str | None]
) -> frozendict[str, tuple[CanvasContent, ...]]:
    by_id = frozendict((piece.id, piece) for piece in pieces)
    order = frozendict((piece.id, index) for index, piece in enumerate(pieces))

    def entries() -> Iterator[tuple[str, CanvasContent]]:
        for item in pieces:
            if item.id in parents:
                parent = parents[item.id]
                if parent is not None:
                    yield parent, item
            else:
                match item:
                    case CanvasQuestion(work_ids=ids) | CanvasUpdate(work_ids=ids) | CanvasAction(work_ids=ids):
                        yield from ((identity, item) for identity in ids)
                    case _:
                        pass
        for container in known:
            match container:
                case WorkThread(links=links):
                    members = tuple(link.source_id for link in links)
                case CanvasCollection(members=members) | CanvasInbox(members=members):
                    pass
                case _:
                    continue
            for identity in members:
                linked_piece = by_id.get(identity)
                if linked_piece is not None and not (identity in parents and parents[identity] is None):
                    yield container.id, linked_piece

    def ordered(entry: tuple[str, CanvasContent]) -> tuple[str, int]:
        return entry[0], order[entry[1].id]

    def owner(entry: tuple[str, CanvasContent]) -> str:
        return entry[0]

    grouped = frozendict(
        (identity, tuple(frozendict((item.id, item) for _, item in group).values()))
        for identity, group in groupby(sorted(entries(), key=ordered), key=owner)
    )
    return frozendict((container.id, grouped.get(container.id, ())) for container in known)


def descendants(group: ContextGroup) -> Iterator[ContextGroup]:
    yield group
    for child in group.children:
        yield from descendants(child)


def visible_groups(group: ContextGroup) -> Iterator[ContextGroup]:
    yield group
    if group.expanded:
        for child in group.children:
            yield from visible_groups(child)


def group_contents(group: ContextGroup) -> Iterator[CanvasContent]:
    if group.content is not None:
        yield group.content
    if group.expanded:
        yield from group.items
        for child in group.children:
            yield from group_contents(child)


@dataclass(frozen=True, slots=True)
class CanvasStructure:
    """Topology changes independently of cameras, pins and recorded run cursors."""

    notes: tuple[CanvasNote, ...]
    activity: tuple[CanvasActivity, ...]
    collections: tuple[CanvasCollection, ...]
    nesting: tuple[CanvasNest, ...]


@dataclass(frozen=True, slots=True)
class CanvasTopology:
    containers: tuple[CanvasContainer, ...]
    pieces: tuple[CanvasContent, ...]
    parents: frozendict[str, str | None]
    paths: frozendict[str, tuple[str, ...]]
    memberships: frozendict[str, tuple[CanvasContent, ...]]
    children: frozendict[str, tuple[CanvasContainer, ...]]
    by_id: frozendict[str, CanvasContainer]


def topology(catalog: Catalog, document: CanvasDocument) -> CanvasTopology:
    return indexed_topology(catalog, CanvasStructure(document.notes, document.activity, document.collections, document.nesting))


@lru_cache(maxsize=8)
def indexed_topology(catalog: Catalog, structure: CanvasStructure) -> CanvasTopology:
    # functools owns this bounded cache of immutable observations. Repeated
    # navigation/placement must not rebuild membership and ancestry scans;
    # scene geometry and all Qt objects stay outside the cache.
    document = CanvasDocument(notes=structure.notes, activity=structure.activity, collections=structure.collections, nesting=structure.nesting)
    known, pieces = containers(catalog, document), contents(catalog, document)
    parents, paths = explicit_parents(catalog, document), context_paths(catalog, document)
    memberships = indexed_memberships(known, pieces, parents)

    def owner(entry: tuple[str, CanvasContainer]) -> str:
        return entry[0]

    grouped = frozendict(
        (identity, tuple(child for _, child in group))
        for identity, group in groupby(sorted(((paths[item.id][-2], item) for item in known if len(paths[item.id]) > 1), key=owner), key=owner)
    )
    children = frozendict((item.id, grouped.get(item.id, ())) for item in known)
    return CanvasTopology(known, pieces, parents, paths, memberships, children, frozendict((item.id, item) for item in known))


def framed(container: CanvasContainer) -> bool:
    match container:
        case WorkThread() | CanvasCollection() | CanvasInbox():
            return True
        case _:
            return False


def project(catalog: Catalog, document: CanvasDocument, scope: CanvasScope) -> CanvasScene:
    indexed = topology(catalog, document)
    known, paths, parents, memberships = indexed.containers, indexed.paths, indexed.parents, indexed.memberships
    state = view_state(document, scope.identity)

    def build(container: CanvasContainer, trail: tuple[str, ...] = ()) -> ContextGroup:
        related = memberships[container.id]
        candidates = indexed.children[container.id]
        # A focused work must reveal shared references even when their overview
        # parent is elsewhere. Only pieces with contents need a frame.
        candidates = (*candidates, *(item for item in related if item not in candidates and memberships[item.id]))
        children = tuple(
            build(item, (*trail, container.id))
            for item in candidates
            if item.id not in (*trail, container.id)
            and (framed(item) or memberships[item.id] or any(group.parent_id == item.id for group in document.collections))
        )
        nested = frozenset(item.id for child in children for group in descendants(child) for item in group.pieces)
        items = tuple(item for item in related if item.id not in nested and item.id not in (*trail, container.id))
        match container:
            case WorkThread() | CanvasCollection():
                named = True
            case _:
                named = False
        expanded = scope.mode is CanvasMode.CONTENTS and container.id not in state.collapsed and (named or container.id in state.expanded)
        return ContextGroup(container, items, children, expanded=expanded)

    focused = indexed.by_id.get(scope.identity) if scope.identity is not None else None
    if focused is None:
        scope = replace(scope, path=())
        groups = tuple(build(item) for item in known if len(paths[item.id]) == 1 and (framed(item) or memberships[item.id]))
        direct = indexed.pieces
    else:
        current = build(focused)
        groups = (replace(current, expanded=True),)
        direct = ()

    context_ids = frozenset(group.id for root in groups for group in descendants(root))

    def belongs(identity: str, owner: str, assigned: frozenset[str]) -> bool:
        parent = parents.get(identity, owner)
        return identity not in assigned and (parent == owner or parent not in context_ids)

    def unique(group: ContextGroup, assigned: frozenset[str]) -> tuple[ContextGroup, frozenset[str]]:
        own = group.content
        if own is not None:
            assigned = assigned | {own.id}
        items = tuple(item for item in group.items if belongs(item.id, group.id, assigned))
        assigned = assigned | frozenset(item.id for item in items)
        children: tuple[ContextGroup, ...] = ()
        for child in group.children:
            if child.content is not None and not belongs(child.id, group.id, assigned):
                continue
            revised, assigned = unique(child, assigned)
            children = (*children, revised)
        return replace(group, items=items, children=children), assigned

    assigned: frozenset[str] = frozenset()
    visible: tuple[ContextGroup, ...] = ()
    for group in groups:
        if group.content is not None and group.id in assigned:
            continue
        revised, assigned = unique(group, assigned)
        visible = (*visible, revised)
    return CanvasScene(scope, visible, tuple(item for item in direct if item.id not in assigned))


def scene_contents(scene: CanvasScene) -> tuple[CanvasContent, ...]:
    return (*tuple(item for group in scene.groups for item in group_contents(group)), *scene.items)
