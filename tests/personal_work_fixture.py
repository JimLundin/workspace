"""Concrete source adapters; captured observations never perform app writes."""

import threading
from collections.abc import Mapping
from dataclasses import replace

from pydantic import TypeAdapter

from assistant.browser import BrowserResult
from assistant.browser_values import BrowserError
from assistant.llm import Json
from assistant.personal_work_sources import Observations, observed_source
from automation.personal_work import SourceKind, WorkSource

WIRE = TypeAdapter(dict[str, Json])


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
    """Own a concrete response catalog and an observable browser-request log."""

    def __init__(self, responses: Mapping[tuple[str, str, int], dict[str, Json] | BrowserError]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, int]] = []
        self.connections = 0
        self.closed = 0

    def connect(self, cancel: threading.Event) -> None:
        self.connections += 1

    def request(self, operation: str, args: dict[str, Json], cancel: threading.Event) -> BrowserResult:
        target, offset = args.get("target_id", ""), args.get("offset", 0)
        assert isinstance(target, str) and isinstance(offset, int)
        key = (operation, target, offset)
        self.calls.append(key)
        response = self.responses[key]
        if isinstance(response, BrowserError):
            raise response
        return BrowserResult(WIRE.dump_json(response).decode())

    def close(self) -> None:
        self.closed += 1
