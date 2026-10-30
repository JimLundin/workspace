"""Read-only work evidence from opted-in, signed-in browser pages.

The reader never changes a board filter, searches an inbox, opens a message or
selects a Teams chat. Coverage is the rendered pages; absent rows retain their
saved evidence. CDP targets belong to this observation and are never persisted.
"""

import threading
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Protocol, assert_never
from urllib.parse import urlsplit

from pydantic import TypeAdapter

from assistant.browser import BrowserResult
from assistant.browser_values import BrowserError
from assistant.llm import Json
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
from automation.personal_work import SourceKind, WorkSource, source_id, source_revision


class BrowserPort(Protocol):
    def connect(self, cancel: threading.Event) -> None: ...
    def request(self, operation: str, args: dict[str, Json], cancel: threading.Event) -> BrowserResult: ...
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
class Tabs:
    tabs: tuple[Tab, ...]


@dataclass(frozen=True, slots=True)
class Observations:
    sources: tuple[WorkSource, ...]
    coverage: tuple[str, ...]
    problems: tuple[str, ...] = ()


_TABS = TypeAdapter(Tabs)


def kind_for(url: str) -> SourceKind | None:
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


def observed_source(kind: SourceKind, identity: str, details: tuple[str, str, str], at: float) -> WorkSource:
    # A source's routing identity, observed content and timestamp are distinct
    # parts of one observation. Content changes determine its revision; time does not.
    title, excerpt, url = details
    title, excerpt = title.strip()[:240] or kind.value.capitalize(), excerpt[:6000]
    return WorkSource(source_id(kind, identity), kind, identity, title, excerpt, url, source_revision(title, excerpt, url), at)


def board_sources(board: Board, tab: Tab, at: float) -> tuple[WorkSource, ...]:
    return tuple(
        observed_source(SourceKind.KANBAN, card.task_id, (card.title, f"Board column: {card.column}\n{card.text}", tab.url), at)
        for card in board.tasks
    )


def teams_sources(teams: TeamsPage, tab: Tab, at: float) -> tuple[WorkSource, ...]:
    # Title-only sidebar entries are locators, not evidence of an obligation.
    # The selected conversation's actual rendered messages can connect work.
    if not teams.current or not teams.messages:
        return ()
    text = "\n\n".join(f"{message.sender}: {message.text}" for message in teams.messages[-20:])[-6000:]
    conversation = observed_source(SourceKind.TEAMS, teams.current, (teams.title or "Teams conversation", text, tab.url), at)
    return (conversation, *message_sources(conversation, teams.messages[-20:]))


def mail_title(preview: str) -> str:
    lines = tuple(line.strip() for line in preview.splitlines() if line.strip() and not all("\ue000" <= char <= "\uf8ff" for char in line.strip()))
    return " · ".join(line for line in lines[:4] if line not in ("External", "Inbox"))[:240] or "Outlook conversation"


def outlook_sources(outlook: Mailbox, tab: Tab, at: float) -> tuple[WorkSource, ...]:
    origin = urlsplit(tab.url)
    mailbox = f"https://{origin.hostname}/mail/"
    selected = outlook.selected
    sources = tuple(
        observed_source(
            SourceKind.OUTLOOK,
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
        sources = (*sources, observed_source(SourceKind.OUTLOOK, selected.conversation_id, (selected.subject, selected.text, tab.url), at))
    conversation = next((source for source in sources if selected is not None and source.identity == selected.conversation_id), None)
    return (*sources, *message_sources(conversation, selected.messages)) if conversation is not None and selected is not None else sources


def message_sources(conversation: WorkSource, messages: Iterable[Piece]) -> tuple[WorkSource, ...]:
    return tuple(
        replace(
            observed_source(
                conversation.kind,
                message.identity,
                (message.sender or conversation.title, message.text, conversation.url),
                conversation.observed_at,
            ),
            id=source_id(conversation.kind, message.identity, parent_id=conversation.id),
            parent_id=conversation.id,
        )
        for message in messages
        if message.identity and message.text
    )


class BrowserSources:
    __slots__ = ("browser", "connected", "failed")

    def __init__(self, browser: BrowserPort) -> None:
        self.browser = browser
        # This reader owns the connection lifecycle. A denied/unavailable
        # attachment is retried only when the user explicitly refreshes My work.
        self.connected = False
        self.failed: str | None = None

    def refresh(self) -> None:
        self.failed = None

    def read(self, at: float, cancel: threading.Event) -> Observations:
        if self.failed is not None:
            return Observations((), (), (self.failed,))
        try:
            if not self.connected:
                self.browser.connect(cancel)
                self.connected = True
            tabs = _TABS.validate_json(self.browser.request("tabs", {"limit": 40}, cancel).text).tabs
        except BrowserError, OSError, ValueError:
            self.failed = "Browser evidence is unavailable. Open signed-in Teams, Outlook and Kanban tabs, then Refresh My work."
            return Observations((), (), (self.failed,))
        sources: tuple[WorkSource, ...] = ()
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
                    case SourceKind.DOCUMENT | SourceKind.WEB_PAGE:
                        continue
                    case _ as unreachable:
                        assert_never(unreachable)
                coverage = (*coverage, kind.value)
            except BrowserError, OSError, ValueError:
                problems = (*problems, f"{kind.value.capitalize()} evidence is currently unavailable; saved connections remain.")
        return Observations(sources, tuple(sorted(set(coverage))), problems)

    def close(self) -> None:
        self.browser.close()
