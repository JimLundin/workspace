"""Concrete source adapters; captured observations never perform app writes."""

import threading
from collections.abc import Mapping
from dataclasses import replace
from typing import Literal, overload

from pydantic import TypeAdapter

from assistant.browser import BrowserResult
from assistant.browser_requests import BrowserRequest
from assistant.browser_values import BrowserError, BrowserStatus, PageList, PageRow
from assistant.personal_work_sources import Observations, Tab, kanban_source, outlook_source, teams_source
from assistant.web_apps import Located, WebAppOperation
from contracts.json_value import Json
from contracts.personal_work import (
    ApplicationSource,
    DocumentSource,
    KanbanSource,
    OutlookSource,
    Source,
    SourceKind,
    SourceOrigin,
    TeamsSource,
    WebPageSource,
    source_id,
    source_revision,
)

WIRE = TypeAdapter(dict[str, Json])
STATUS = TypeAdapter(BrowserStatus)


@overload
def source(kind: Literal[SourceKind.TEAMS], identity: str = "one", at: float = 10) -> TeamsSource: ...
@overload
def source(kind: Literal[SourceKind.OUTLOOK], identity: str = "one", at: float = 10) -> OutlookSource: ...
@overload
def source(kind: Literal[SourceKind.KANBAN], identity: str = "one", at: float = 10) -> KanbanSource: ...
@overload
def source(kind: Literal[SourceKind.DOCUMENT], identity: str = "one", at: float = 10) -> DocumentSource: ...
@overload
def source(kind: Literal[SourceKind.WEB_PAGE], identity: str = "one", at: float = 10) -> WebPageSource: ...
@overload
def source(kind: SourceKind, identity: str = "one", at: float = 10) -> Source: ...
def source(kind: SourceKind, identity: str = "one", at: float = 10) -> Source:
    title, excerpt = "Atlas migration", "Deploy Atlas after the supplier review."
    match kind:
        case SourceKind.TEAMS:
            return teams_source(identity, (title, excerpt, "https://teams.cloud.microsoft/"), at)
        case SourceKind.OUTLOOK:
            return outlook_source(identity, (title, excerpt, "https://outlook.office.com/mail/"), at)
        case SourceKind.KANBAN:
            return kanban_source(identity, (title, excerpt, "https://dev-team-kanban.fcg.palantirfoundry.com/"), at)
        case SourceKind.DOCUMENT:
            return reference(DocumentSource, kind, identity, "https://contoso.example.test/Atlas.docx", at)
        case SourceKind.WEB_PAGE:
            return reference(WebPageSource, kind, identity, "https://contoso.example.test/research", at)
        case SourceKind.MEETING:
            raise ValueError("Use a native meeting fixture.")


def reference[R: (DocumentSource, WebPageSource)](make: type[R], kind: SourceKind, identity: str, url: str, at: float) -> R:
    title, excerpt = "Atlas migration", "Deploy Atlas after the supplier review."
    return make(source_id(kind, identity), identity, title, excerpt, url, source_revision(title, excerpt, url), at, SourceOrigin.USER)


class CapturedSources:
    """Own fixture observation and lifecycle counters behind the source port."""

    def __init__(self, sources: tuple[ApplicationSource, ...] = ()) -> None:
        self.sources = sources
        self.refreshed = 0
        self.closed = 0

    def read(self, at: float, cancel: threading.Event) -> Observations:
        return Observations(tuple(replace(item, observed_at=at) for item in self.sources), ("teams", "outlook", "kanban"))

    def refresh(self) -> None:
        self.refreshed += 1

    def close(self) -> None:
        self.closed += 1


class CapturedBrowser:
    """Own typed page observations and an observable log of the queries that read them.

    Each answer must be an instance of its operation's result type, so a
    fixture cannot drift from the shape the real page script is checked against.
    """

    def __init__(
        self,
        tabs: tuple[Tab, ...] | BrowserStatus | BrowserError,
        answers: Mapping[Located, object],
        *,
        pages: Mapping[int, BrowserStatus] = frozendict(),
    ) -> None:
        self.tabs = tabs
        self.answers = answers
        self.pages: Mapping[int, BrowserStatus] = pages
        self.queries: list[Located] = []
        self.tab_reads = 0
        self.connections = 0
        self.closed = 0

    def connect(self, cancel: threading.Event) -> None:
        self.connections += 1

    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult:
        assert isinstance(request, PageList)
        self.tab_reads += 1
        if request.offset in self.pages:
            return BrowserResult(STATUS.dump_json(self.pages[request.offset], exclude_none=True).decode())
        match self.tabs:
            case BrowserError() as error:
                raise error
            case BrowserStatus() as status:
                return BrowserResult(STATUS.dump_json(status, exclude_none=True).decode())
            case tabs:
                status = BrowserStatus("attached", tuple(PageRow(tab.id, "", tab.url) for tab in tabs))
                return BrowserResult(STATUS.dump_json(status, exclude_none=True).decode())

    def web_app[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R:
        self.queries.append(query)
        match self.answers[query]:
            case BrowserError() as error:
                raise error
            case answer:
                return operation.result.validate_python(answer)

    def close(self) -> None:
        self.closed += 1
