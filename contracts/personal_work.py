"""Personal work, source associations and immutable catalog contracts.

Work threads are ongoing user concerns. Agent tasks remain execution requests in
TaskStore. Pydantic owns contract validation mechanics; our policies own
source identity, stale edits, association corrections and model reconciliation.
"""

import hashlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from functools import reduce
from itertools import chain, groupby
from typing import Annotated, Final, Literal
from urllib.parse import urlsplit

from pydantic import Field, StringConstraints, TypeAdapter

from contracts.meetings import Meeting, MeetingConversation
from contracts.work_documents import DocumentReference, WebDocument, checked_url, document_identity

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
    MEETING = "meeting"


class WorkState(StrEnum):
    ACTIVE = "active"
    WAITING = "waiting"
    DONE = "done"


class SourceOrigin(StrEnum):
    OBSERVED = "observed"
    USER = "user"
    AGENT = "agent"


_TEAMS_HOSTS: Final = frozenset({"teams.cloud.microsoft", "teams.microsoft.com"})
_OUTLOOK_HOSTS: Final = frozenset({"outlook.office.com", "outlook.office365.com", "outlook.cloud.microsoft"})
_KANBAN_HOSTS: Final = frozenset({"dev-team-kanban.fcg.palantirfoundry.com"})


def _check_identity(identity: str, *, kind: SourceKind, source: str, parent_id: str | None) -> None:
    if identity != source_id(kind, source, parent_id=parent_id) or identity == parent_id:
        raise ValueError("The source identity does not match its application identity or parent.")


def _check_application(url: str, hosts: frozenset[str]) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("The source must point to its observed business application.")


@dataclass(frozen=True, slots=True)
class TeamsSource:
    """A Teams conversation observed in the browser, or one message in it (`parent_id`)."""

    id: Identity
    identity: Identity
    title: Title
    excerpt: Detail
    url: Annotated[str, Field(max_length=4000)]
    revision: Identity
    observed_at: Timestamp
    parent_id: Identity | None = None
    kind: Literal[SourceKind.TEAMS] = SourceKind.TEAMS

    def __post_init__(self) -> None:
        _check_identity(self.id, kind=self.kind, source=self.identity, parent_id=self.parent_id)
        _check_application(self.url, _TEAMS_HOSTS)

    @property
    def origin(self) -> SourceOrigin:
        return SourceOrigin.OBSERVED


@dataclass(frozen=True, slots=True)
class OutlookSource:
    """An Outlook conversation observed in the browser, or one email in it (`parent_id`)."""

    id: Identity
    identity: Identity
    title: Title
    excerpt: Detail
    url: Annotated[str, Field(max_length=4000)]
    revision: Identity
    observed_at: Timestamp
    parent_id: Identity | None = None
    kind: Literal[SourceKind.OUTLOOK] = SourceKind.OUTLOOK

    def __post_init__(self) -> None:
        _check_identity(self.id, kind=self.kind, source=self.identity, parent_id=self.parent_id)
        _check_application(self.url, _OUTLOOK_HOSTS)

    @property
    def origin(self) -> SourceOrigin:
        return SourceOrigin.OBSERVED


@dataclass(frozen=True, slots=True)
class KanbanSource:
    """A Kanban ticket observed on a rendered board."""

    id: Identity
    identity: Identity
    title: Title
    excerpt: Detail
    url: Annotated[str, Field(max_length=4000)]
    revision: Identity
    observed_at: Timestamp
    kind: Literal[SourceKind.KANBAN] = SourceKind.KANBAN

    def __post_init__(self) -> None:
        _check_identity(self.id, kind=self.kind, source=self.identity, parent_id=None)
        _check_application(self.url, _KANBAN_HOSTS)

    @property
    def parent_id(self) -> None:
        return None

    @property
    def origin(self) -> SourceOrigin:
        return SourceOrigin.OBSERVED


@dataclass(frozen=True, slots=True)
class DocumentSource:
    """A document the user or the agent added by its location."""

    id: Identity
    identity: Identity
    title: Title
    excerpt: Detail
    url: Annotated[str, Field(max_length=4000)]
    revision: Identity
    observed_at: Timestamp
    origin: SourceOrigin
    kind: Literal[SourceKind.DOCUMENT] = SourceKind.DOCUMENT

    def __post_init__(self) -> None:
        _check_identity(self.id, kind=self.kind, source=self.identity, parent_id=None)
        checked_url(self.url)

    @property
    def parent_id(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class WebPageSource:
    """A web page the user or the agent added as a reference."""

    id: Identity
    identity: Identity
    title: Title
    excerpt: Detail
    url: Annotated[str, Field(max_length=4000)]
    revision: Identity
    observed_at: Timestamp
    origin: SourceOrigin
    kind: Literal[SourceKind.WEB_PAGE] = SourceKind.WEB_PAGE

    def __post_init__(self) -> None:
        _check_identity(self.id, kind=self.kind, source=self.identity, parent_id=None)
        checked_url(self.url)
        if urlsplit(self.url).scheme != "https":
            raise ValueError("Web pages require an HTTPS reference.")

    @property
    def parent_id(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class MeetingSource:
    """A catalog reference to one native event; its conversation stays in its journal."""

    id: Identity
    meeting: Meeting
    excerpt: Detail
    observed_at: Timestamp
    kind: Literal[SourceKind.MEETING] = SourceKind.MEETING

    def __post_init__(self) -> None:
        if self.id != source_id(SourceKind.MEETING, self.meeting.identity):
            raise ValueError("The meeting source identity does not match its event.")

    @property
    def identity(self) -> str:
        return self.meeting.identity

    @property
    def title(self) -> str:
        return self.meeting.title

    @property
    def revision(self) -> str:
        return str(self.meeting.revision)

    @property
    def url(self) -> str:
        return self.meeting.transcript_path

    @property
    def parent_id(self) -> None:
        return None

    @property
    def origin(self) -> SourceOrigin:
        return SourceOrigin.OBSERVED


type ApplicationSource = TeamsSource | OutlookSource | KanbanSource
"""Evidence observed in a signed-in business application; opening it asks the agent."""
type ReferenceSource = DocumentSource | WebPageSource
"""A location added as a reference; it opens directly."""
type Source = ApplicationSource | ReferenceSource | MeetingSource


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
    sources: Annotated[tuple[Source, ...], Field(max_length=1000)] = ()
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
class ReadMeeting:
    source_id: Identity
    offset: Annotated[int, Field(strict=True, ge=0)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 50
    operation: Literal["work_items_meeting"] = "work_items_meeting"


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
    ListWork | ListSources | ReadMeeting | SaveWork | UnlinkWork | AddDocument | AddWebPage | DismissWork | RestoreWork,
    Field(discriminator="operation"),
]


@dataclass(frozen=True, slots=True)
class WorkPage:
    works: tuple[WorkThread, ...]
    sources: tuple[Source, ...]
    total: int
    next_offset: int | None
    kind: Literal["personal_work"] = "personal_work"
    dismissed: tuple[DismissedWork, ...] = ()


@dataclass(frozen=True, slots=True)
class SourcePage:
    sources: tuple[Source, ...]
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
    source: ReferenceSource
    kind: Literal["document_added"] = "document_added"


type PersonalResponse = WorkPage | SourcePage | WorkSaved | WorkRefused | DocumentAdded | MeetingConversation


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
    sources: tuple[Source, ...]
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


def reference_id(request: AddDocument | AddWebPage) -> str:
    """The source identity an added document or web page registers under."""
    kind = SourceKind.WEB_PAGE if isinstance(request, AddWebPage) else SourceKind.DOCUMENT
    return source_id(kind, document_identity(request.reference.url))


def reference_source(request: AddDocument | AddWebPage, at: float, origin: SourceOrigin) -> ReferenceSource:
    location = request.reference.url
    parts = (reference_id(request), document_identity(location), request.title, request.excerpt, location)
    revision = source_revision(request.title, request.excerpt, location)
    match request:
        case AddDocument():
            return DocumentSource(*parts, revision, at, origin)
        case AddWebPage():
            return WebPageSource(*parts, revision, at, origin)


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


def source_context(sources: Sequence[Source], referenced: frozenset[str]) -> frozenset[str]:
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


def _newer(previous: Source, source: Source) -> Source:
    """The source an observation leaves in the index: a meeting keeps its latest revision."""
    match source, previous:
        case MeetingSource(meeting=incoming), MeetingSource(meeting=stored):
            return previous if incoming.revision < stored.revision or (incoming == stored and source.excerpt == previous.excerpt) else source
        case _:
            return source if source.observed_at >= previous.observed_at else previous


def _source_id(source: Source) -> str:
    return source.id


def _merged(stored: Mapping[str, Source], identity: str, incoming: Iterable[Source]) -> Source:
    return reduce(_newer, chain((stored[identity],) if identity in stored else (), incoming))


def observe_sources(catalog: Catalog, sources: tuple[Source, ...]) -> Catalog:
    stored = {source.id: source for source in catalog.sources}
    # A stable sort keeps each identity's observations in arrival order for the merge.
    current = stored | {
        identity: _merged(stored, identity, incoming) for identity, incoming in groupby(sorted(sources, key=_source_id), key=_source_id)
    }
    referenced = frozenset(
        link.source_id for work in (*catalog.works, *(item.work for item in catalog.dismissed)) for link in work.links
    ) | frozenset(source.id for source in current.values() if isinstance(source, DocumentSource | WebPageSource | MeetingSource))
    # A conversation reference retains its observed pieces; a specific message
    # retains its containing conversation. Missing browser rows prove no deletion.
    referenced = source_context(tuple(current.values()), referenced)

    # Missing rendered rows do not delete evidence or its associations. Bound
    # unconnected observations while retaining the sources of saved work.
    def order(source: Source) -> tuple[bool, float, str]:
        return source.id not in referenced, -source.observed_at, source.id

    retained = tuple(sorted(current.values(), key=order)[:1000])
    if retained == catalog.sources:
        return catalog
    return replace(catalog, revision=catalog.revision + 1, sources=retained)


@dataclass(frozen=True, slots=True)
class _Planned:
    item: PlannedWork
    identity: str
    links: tuple[Association, ...]
    original: WorkThread | None


def _dismissed(catalog: Catalog, item: PlannedWork, links: tuple[Association, ...]) -> bool:
    source_ids = frozenset(link.source_id for link in links)
    return any(
        item.work_id == dismissed.work.id
        or (
            item.work_id is None
            and (
                item.definition.goal.casefold() == dismissed.work.definition.goal.casefold()
                or source_ids <= frozenset(link.source_id for link in dismissed.work.links)
            )
        )
        for dismissed in catalog.dismissed
    )


def _planned(catalog: Catalog, plan: WorkPlan) -> Iterator[_Planned]:
    """Resolve each undismissed planned work to its identity, refusing a second update of one work."""
    rejected = frozenset((item.work_id, item.source_id) for item in catalog.rejected)
    seen: frozenset[str] = frozenset()
    for item in plan.works:
        links = checked_links(catalog, item.links)
        if _dismissed(catalog, item, links):
            continue
        original = find_work(catalog, item.work_id) if item.work_id is not None else None
        identity = (
            original.id
            if original is not None
            else "work:"
            + hashlib.sha256(_WORK_KEY.dump_json((item.definition.goal.casefold(), tuple(sorted(link.source_id for link in links))))).hexdigest()[:24]
        )
        if identity in seen:
            raise ValueError("The model updated the same work twice.")
        seen = seen | {identity}
        yield _Planned(item, identity, tuple(link for link in links if (identity, link.source_id) not in rejected), original)


def _planned_work(catalog: Catalog, planned: _Planned, at: float) -> WorkThread | None:
    """The changed or new work a planned item makes, or None when it changes nothing."""
    item, identity, links = planned.item, planned.identity, planned.links
    original = planned.original if planned.original is not None else next((work for work in catalog.works if work.id == identity), None)
    if original is None:
        return WorkThread(identity, 0, item.definition, links, at, at) if links else None
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
        return None
    return replace(original, revision=original.revision + 1, definition=definition, links=merged, updated_at=at)


def reconcile_plan(catalog: Catalog, plan: WorkPlan, at: float) -> Catalog:
    # Each planned work has its own identity, so every change applies to the
    # catalog's works independently: replace existing works and append new ones.
    changes = tuple(work for planned in _planned(catalog, plan) if (work := _planned_work(catalog, planned, at)) is not None)
    changed = {work.id: work for work in changes}
    existing = frozenset(work.id for work in catalog.works)
    works = (*(changed.get(work.id, work) for work in catalog.works), *(work for work in changes if work.id not in existing))
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
