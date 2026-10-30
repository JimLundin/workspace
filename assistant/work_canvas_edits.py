"""User edits of the local canvas, applied by its owner to the latest document.

The panel renders documents and sends intents; it never saves its rendered copy.
Each intent names only what the user changed, so an agent update committed since
the panel's last render survives the edit.
"""

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import assert_never

from assistant.work_canvas_commands import PutRelation, RemoveRelation, UpdateCanvas, edited, revision
from assistant.work_canvas_context import CanvasScope, context_path, project
from assistant.work_canvas_gestures import NestBubble, PlaceBubbles
from assistant.work_canvas_model import (
    CanvasCollection,
    CanvasDocument,
    CanvasNote,
    CanvasViewState,
    nest,
    release_subtree,
    save_collection,
    save_note,
    save_view,
    toggle_expansion,
    view_state,
)
from automation.personal_work import Catalog


@dataclass(frozen=True, slots=True)
class ArrangeView:
    """A measured layout of the rendered view; dropped when that view changed since."""

    base: CanvasViewState
    arranged: CanvasViewState


class ReleasePositions(Enum):
    RELEASE = "release"


@dataclass(frozen=True, slots=True)
class Reveal:
    id: str


@dataclass(frozen=True, slots=True)
class SetExpansion:
    id: str
    expanded: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class AddGroup:
    group: CanvasCollection


@dataclass(frozen=True, slots=True)
class RenameGroup:
    id: str
    title: str


@dataclass(frozen=True, slots=True)
class PutInside:
    id: str
    parent_id: str | None
    members: frozenset[str]


@dataclass(frozen=True, slots=True)
class SaveNote:
    note: CanvasNote


type Change = (
    PlaceBubbles
    | NestBubble
    | ArrangeView
    | ReleasePositions
    | Reveal
    | SetExpansion
    | AddGroup
    | RenameGroup
    | PutInside
    | SaveNote
    | PutRelation
    | RemoveRelation
)


@dataclass(frozen=True, slots=True)
class UserEdit:
    """One change the user made while viewing a scope."""

    scope: CanvasScope
    change: Change


def user_edited(document: CanvasDocument, catalog: Catalog, edit: UserEdit) -> CanvasDocument:
    """Apply one user edit to the latest document; an invalid nesting raises ValueError."""
    scope = edit.scope
    match edit.change:
        case PlaceBubbles(id=identity, positions=positions):
            state = view_state(document, scope.identity)
            replacements = frozendict((position.id, position) for position in positions)
            placements = tuple(replacements.get(placement.id, placement) for placement in state.placements)
            return save_view(document, replace(state, placements=placements, pinned=state.pinned | {identity}))
        case NestBubble(id=identity, parent_id=parent, positions=positions, members=members):
            nested = nest(document, parent, identity)
            project(catalog, nested, scope)
            nested = release_subtree(nested, members)
            state = view_state(nested, scope.identity)
            if parent is None:
                state = replace(state, placements=(*state.placements, *positions), pinned=state.pinned | {identity})
            nested = save_view(nested, state)
            if parent is not None and parent != scope.identity:
                nested = toggle_expansion(nested, scope.identity, parent, expanded=True)
            return nested
        case ArrangeView(base=base, arranged=arranged):
            # A changed view gets its own render and measured layout.
            return save_view(document, arranged) if view_state(document, arranged.context_id) == base else document
        case ReleasePositions.RELEASE:
            return save_view(document, CanvasViewState(scope.identity))
        case Reveal(id=identity):
            revealed = document
            for ancestor in context_path(identity, catalog, document):
                revealed = toggle_expansion(revealed, None, ancestor, expanded=True)
            return revealed
        case SetExpansion(id=identity, expanded=expanded):
            return toggle_expansion(document, scope.identity, identity, expanded=expanded)
        case AddGroup(group=group):
            return save_collection(document, group)
        case RenameGroup(id=identity, title=title):
            group = next((group for group in document.collections if group.id == identity), None)
            return save_collection(document, replace(group, title=title)) if group is not None else document
        case PutInside(id=identity, parent_id=parent, members=members):
            nested = release_subtree(nest(document, parent, identity), members | {identity})
            project(catalog, nested, scope)
            return nested
        case SaveNote(note=note):
            return save_note(document, note)
        case PutRelation() | RemoveRelation() as relation:
            return edited(document, UpdateCanvas(revision(document), (relation,)), catalog)
        case _:
            assert_never(edit.change)
