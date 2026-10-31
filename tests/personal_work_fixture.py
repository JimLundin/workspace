"""Concrete source adapters; captured observations never perform app writes."""

import threading
from collections.abc import Mapping
from dataclasses import replace

from pydantic import TypeAdapter

from assistant.browser import BrowserResult
from assistant.browser_requests import BrowserRequest
from assistant.browser_values import BrowserError, BrowserStatus, PageList, PageRow
from assistant.personal_work_sources import Observations, Tab, observed_source
from assistant.web_apps import Located, WebAppOperation
from automation.json_value import Json
from automation.personal_work import SourceKind, WorkSource

WIRE = TypeAdapter(dict[str, Json])
STATUS = TypeAdapter(BrowserStatus)


def source(kind: SourceKind, identity: str = "one", at: float = 10) -> WorkSource:
    match kind:
        case SourceKind.TEAMS:
            url = "https://teams.cloud.microsoft/"
        case SourceKind.OUTLOOK:
            url = "https://outlook.office.com/mail/"
        case SourceKind.DOCUMENT:
            url = "https://contoso.example.test/Atlas.docx"
        case SourceKind.WEB_PAGE:
            url = "https://contoso.example.test/research"
        case SourceKind.KANBAN:
            url = "https://dev-team-kanban.fcg.palantirfoundry.com/"
    return observed_source(kind, identity, ("Atlas migration", "Deploy Atlas after the supplier review.", url), at)


class CapturedSources:
    """Own fixture observation and lifecycle counters behind the source port."""

    def __init__(self, sources: tuple[WorkSource, ...] = ()) -> None:
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

    def __init__(self, tabs: tuple[Tab, ...] | BrowserError, answers: Mapping[Located, object]) -> None:
        self.tabs = tabs
        self.answers = answers
        self.queries: list[Located] = []
        self.tab_reads = 0
        self.connections = 0
        self.closed = 0

    def connect(self, cancel: threading.Event) -> None:
        self.connections += 1

    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult:
        assert isinstance(request, PageList)
        self.tab_reads += 1
        match self.tabs:
            case BrowserError() as error:
                raise error
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
