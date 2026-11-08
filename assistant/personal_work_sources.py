"""Read-only work evidence from opted-in, signed-in browser pages.

The reader never changes a board filter, searches an inbox, opens a message or
selects a Teams chat. Coverage is the rendered pages; absent rows retain their
saved evidence. CDP targets belong to this observation and are never persisted.
"""

import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from typing import Final, Literal, Protocol, assert_never
from urllib.parse import urlsplit

from pydantic import TypeAdapter

from assistant.browser import BrowserResult
from assistant.browser_requests import BrowserRequest
from assistant.browser_values import BrowserError, BrowserStatus, PageList
from assistant.web_apps import (
    KANBAN_BOARD,
    OUTLOOK_READ,
    TEAMS_READ,
    Board,
    BoardQuery,
    Located,
    Mailbox,
    MailList,
    TeamsPage,
    TeamsQuery,
    WebAppOperation,
)
from cell import Cell
from contracts.personal_work import ApplicationSource, KanbanSource, OutlookSource, SourceKind, TeamsSource, source_id, source_revision


class BrowserPort(Protocol):
    def connect(self, cancel: threading.Event) -> None: ...
    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult: ...
    def web_app[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R: ...
    def close(self) -> None: ...


class Piece(Protocol):
    """An individually identified message within an observed conversation."""

    @property
    def identity(self) -> str: ...
    @property
    def sender(self) -> str: ...
    @property
    def text(self) -> str: ...


@dataclass(frozen=True, slots=True)
class Tab:
    id: str
    url: str


@dataclass(frozen=True, slots=True)
class Observations:
    sources: tuple[ApplicationSource, ...]
    coverage: tuple[str, ...]
    problems: tuple[str, ...] = ()


_STATUS = TypeAdapter(BrowserStatus)
ACCESS_RETRY_SECONDS: Final = 60.0


type Application = Literal[SourceKind.TEAMS, SourceKind.OUTLOOK, SourceKind.KANBAN]
"""The applications whose signed-in pages the reader observes."""


def kind_for(url: str) -> Application | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        return None
    match parsed.hostname:
        case "teams.cloud.microsoft" | "teams.microsoft.com":
            return SourceKind.TEAMS
        case "outlook.office.com" | "outlook.office365.com" | "outlook.cloud.microsoft":
            return SourceKind.OUTLOOK if parsed.path.startswith("/mail") else None
        case "dev-team-kanban.fcg.palantirfoundry.com":
            return SourceKind.KANBAN
        case _:
            return None


@dataclass(frozen=True, slots=True)
class Observed:
    """One observation's content, apart from its routing identity and time.
    Content changes determine a source's revision; time does not."""

    title: str
    excerpt: str
    url: str

    @classmethod
    def of(cls, details: tuple[str, str, str], fallback: str) -> Observed:
        title, excerpt, url = details
        return cls(title.strip()[:240] or fallback, excerpt[:6000], url)

    @property
    def revision(self) -> str:
        return source_revision(self.title, self.excerpt, self.url)


_APPLICATIONS: Final = frozendict(
    {TeamsSource: (SourceKind.TEAMS, "Teams"), OutlookSource: (SourceKind.OUTLOOK, "Outlook"), KanbanSource: (SourceKind.KANBAN, "Kanban")}
)
"""Each application's source kind and the title an untitled observation falls back to."""


def application_source[S: ApplicationSource](source: type[S], identity: str, details: tuple[str, str, str], at: float) -> S:
    kind, fallback = _APPLICATIONS[source]
    seen = Observed.of(details, fallback)
    return source(source_id(kind, identity), identity, seen.title, seen.excerpt, seen.url, seen.revision, at)


def board_sources(board: Board, tab: Tab, at: float) -> tuple[KanbanSource, ...]:
    return tuple(
        application_source(KanbanSource, card.task_id, (card.title, f"Board column: {card.column}\n{card.text}", tab.url), at) for card in board.tasks
    )


def teams_sources(teams: TeamsPage, tab: Tab, at: float) -> tuple[TeamsSource, ...]:
    # Title-only sidebar entries are locators, not evidence of an obligation.
    # The selected conversation's actual rendered messages can connect work.
    if not teams.current or not teams.messages:
        return ()
    text = "\n\n".join(f"{message.sender}: {message.text}" for message in teams.messages[-20:])[-6000:]
    conversation = application_source(TeamsSource, teams.current, (teams.title or "Teams conversation", text, tab.url), at)
    return (conversation, *message_sources(conversation, teams.messages[-20:]))


def mail_title(preview: str) -> str:
    lines = tuple(line.strip() for line in preview.splitlines() if line.strip() and not all("\ue000" <= char <= "\uf8ff" for char in line.strip()))
    return " · ".join(line for line in lines[:4] if line not in ("External", "Inbox"))[:240] or "Outlook conversation"


def outlook_sources(outlook: Mailbox, tab: Tab, at: float) -> tuple[OutlookSource, ...]:
    origin = urlsplit(tab.url)
    mailbox = f"https://{origin.hostname}/mail/"
    selected = outlook.selected
    sources = tuple(
        application_source(
            OutlookSource,
            mail.conversation_id,
            (selected.subject, selected.text, tab.url)
            if selected is not None and selected.conversation_id == mail.conversation_id and selected.text
            else (mail_title(mail.preview), mail.preview, mailbox),
            at,
        )
        for mail in outlook.conversations
    )
    # A selected pane is independent of pagination/virtualized list rows. Its
    # actual body remains evidence even when its row is not on this page.
    if selected is not None and selected.text and selected.conversation_id not in {mail.conversation_id for mail in outlook.conversations}:
        sources = (*sources, application_source(OutlookSource, selected.conversation_id, (selected.subject, selected.text, tab.url), at))
    conversation = next((source for source in sources if selected is not None and source.identity == selected.conversation_id), None)
    return (*sources, *message_sources(conversation, selected.messages)) if conversation is not None and selected is not None else sources


def message_sources[C: (TeamsSource, OutlookSource)](conversation: C, messages: Iterable[Piece]) -> tuple[C, ...]:
    """Each message is its own source, a part of its conversation."""

    def piece(message: Piece) -> C:
        seen = Observed.of((message.sender or conversation.title, message.text, conversation.url), conversation.title)
        return replace(
            conversation,
            id=source_id(conversation.kind, message.identity, parent_id=conversation.id),
            identity=message.identity,
            title=seen.title,
            excerpt=seen.excerpt,
            revision=seen.revision,
            parent_id=conversation.id,
        )

    return tuple(piece(message) for message in messages if message.identity and message.text)


@dataclass(frozen=True, slots=True)
class _Access:
    """Connection state and a bounded retry deadline. Regular samples keep
    checking app access; attachment failures wait one minute."""

    connected: bool = False
    failed: str | None = None
    retry_at: float = 0.0


@dataclass(frozen=True, slots=True)
class BrowserSources:
    browser: BrowserPort
    _state: Cell[_Access] = field(default_factory=lambda: Cell(_Access()), init=False, repr=False)

    def refresh(self) -> None:
        self._state.update(lambda state: replace(state, failed=None, retry_at=0.0))

    def tabs(self, cancel: threading.Event) -> Iterator[Tab]:
        """Check every page of open tabs, rejecting stopped or stalled reads."""
        if not self._state.get().connected:
            self.browser.connect(cancel)
            self._state.update(lambda state: replace(state, connected=True))
        offset = 0
        while not cancel.is_set():
            status = _STATUS.validate_json(self.browser.request(PageList(offset, limit=40), cancel).text)
            if status.mode == "stopped":
                raise BrowserError("The browser connection ended.")
            yield from (Tab(page.id, page.url) for page in status.tabs)
            following = status.next_offset
            if following is None:
                return
            if following <= offset:
                raise BrowserError("The browser tab listing did not advance.")
            offset = following

    def read(self, at: float, cancel: threading.Event) -> Observations:
        if cancel.is_set():
            return Observations((), ())
        access = self._state.get()
        if access.failed is not None and at < access.retry_at:
            return Observations((), (), (access.failed,))
        try:
            tabs = tuple(self.tabs(cancel))
        except BrowserError, OSError, ValueError:
            failed = "Browser evidence is unavailable. Open signed-in Teams, Outlook and Kanban tabs; access retries automatically each minute."
            self._state.set(_Access(connected=False, failed=failed, retry_at=at + ACCESS_RETRY_SECONDS))
            return Observations((), (), (failed,))
        self._state.update(lambda state: replace(state, failed=None))
        sources: tuple[ApplicationSource, ...] = ()
        coverage: tuple[str, ...] = ()
        problems: tuple[str, ...] = ()
        for tab in tabs:
            kind = kind_for(tab.url)
            if kind is None or cancel.is_set():
                continue
            try:
                match kind:
                    case SourceKind.KANBAN:
                        offset = 0
                        for _ in range(3):
                            if cancel.is_set():
                                break
                            result = self.browser.web_app(KANBAN_BOARD, BoardQuery(tab.id, offset=offset, limit=30), cancel)
                            sources = (*sources, *board_sources(result, tab, at))
                            if result.next_offset is None:
                                break
                            offset = result.next_offset
                    case SourceKind.TEAMS:
                        result_teams = self.browser.web_app(TEAMS_READ, TeamsQuery(tab.id), cancel)
                        sources = (*sources, *teams_sources(result_teams, tab, at))
                    case SourceKind.OUTLOOK:
                        offset = 0
                        for _ in range(3):
                            if cancel.is_set():
                                break
                            result_mail = self.browser.web_app(OUTLOOK_READ, MailList(tab.id, offset=offset, limit=20), cancel)
                            sources = (*sources, *outlook_sources(result_mail, tab, at))
                            if result_mail.next_offset is None:
                                break
                            offset = result_mail.next_offset
                    case _ as unreachable:
                        assert_never(unreachable)
                coverage = (*coverage, kind.value)
            except BrowserError, OSError, ValueError:
                problems = (*problems, f"{kind.value.capitalize()} evidence is currently unavailable; saved connections remain.")
        return Observations(sources, tuple(sorted(set(coverage))), problems)

    def close(self) -> None:
        self.browser.close()
