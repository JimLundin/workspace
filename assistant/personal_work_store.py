"""Desktop-owned transactional persistence for the personal-work catalog."""

from dataclasses import replace
from pathlib import Path
from typing import assert_never

from automation import journal
from automation.personal_work import (
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
    PersonalRequest,
    PersonalResponse,
    RestoreWork,
    SaveWork,
    SourceKind,
    UnlinkWork,
    WorkPlan,
    WorkSaved,
    WorkSource,
    find_work,
    observe_sources,
    page,
    reconcile_plan,
    save_work,
    source_id,
    source_revision,
    unlink_work,
)
from automation.work_documents import document_identity


class PersonalStore:
    """Each call owns one real SQLite transaction; observations are immutable.

    This uses the existing work database, with an independent catalog table and
    revision. Each write transaction protects edits from concurrent model results.
    """

    __slots__ = ("path",)

    def __init__(self, path: Path) -> None:
        self.path = path
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

    def observe(self, sources: tuple[WorkSource, ...]) -> Catalog:
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

    def handle(self, request: PersonalRequest, at: float) -> PersonalResponse:
        with journal.writing(self.path) as connection:
            state = self.loaded(connection)
            match request:
                case ListWork() | ListSources():
                    return page(state, request)
                case AddDocument() | AddWebPage():
                    location = request.reference.url
                    kind = SourceKind.WEB_PAGE if isinstance(request, AddWebPage) else SourceKind.DOCUMENT
                    source = WorkSource(
                        source_id(kind, document_identity(location)),
                        kind,
                        document_identity(location),
                        request.title,
                        request.excerpt,
                        location,
                        source_revision(request.title, request.excerpt, location),
                        at,
                    )
                    state = observe_sources(state, (source,))
                    if request.work_id is not None:
                        work = find_work(state, request.work_id)
                        links = (
                            *tuple(link for link in work.links if link.source_id != source.id),
                            Association(
                                source.id, "Web reference added to this work." if kind is SourceKind.WEB_PAGE else "Document added to this work."
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
