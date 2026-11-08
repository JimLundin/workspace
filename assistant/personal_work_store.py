"""Desktop-owned transactional persistence for the personal-work catalog."""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import assert_never

from assistant.meeting_store import MeetingStore
from automation import journal
from contracts.personal_work import (
    CATALOG,
    AddDocument,
    AddWebPage,
    Association,
    Catalog,
    CorrelationInput,
    DismissedWork,
    DismissWork,
    DocumentAdded,
    ListSources,
    ListWork,
    MeetingSource,
    PersonalRequest,
    PersonalResponse,
    ReadMeeting,
    RestoreWork,
    SaveWork,
    Source,
    SourceOrigin,
    UnlinkWork,
    WebPageSource,
    WorkPlan,
    WorkSaved,
    find_work,
    observe_sources,
    page,
    reconcile_plan,
    reference_source,
    save_work,
    unlink_work,
)


@dataclass(frozen=True, slots=True)
class PersonalStore:
    """Each call owns one real SQLite transaction; observations are immutable.

    This uses the existing work database, with an independent catalog table and
    revision. Each write transaction protects edits from concurrent model results.
    """

    path: Path

    def __post_init__(self) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with journal.writing(self.path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS personal_work (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)")
            connection.execute("INSERT OR IGNORE INTO personal_work VALUES (1, ?)", (CATALOG.dump_json(Catalog()),))

    def loaded(self, connection: journal.Connection) -> Catalog:
        observed: object = connection.execute("SELECT payload FROM personal_work WHERE id=1").fetchone()
        match observed:
            case (bytes() as payload,):
                return CATALOG.validate_json(payload)
            case _:
                raise ValueError("The personal work catalog is unavailable.")

    def persist(self, connection: journal.Connection, catalog: Catalog) -> None:
        state = CATALOG.validate_json(CATALOG.dump_json(catalog))
        connection.execute("UPDATE personal_work SET payload=? WHERE id=1", (CATALOG.dump_json(state),))

    def read(self) -> Catalog:
        with journal.reading(self.path) as connection:
            return self.loaded(connection)

    def observe(self, sources: tuple[Source, ...]) -> Catalog:
        with journal.writing(self.path) as connection:
            state = observe_sources(self.loaded(connection), sources)
            self.persist(connection, state)
            return state

    def reconcile(self, request: CorrelationInput, plan: WorkPlan, at: float) -> Catalog:
        with journal.writing(self.path) as connection:
            state = self.loaded(connection)
            if state.revision != request.catalog_revision:
                raise ValueError("Work or source evidence changed during this review. A fresh review is needed.")
            # A model can only associate the captured observations, not other
            # stored sources omitted from its bounded input.
            offered = frozenset(source.id for source in request.sources)
            if any(link.source_id not in offered for work in plan.works for link in work.links):
                raise ValueError("The model connected a source outside its review.")
            state = reconcile_plan(state, plan, at)
            self.persist(connection, state)
            return state

    def handle(self, request: PersonalRequest, at: float, *, origin: SourceOrigin = SourceOrigin.AGENT) -> PersonalResponse:
        # Meeting conversation IO owns a separate journal, outside a catalog write transaction.
        if isinstance(request, ReadMeeting):
            source = next((item for item in self.read().sources if item.id == request.source_id), None)
            match source:
                case MeetingSource(meeting=meeting):
                    conversation = MeetingStore(Path(meeting.transcript_path).parent).conversation(request.offset, request.limit)
                    if conversation.meeting.identity != meeting.identity:
                        raise ValueError("This journal no longer matches the recorded meeting identity.")
                    return conversation
                case _:
                    raise ValueError("Read a native meeting source identity from work_items_sources first.")
        with journal.writing(self.path) as connection:
            state = self.loaded(connection)
            match request:
                case ListWork() | ListSources():
                    return page(state, request)
                case AddDocument() | AddWebPage():
                    source = reference_source(request, at, origin)
                    state = observe_sources(state, (source,))
                    if request.work_id is not None:
                        work = find_work(state, request.work_id)
                        links = (
                            *tuple(link for link in work.links if link.source_id != source.id),
                            Association(
                                source.id,
                                "Web reference added to this work." if isinstance(source, WebPageSource) else "Document added to this work.",
                            ),
                        )
                        state, work = save_work(state, SaveWork(work.definition, links, work.id, work.revision), at)
                    self.persist(connection, state)
                    return DocumentAdded(source)
                case SaveWork():
                    state, work = save_work(state, request, at)
                case UnlinkWork():
                    state, work = unlink_work(state, request, at)
                case DismissWork(work_id=identity, expected_revision=expected, reason=reason):
                    work = find_work(state, identity)
                    if work.revision != expected:
                        raise ValueError("This work changed. Read its current revision before dismissing it.")
                    state = replace(
                        state,
                        revision=state.revision + 1,
                        works=tuple(item for item in state.works if item.id != identity),
                        dismissed=(*state.dismissed, DismissedWork(work, reason)),
                    )
                case RestoreWork(work_id=identity):
                    dismissal = next((item for item in state.dismissed if item.work.id == identity), None)
                    if dismissal is None:
                        raise ValueError("This work is not dismissed.")
                    work = replace(dismissal.work, revision=dismissal.work.revision + 1, updated_at=at, personal_state=True)
                    state = replace(
                        state,
                        revision=state.revision + 1,
                        works=(*state.works, work),
                        dismissed=tuple(item for item in state.dismissed if item.work.id != identity),
                    )
                case _ as unreachable:
                    assert_never(unreachable)
            self.persist(connection, state)
            return WorkSaved(work)
