"""Desktop attention follows work identity, independently of canvas placement.

These bounded projections reuse Workspace's existing work/source relationships.
They are presentation policy, not a general graph or scheduling abstraction.
"""

from dataclasses import dataclass

from assistant.canvas_activity import Attention, CanvasQuestion, CanvasRequest, CanvasUpdate
from assistant.work_canvas_model import CanvasDocument, hidden_ids
from automation.personal_work import Catalog


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """A canvas contribution's complete presentation and exact reply route.

    The fields belong together: identity/context preserve card ownership while
    title, text, timestamp and the optional question describe the contribution.
    """

    identity: str
    context: str
    title: str
    text: str
    created_at: float = 0
    question: CanvasQuestion | None = None


@dataclass(frozen=True, slots=True)
class AttentionSnapshot:
    contexts: frozendict[str, str] = frozendict()
    items: tuple[AttentionItem, ...] = ()
    hidden: frozenset[str] = frozenset()


def observed_attention(catalog: Catalog, document: CanvasDocument) -> AttentionSnapshot:
    hidden = hidden_ids(catalog, document)
    works = frozenset(work.id for work in catalog.works)
    # Factual work connections precede visual grouping. A canvas arrangement
    # may move a contribution without creating a second desktop work identity.
    parents = frozendict(
        (
            *((source.id, source.parent_id) for source in catalog.sources if source.parent_id is not None),
            *((member, node.parent_id) for node in document.nesting for member in node.members if node.parent_id is not None),
            *((member, group.id) for group in document.collections for member in group.members),
            *((group.id, group.parent_id) for group in document.collections if group.parent_id is not None),
            *((note.id, note.context_id) for note in document.notes if note.context_id is not None),
            *((item.id, item.work_ids[0]) for item in document.activity if item.work_ids),
            *((run.task_id, run.work_id) for run in document.runs),
            *((link.source_id, work.id) for work in reversed(catalog.works) for link in work.links),
        )
    )

    def context(identity: str) -> str:
        seen: frozenset[str] = frozenset()
        while identity not in works and identity in parents and identity not in seen:
            seen = seen | {identity}
            identity = parents[identity]
        return identity

    identities = (*parents, *works, *(item.id for item in document.activity), *(note.id for note in document.notes))
    contexts = frozendict((identity, context(identity)) for identity in identities)
    items: tuple[AttentionItem, ...] = ()
    for item in document.activity:
        if item.id in hidden:
            continue
        match item:
            case CanvasQuestion():
                items = (*items, AttentionItem(item.id, context(item.id), item.title, item.text, item.created_at, item))
            case CanvasUpdate():
                items = (*items, AttentionItem(item.id, context(item.id), item.title, item.text, item.created_at))
            case _:
                pass
    items = (
        *items,
        *(AttentionItem(note.id, context(note.id), note.title, note.text) for note in document.notes if note.id not in hidden),
        *(
            AttentionItem(
                work.id,
                work.id,
                work.definition.title,
                "\n\n".join(value for value in (work.definition.summary, work.definition.next_step) if value),
                work.updated_at,
            )
            for work in catalog.works
            if work.id not in hidden
        ),
    )
    return AttentionSnapshot(contexts, items, hidden)


def context_of(snapshot: AttentionSnapshot, identity: str) -> str:
    target = identity.removeprefix("canvas:")
    return snapshot.contexts.get(target, target)


def selected_question(snapshot: AttentionSnapshot, request: CanvasRequest | None) -> CanvasQuestion | None:
    return next(
        (
            item.question
            for item in snapshot.items
            if item.question is not None and item.question.request == request and item.question.reply is Attention.WAITING
        ),
        None,
    )
