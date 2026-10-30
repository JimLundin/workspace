"""Project factual work references onto visible bubbles, including collapsed ones."""

from collections.abc import Iterator
from dataclasses import dataclass

from assistant.work_canvas_context import CanvasScene, ContextGroup, descendants
from assistant.work_canvas_model import CanvasRelation
from automation.personal_work import Catalog


@dataclass(frozen=True, slots=True)
class CanvasConnection:
    start: str
    end: str
    reason: str


@dataclass(frozen=True, slots=True)
class RelationConnection:
    start: str
    end: str
    relation: CanvasRelation

    @property
    def reason(self) -> str:
        return self.relation.reason


type CanvasLink = CanvasConnection | RelationConnection


def representatives(scene: CanvasScene) -> frozendict[str, str]:
    def entries(group: ContextGroup) -> Iterator[tuple[str, str]]:
        if not group.expanded:
            for child in descendants(group):
                yield child.id, group.id
                yield from ((item.id, group.id) for item in child.pieces)
            return
        yield group.id, group.id
        yield from ((item.id, item.id) for item in group.items)
        for child in group.children:
            yield from entries(child)

    return frozendict((*(entry for root in scene.groups for entry in entries(root)), *((item.id, item.id) for item in scene.items)))


def connections(catalog: Catalog, scene: CanvasScene, relations: tuple[CanvasRelation, ...] = ()) -> tuple[CanvasLink, ...]:
    visible = representatives(scene)
    # Containment already expresses references within the same work. Lines earn
    # their space when shared evidence belongs to a different visible context.
    contained = frozendict(
        (group.id, frozenset(item.id for child in descendants(group) for item in child.pieces))
        for root in scene.groups
        for group in descendants(root)
    )
    result: tuple[CanvasLink, ...] = ()
    for work in catalog.works:
        start = visible.get(work.id)
        if start is None:
            continue
        for link in work.links:
            end = visible.get(link.source_id)
            if end is None or end == start or link.source_id in contained.get(work.id, frozenset()):
                continue
            result = (*result, CanvasConnection(start, end, link.reason))
    for relation in relations:
        start, end = visible.get(relation.start), visible.get(relation.end)
        if start is not None and end is not None and start != end:
            result = (*result, RelationConnection(start, end, relation))
    return result
