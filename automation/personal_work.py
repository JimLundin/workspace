"""Personal work, source associations and transactional catalog persistence.

Work threads are ongoing user concerns. Agent tasks remain execution requests in
TaskStore. SQLite/Pydantic own storage and validation mechanics; our policies own
source identity, stale edits, association corrections and model reconciliation.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, assert_never
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, TypeAdapter

from automation import journal
from automation.work_documents import DocumentReference, WebDocument, checked_url, document_identity

type Identity = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
type Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
type Detail = Annotated[str, Field(max_length=6000)]
type Revision = Annotated[int, Field(strict=True, ge=0)]
type Timestamp = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class SourceKind(StrEnum):
    TEAMS = "teams"
    OUTLOOK = "outlook"
    KANBAN = "kanban"
    DOCUMENT = "document"
    WEB_PAGE = "web_page"


class WorkState(StrEnum):
    ACTIVE = "active"
    WAITING = "waiting"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class WorkSource:
    id: Identity
    kind: SourceKind
    identity: Identity
    title: Title
    excerpt: Detail
    url: Annotated[str, Field(max_length=4000)]
    revision: Identity
    observed_at: Timestamp
    parent_id: Identity | None = None

    def __post_init__(self) -> None:
        if self.id != source_id(self.kind, self.identity, parent_id=self.parent_id) or self.id == self.parent_id:
            raise ValueError("The source identity does not match its application identity or parent.")
        if self.kind in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE):
            checked_url(self.url)
            if self.kind is SourceKind.WEB_PAGE and urlsplit(self.url).scheme != "https":
                raise ValueError("Web pages require an HTTPS reference.")
            return
        hosts: tuple[str, ...]
        match self.kind:
            case SourceKind.TEAMS:
                hosts = ("teams.cloud.microsoft", "teams.microsoft.com")
            case SourceKind.OUTLOOK:
                hosts = ("outlook.office.com", "outlook.office365.com", "outlook.cloud.microsoft")
            case SourceKind.KANBAN:
                hosts = ("dev-team-kanban.fcg.palantirfoundry.com",)
            case _ as unreachable:
                assert_never(unreachable)
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("The source must point to its observed business application.")
        if self.id != source_id(self.kind, self.identity, parent_id=self.parent_id):
            raise ValueError("The source identity does not match its application identity.")


@dataclass(frozen=True, slots=True)
class Association:
    source_id: Identity
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]


@dataclass(frozen=True, slots=True)
class WorkDefinition:
    title: Title
    goal: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    summary: Detail = ""
    next_step: Annotated[str, Field(max_length=2000)] = ""
    state: WorkState = WorkState.ACTIVE
    project: Annotated[str, Field(max_length=240)] = ""


@dataclass(frozen=True, slots=True)
class WorkThread:
    id: Identity
    revision: Revision
    definition: WorkDefinition
    links: tuple[Association, ...]
    updated_at: Timestamp
    created_at: Timestamp
    personal_state: bool = field(default=False, kw_only=True)


@dataclass(frozen=True, slots=True)
class RejectedAssociation:
    work_id: Identity
    source_id: Identity


@dataclass(frozen=True, slots=True)
class DismissedWork:
    work: WorkThread
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]


@dataclass(frozen=True, slots=True)
class Catalog:
    revision: Revision = 0
    works: Annotated[tuple[WorkThread, ...], Field(max_length=200)] = ()
    sources: Annotated[tuple[WorkSource, ...], Field(max_length=1000)] = ()
    rejected: Annotated[tuple[RejectedAssociation, ...], Field(max_length=4000)] = ()
    dismissed: Annotated[tuple[DismissedWork, ...], Field(max_length=200)] = ()

    def __post_init__(self) -> None:
        parents = frozendict((source.id, source.parent_id) for source in self.sources)
        for identity in parents:
            path: frozenset[str] = frozenset()
            current: str | None = identity
            while current is not None:
                if current in path:
                    raise ValueError("Observed sources cannot form a containment cycle.")
                path = path | {current}
                current = parents.get(current)


@dataclass(frozen=True, slots=True)
class PersonalView:
    catalog: Catalog = field(default_factory=Catalog)
    status: str = "Connecting your work across Teams, Outlook and Kanban."


@dataclass(frozen=True, slots=True)
class ListWork:
    query: Annotated[str, Field(max_length=500)] = ""
    offset: Annotated[int, Field(strict=True, ge=0)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 10
    operation: Literal["work_items_list"] = "work_items_list"


@dataclass(frozen=True, slots=True)
class ListSources:
    query: Annotated[str, Field(max_length=500)] = ""
    offset: Annotated[int, Field(strict=True, ge=0)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 10
    operation: Literal["work_items_sources"] = "work_items_sources"


@dataclass(frozen=True, slots=True)
class SaveWork:
    definition: WorkDefinition
    links: Annotated[tuple[Association, ...], Field(max_length=100)] = ()
    work_id: Identity | None = None
    expected_revision: Revision | None = None
    operation: Literal["work_items_save"] = "work_items_save"


@dataclass(frozen=True, slots=True)
class UnlinkWork:
    work_id: Identity
    source_id: Identity
    expected_revision: Revision
    operation: Literal["work_items_unlink"] = "work_items_unlink"


@dataclass(frozen=True, slots=True)
class AddDocument:
    # Registration binds a location, presentation and optional work connection.
    title: Title
    reference: DocumentReference
    excerpt: Detail = ""
    work_id: Identity | None = None
    operation: Literal["work_items_add_document"] = "work_items_add_document"


@dataclass(frozen=True, slots=True)
class AddWebPage:
    title: Title
    reference: WebDocument
    excerpt: Detail = ""
    work_id: Identity | None = None
    operation: Literal["work_items_add_web_page"] = "work_items_add_web_page"


@dataclass(frozen=True, slots=True)
class DismissWork:
    work_id: Identity
    expected_revision: Revision
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]
    operation: Literal["work_items_dismiss"] = "work_items_dismiss"


@dataclass(frozen=True, slots=True)
class RestoreWork:
    work_id: Identity
    operation: Literal["work_items_restore"] = "work_items_restore"


type PersonalRequest = Annotated[
    ListWork | ListSources | SaveWork | UnlinkWork | AddDocument | AddWebPage | DismissWork | RestoreWork, Field(discriminator="operation")
]


@dataclass(frozen=True, slots=True)
class WorkPage:
    works: tuple[WorkThread, ...]
    sources: tuple[WorkSource, ...]
    total: int
    next_offset: int | None
    kind: Literal["personal_work"] = "personal_work"
    dismissed: tuple[DismissedWork, ...] = ()


@dataclass(frozen=True, slots=True)
class SourcePage:
    sources: tuple[WorkSource, ...]
    total: int
    next_offset: int | None
    kind: Literal["work_sources"] = "work_sources"


@dataclass(frozen=True, slots=True)
class WorkSaved:
    work: WorkThread
    kind: Literal["work_saved"] = "work_saved"


@dataclass(frozen=True, slots=True)
class WorkRefused:
    error: str
    kind: Literal["work_refused"] = "work_refused"


@dataclass(frozen=True, slots=True)
class DocumentAdded:
    source: WorkSource
    kind: Literal["document_added"] = "document_added"


type PersonalResponse = WorkPage | SourcePage | WorkSaved | WorkRefused | DocumentAdded


@dataclass(frozen=True, slots=True)
class PlannedWork:
    work_id: Identity | None
    definition: WorkDefinition
    links: Annotated[tuple[Association, ...], Field(min_length=1, max_length=100)]


@dataclass(frozen=True, slots=True)
class WorkPlan:
    works: Annotated[tuple[PlannedWork, ...], Field(max_length=30)] = ()


@dataclass(frozen=True, slots=True)
class CorrelationInput:
    catalog_revision: Revision
    works: tuple[WorkThread, ...]
    sources: tuple[WorkSource, ...]
    rejected: tuple[RejectedAssociation, ...]
    dismissed: tuple[DismissedWork, ...] = ()


@dataclass(frozen=True, slots=True)
class OpenWorkSource:
    source_id: Identity


class RefreshPersonalWork(StrEnum):
    REFRESH = "refresh"


CATALOG = TypeAdapter(Catalog)
PERSONAL_REQUEST = TypeAdapter(PersonalRequest)
PERSONAL_RESPONSE = TypeAdapter(PersonalResponse)
WORK_PLAN = TypeAdapter(WorkPlan)
CORRELATION_INPUT = TypeAdapter(CorrelationInput)
_SOURCE_KEY = TypeAdapter(tuple[SourceKind, str])
_SOURCE_PART_KEY = TypeAdapter(tuple[SourceKind, str, str])
_SOURCE_CONTENT = TypeAdapter(tuple[str, str, str])
_WORK_KEY = TypeAdapter(tuple[str, tuple[str, ...]])


def source_id(kind: SourceKind, identity: str, *, parent_id: str | None = None) -> str:
    key = _SOURCE_KEY.dump_json((kind, identity)) if parent_id is None else _SOURCE_PART_KEY.dump_json((kind, parent_id, identity))
    return kind.value + ":" + hashlib.sha256(key).hexdigest()[:24]


def source_revision(title: str, excerpt: str, url: str) -> str:
    return hashlib.sha256(_SOURCE_CONTENT.dump_json((title, excerpt, url))).hexdigest()


def find_work(catalog: Catalog, identity: str) -> WorkThread:
    work = next((work for work in catalog.works if work.id == identity), None)
    if work is None:
        raise ValueError("That piece of work no longer exists. Refresh My work.")
    return work


def checked_links(catalog: Catalog, links: tuple[Association, ...]) -> tuple[Association, ...]:
    identities = tuple(link.source_id for link in links)
    if len(set(identities)) != len(identities) or not set(identities) <= {source.id for source in catalog.sources}:
        raise ValueError("Connections need distinct source identities observed by Workspace.")
    return links


def save_work(catalog: Catalog, command: SaveWork, at: float) -> tuple[Catalog, WorkThread]:
    links = checked_links(catalog, command.links)
    if command.work_id is None:
        if command.expected_revision is not None:
            raise ValueError("New work cannot have an expected revision.")
        identity = (
            "work:"
            + hashlib.sha256(_WORK_KEY.dump_json((command.definition.goal.casefold(), tuple(sorted(link.source_id for link in links))))).hexdigest()[
                :24
            ]
        )
        if any(work.id == identity for work in catalog.works):
            raise ValueError("This work already exists. Read its identity before updating it.")
        if any(item.work.id == identity for item in catalog.dismissed):
            raise ValueError("This work was dismissed. Restore it before updating it.")
        work = WorkThread(identity, 0, command.definition, links, at, at, personal_state=True)
        works = (*catalog.works, work)
    else:
        original = find_work(catalog, command.work_id)
        if command.expected_revision != original.revision:
            raise ValueError("This work changed since it was read. Refresh before saving.")
        work = replace(original, revision=original.revision + 1, definition=command.definition, links=links, updated_at=at, personal_state=True)
        works = tuple(work if item.id == work.id else item for item in catalog.works)
    # Explicitly adding a connection again overrides the earlier correction.
    rejected = tuple(item for item in catalog.rejected if item.work_id != work.id or item.source_id not in {link.source_id for link in links})
    return replace(catalog, revision=catalog.revision + 1, works=works, rejected=rejected), work


def unlink_work(catalog: Catalog, command: UnlinkWork, at: float) -> tuple[Catalog, WorkThread]:
    original = find_work(catalog, command.work_id)
    if original.revision != command.expected_revision:
        raise ValueError("This work changed since it was read. Refresh before correcting it.")
    if command.source_id not in {link.source_id for link in original.links}:
        raise ValueError("That source is no longer connected to this work.")
    work = replace(
        original, revision=original.revision + 1, links=tuple(link for link in original.links if link.source_id != command.source_id), updated_at=at
    )
    rejection = RejectedAssociation(work.id, command.source_id)
    return replace(
        catalog,
        revision=catalog.revision + 1,
        works=tuple(work if item.id == work.id else item for item in catalog.works),
        rejected=(*catalog.rejected, rejection) if rejection not in catalog.rejected else catalog.rejected,
    ), work


def source_context(sources: Sequence[WorkSource], referenced: frozenset[str]) -> frozenset[str]:
    """A conversation retains its pieces; a message retains its conversation."""
    while True:
        extended = (
            referenced
            | frozenset(source.id for source in sources if source.parent_id in referenced)
            | frozenset(source.parent_id for source in sources if source.id in referenced and source.parent_id is not None)
        )
        if extended == referenced:
            return referenced
        referenced = extended


def observe_sources(catalog: Catalog, sources: tuple[WorkSource, ...]) -> Catalog:
    current = {source.id: source for source in catalog.sources}
    for source in sources:
        previous = current.get(source.id)
        if previous is None or source.observed_at >= previous.observed_at:
            current[source.id] = source
    referenced = frozenset(
        link.source_id for work in (*catalog.works, *(item.work for item in catalog.dismissed)) for link in work.links
    ) | frozenset(source.id for source in current.values() if source.kind in (SourceKind.DOCUMENT, SourceKind.WEB_PAGE))
    # A conversation reference retains its observed pieces; a specific message
    # retains its containing conversation. Missing browser rows prove no deletion.
    referenced = source_context(tuple(current.values()), referenced)

    # Missing rendered rows do not delete evidence or its associations. Bound
    # unconnected observations while retaining the sources of saved work.
    def order(source: WorkSource) -> tuple[bool, float, str]:
        return source.id not in referenced, -source.observed_at, source.id

    retained = tuple(sorted(current.values(), key=order)[:1000])
    if retained == catalog.sources:
        return catalog
    return replace(catalog, revision=catalog.revision + 1, sources=retained)


def reconcile_plan(catalog: Catalog, plan: WorkPlan, at: float) -> Catalog:
    works = catalog.works
    updated: set[str] = set()
    rejected = frozenset((item.work_id, item.source_id) for item in catalog.rejected)
    for item in plan.works:
        links = checked_links(catalog, item.links)
        source_ids = frozenset(link.source_id for link in links)
        if any(
            item.work_id == dismissed.work.id
            or (
                item.work_id is None
                and (
                    item.definition.goal.casefold() == dismissed.work.definition.goal.casefold()
                    or source_ids <= frozenset(link.source_id for link in dismissed.work.links)
                )
            )
            for dismissed in catalog.dismissed
        ):
            continue
        original = find_work(catalog, item.work_id) if item.work_id is not None else None
        identity = (
            original.id
            if original is not None
            else "work:"
            + hashlib.sha256(_WORK_KEY.dump_json((item.definition.goal.casefold(), tuple(sorted(link.source_id for link in links))))).hexdigest()[:24]
        )
        if identity in updated:
            raise ValueError("The model updated the same work twice.")
        updated.add(identity)
        links = tuple(link for link in links if (identity, link.source_id) not in rejected)
        if original is None:
            original = next((work for work in works if work.id == identity), None)
        if original is not None:
            # A partial model review can add associations, never erase existing
            # ones. Corrections are explicit, durable user operations.
            merged = tuple(link for link in original.links if link.source_id not in {link.source_id for link in links}) + links
            definition = item.definition
            if original.personal_state:
                definition = replace(
                    definition,
                    title=original.definition.title,
                    goal=original.definition.goal,
                    state=original.definition.state,
                    project=original.definition.project,
                )
            if definition == original.definition and merged == original.links:
                continue
            work = replace(original, revision=original.revision + 1, definition=definition, links=merged, updated_at=at)
            works = tuple(work if entry.id == identity else entry for entry in works)
        elif links:
            work = WorkThread(identity, 0, item.definition, links, at, at)
            works = (*works, work)
    if works == catalog.works:
        return catalog
    return CATALOG.validate_python(replace(catalog, revision=catalog.revision + 1, works=works))


def work_order(work: WorkThread) -> tuple[bool, float, str]:
    return work.definition.state is WorkState.DONE, -work.updated_at, work.id


def page(catalog: Catalog, query: ListWork | ListSources) -> WorkPage | SourcePage:
    if isinstance(query, ListSources):
        sources = tuple(
            source
            for source in catalog.sources
            if query.query.casefold()
            in (
                source.id + " " + source.identity + " " + (source.parent_id or "") + " " + source.url + " " + source.title + " " + source.excerpt
            ).casefold()
        )
        selected = tuple(replace(source, excerpt=source.excerpt[:1000]) for source in sources[query.offset : query.offset + query.limit])
        return SourcePage(selected, len(sources), query.offset + len(selected) if query.offset + len(selected) < len(sources) else None)
    works = tuple(
        sorted(
            (
                work
                for work in catalog.works
                if query.query.casefold() in (work.definition.title + " " + work.definition.goal + " " + work.definition.project).casefold()
            ),
            key=work_order,
        )
    )
    selected_works = works[query.offset : query.offset + query.limit]
    linked = frozenset(link.source_id for work in selected_works for link in work.links)
    return WorkPage(
        selected_works,
        tuple(replace(source, excerpt=source.excerpt[:400]) for source in catalog.sources if source.id in linked),
        len(works),
        query.offset + len(selected_works) if query.offset + len(selected_works) < len(works) else None,
        dismissed=tuple(
            item
            for item in catalog.dismissed
            if query.query.casefold() in (item.work.id + " " + item.work.definition.title + " " + item.reason).casefold()
        )[query.offset : query.offset + query.limit],
    )


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
