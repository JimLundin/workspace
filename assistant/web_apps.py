"""Teams, Outlook and AIP Kanban operations in an opted-in browser's signed-in pages.

Each web-app operation is declared once: its typed query, page script,
application and typed result. The browser owns CDP, page wakeup and
cancellation. These adapters own exact selection and DOM contracts observed in
the applications. No credentials leave the page. Kanban's filters remain in
effect; missing cards are never guessed.
"""

import contextlib
import threading
from dataclasses import KW_ONLY, dataclass, field
from enum import Enum, auto
from typing import Annotated, Final, Literal, Protocol, assert_never

from pydantic import Field, TypeAdapter, ValidationError

from assistant.browser_documents import Download, Downloaded
from assistant.browser_dom import script
from assistant.browser_requests import BrowserRequest, Evaluate
from assistant.browser_values import BrowserError
from assistant.communications import Activity
from contracts.members import every_member
from contracts.work_documents import LocalDocument
lazy from assistant.browser import BrowserResult

KANBAN_ORIGIN = "https://dev-team-kanban.fcg.palantirfoundry.com"
OUTLOOK_ORIGINS = ("https://outlook.office.com", "https://outlook.office365.com", "https://outlook.cloud.microsoft")
TEAMS_ORIGINS = ("https://teams.cloud.microsoft", "https://teams.microsoft.com")
type Identity = Annotated[str, Field(min_length=1, max_length=500)]
type Text = Annotated[str, Field(max_length=10000)]

_ORIGINS = TypeAdapter(tuple[str, ...])


class App(Enum):
    """The application whose pages an operation's script expects."""

    KANBAN = auto()
    TEAMS = auto()
    OUTLOOK = auto()


class Browser(Protocol):
    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult: ...
    def awake(self, target: str, cancel: threading.Event) -> contextlib.AbstractContextManager[None]: ...
    def download_document(self, request: Download, cancel: threading.Event) -> Downloaded: ...


class Located(Protocol):
    """A query names the exact browser page it reads or changes."""

    @property
    def target_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class Origins:
    kanban: str = KANBAN_ORIGIN
    teams: tuple[str, ...] = TEAMS_ORIGINS
    outlook: tuple[str, ...] = OUTLOOK_ORIGINS

    def of(self, app: App) -> tuple[str, ...]:
        match app:
            case App.KANBAN:
                return (self.kanban,)
            case App.TEAMS:
                return self.teams
            case App.OUTLOOK:
                return self.outlook
            case _:
                assert_never(app)


@dataclass(frozen=True, slots=True)
class BoardQuery:
    target_id: Identity
    query: Annotated[str, Field(max_length=500)] = ""
    offset: Annotated[int, Field(strict=True, ge=0, le=20000)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=30)] = 20


@dataclass(frozen=True, slots=True)
class TaskQuery:
    target_id: Identity
    task_id: Identity


@dataclass(frozen=True, slots=True)
class TaskEdit:
    target_id: Identity
    task_id: Identity
    field: Literal["title", "description", "dueDate", "estimate", "labels", "acceptanceCriteria"]
    expected_value: Text
    value: Text


@dataclass(frozen=True, slots=True)
class TaskMove:
    target_id: Identity
    task_id: Identity
    expected_column: Annotated[str, Field(min_length=1, max_length=100)]
    column: Annotated[str, Field(min_length=1, max_length=100)]


@dataclass(frozen=True, slots=True)
class TaskComment:
    target_id: Identity
    task_id: Identity
    text: Annotated[str, Field(min_length=1, max_length=4000)]


@dataclass(frozen=True, slots=True)
class TeamsQuery:
    target_id: Identity


@dataclass(frozen=True, slots=True)
class ChatQuery:
    target_id: Identity
    chat_id: Identity


@dataclass(frozen=True, slots=True)
class ChatDraft:
    target_id: Identity
    chat_id: Identity
    text: Annotated[str, Field(min_length=1, max_length=10000)]


@dataclass(frozen=True, slots=True)
class MailList:
    target_id: Identity
    offset: Annotated[int, Field(strict=True, ge=0, le=20000)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=30)] = 20


@dataclass(frozen=True, slots=True)
class MailSearch:
    target_id: Identity
    query: Annotated[str, Field(min_length=1, max_length=500)]


@dataclass(frozen=True, slots=True)
class MailQuery:
    target_id: Identity
    conversation_id: Identity


@dataclass(frozen=True, slots=True)
class MailDraft:
    target_id: Identity
    conversation_id: Identity
    text: Annotated[str, Field(min_length=1, max_length=10000)]


@dataclass(frozen=True, slots=True)
class MailDocument:
    target_id: Identity
    conversation_id: Identity
    attachment_id: Identity


@dataclass(frozen=True, slots=True)
class MailDownload:
    target_id: Identity
    conversation_id: Identity
    attachment_id: Identity
    expected_url: Annotated[str, Field(min_length=1, max_length=4000)]
    destination: LocalDocument


# Results are the scripts' external contracts. Literal fields are the page's
# own confirmation; a script that cannot confirm its effect throws instead.


@dataclass(frozen=True, slots=True)
class Card:
    task_id: str
    title: str
    column: str
    text: str


@dataclass(frozen=True, slots=True)
class Board:
    tasks: tuple[Card, ...]
    total: int
    columns: tuple[str, ...]
    filters: tuple[str, ...]
    search: str
    scope: str
    next_offset: int | None


@dataclass(frozen=True, slots=True)
class TaskDetail:
    task_id: str
    fields: frozendict[str, str]
    text: str


@dataclass(frozen=True, slots=True)
class TaskEdited:
    task_id: str
    field: str
    value: str
    _: KW_ONLY  # The `field` attribute shadows dataclasses.field in this class body.
    verified: Literal[True]


@dataclass(frozen=True, slots=True)
class TaskMoved:
    task_id: str
    column: str
    verified: Literal[True] = field(kw_only=True)
    changed: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class CommentPosted:
    task_id: str
    text: str
    posted: Literal[True] = field(kw_only=True)


# Teams' exact conversation identity, which routes every chat operation.
type ChatIdentity = Annotated[str, Field(max_length=512, pattern=r"^19:\S*@\S*$")]


@dataclass(frozen=True, slots=True)
class TeamsChat:
    identity: ChatIdentity
    title: Annotated[str, Field(max_length=300, pattern=r"\S")]


@dataclass(frozen=True, slots=True)
class TeamsPost:
    identity: Annotated[str, Field(max_length=512, pattern=r"\S")]
    sender: Annotated[str, Field(max_length=300, pattern=r"\S")]
    text: Annotated[str, Field(max_length=16_000, pattern=r"\S")]
    created_at: Annotated[float, Field(strict=True, ge=0, lt=100_000_000_000)]
    reactions: Annotated[tuple[Annotated[str, Field(max_length=1000)], ...], Field(max_length=20)]
    own: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class TeamsPage:
    """The rendered chat list and, once its editor is ready, the selected chat's messages."""

    current: Annotated[str, Field(max_length=512, pattern=r"^(19:\S*@\S*)?$")]
    title: Annotated[str, Field(max_length=300)]
    conversations: Annotated[tuple[TeamsChat, ...], Field(max_length=150)]
    messages: Annotated[tuple[TeamsPost, ...], Field(max_length=80)]
    editor_ready: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class ActivityItem:
    identity: Annotated[str, Field(max_length=32, pattern=r"^[0-9]+$")]
    title: Annotated[str, Field(max_length=512, pattern=r"\S")]
    text: Annotated[str, Field(max_length=4000, pattern=r"\S")]
    activity: Activity
    created_at: Annotated[float, Field(strict=True, ge=0, lt=100_000_000_000)]
    """Zero when Teams shows only a relative or partial date."""
    date_hint: Annotated[str, Field(max_length=256)] = ""


@dataclass(frozen=True, slots=True)
class ActivityPage:
    """The rendered Activity feed; `ready` once its list container exists."""

    items: Annotated[tuple[ActivityItem, ...], Field(max_length=80)]
    ready: bool = field(kw_only=True)


ACTIVITY_PAGE = TypeAdapter(ActivityPage)


@dataclass(frozen=True, slots=True)
class ChatOpened:
    chat_id: str
    opened: Literal[True] = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class ChatDrafted:
    chat_id: str
    text: str
    drafted: Literal[True] = field(kw_only=True)
    sent: Literal[False] = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class MailRow:
    conversation_id: str
    preview: str
    label: str
    selected: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class MailMessage:
    """One individually identified message rendered in the selected conversation."""

    identity: str
    sender: str
    text: str


@dataclass(frozen=True, slots=True)
class SelectedMail:
    conversation_id: str
    subject: str
    messages: tuple[MailMessage, ...]
    text: str
    headers: str
    truncated: bool = field(kw_only=True)
    loading: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Mailbox:
    """Rendered conversation rows and the selected reading pane."""

    conversations: tuple[MailRow, ...]
    rendered_total: int
    selected: SelectedMail | None
    search: str
    scope: str
    next_offset: int | None
    editor_open: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class MailOpened:
    conversation_id: str
    mail: SelectedMail | None
    opened: Literal[True] = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class MailDrafted:
    conversation_id: str
    text: str
    subject: str
    recipients: tuple[str, ...]
    status: str
    drafted: Literal[True] = field(kw_only=True)
    sent: Literal[False] = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class Attachment:
    attachment_id: str | None
    label: str
    message_id: str | None
    url: str | None
    ambiguous: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class DocumentLink:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class MailDocuments:
    conversation_id: str
    attachments: tuple[Attachment, ...]
    links: tuple[DocumentLink, ...]
    coverage: str
    truncated: bool = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class PreviewOpened:
    conversation_id: str
    attachment_id: str
    url: str | None
    preview: str
    status: str
    opened: Literal[True] = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class LinkFound:
    """A direct document link, which is opened or collected instead of clicked."""

    conversation_id: str
    attachment_id: str
    url: str | None
    status: str
    opened: Literal[False] = field(kw_only=True)


type DocumentOpened = PreviewOpened | LinkFound


@dataclass(frozen=True, slots=True)
class AttachmentLink:
    conversation_id: str
    attachment_id: str
    url: str


@dataclass(frozen=True, slots=True)
class CollectedDocument:
    conversation_id: str
    attachment_id: str
    path: str
    sha256: str
    size: int
    content_type: str


# Read only. Neither a conversation title nor a notification supplies a routing key.
OBSERVE: Final = script("web_apps.observe")


# Read only. Each activity row is identified by its numeric list-item id.
ACTIVITY_OBSERVE: Final = script("web_apps.activity_observe")


# UI predicates and event dispatch run in the browser's isolated world. They
# never invoke React internals or replace the application's handlers.
_DOM: Final = script("web_apps.dom")

_KANBAN: Final = script("web_apps.kanban")

_BOARD: Final = script("web_apps.board")

_READ: Final = script("web_apps.read")

_EDIT: Final = script("web_apps.edit")

_MOVE: Final = script("web_apps.move")

_COMMENT: Final = script("web_apps.comment")

_CHAT_OPEN: Final = script("web_apps.chat_open")

_CHAT_DRAFT: Final = script("web_apps.chat_draft")


_MAIL: Final = script("web_apps.mail")

_MAIL_DOCUMENT_OPEN: Final = script("web_apps.mail_document_open")

_MAIL_DOCUMENT_DOWNLOAD: Final = script("web_apps.mail_document_download")

_MAIL_SEARCH: Final = script("web_apps.mail_search")

_MAIL_OPEN: Final = script("web_apps.mail_open")

_MAIL_DRAFT: Final = script("web_apps.mail_draft")


def decoded[R](result: TypeAdapter[R], text: str) -> R:
    """Validate a complete bounded result; browser truncation or malformed output remains a failure."""
    try:
        return result.validate_json(text)
    except ValidationError as error:
        raise BrowserError("The application returned an unexpected result. Inspect it before claiming it succeeded.") from error


class WebAppOperation[Q: Located, R](Protocol):
    """What callers need of an operation: its query and result contracts, and how it is performed."""

    @property
    def query(self) -> TypeAdapter[Q]: ...
    @property
    def result(self) -> TypeAdapter[R]: ...
    def perform(self, apps: WebApps, query: Q, cancel: threading.Event) -> R: ...


@dataclass(frozen=True, slots=True)
class PageOperation[Q: Located, R]:
    """A script run in one application's page, which returns its confirmed result."""

    app: App
    script: str
    query: TypeAdapter[Q]
    result: TypeAdapter[R]

    def perform(self, apps: WebApps, query: Q, cancel: threading.Event) -> R:
        return decoded(self.result, apps.evaluate(self, query, cancel))


_COLLECTED = TypeAdapter(CollectedDocument)


@dataclass(frozen=True, slots=True)
class DocumentCollection:
    """Confirm an exact attachment's rendered link, then collect it using the browser's cookies."""

    link: PageOperation[MailDownload, AttachmentLink]

    @property
    def query(self) -> TypeAdapter[MailDownload]:
        return self.link.query

    @property
    def result(self) -> TypeAdapter[CollectedDocument]:
        return _COLLECTED

    def perform(self, apps: WebApps, query: MailDownload, cancel: threading.Event) -> CollectedDocument:
        link = self.link.perform(apps, query, cancel)
        if (link.url, link.attachment_id, link.conversation_id) != (query.expected_url, query.attachment_id, query.conversation_id):
            raise BrowserError("The browser did not confirm the exact attachment link.")
        saved = apps.browser.download_document(Download(query.target_id, link.url, query.destination), cancel)
        return CollectedDocument(query.conversation_id, query.attachment_id, saved.path, saved.sha256, saved.size, saved.content_type)


KANBAN_BOARD: Final = PageOperation(App.KANBAN, _BOARD, TypeAdapter(BoardQuery), TypeAdapter(Board))
KANBAN_READ_TASK: Final = PageOperation(App.KANBAN, _READ, TypeAdapter(TaskQuery), TypeAdapter(TaskDetail))
KANBAN_UPDATE_TASK: Final = PageOperation(App.KANBAN, _EDIT, TypeAdapter(TaskEdit), TypeAdapter(TaskEdited))
KANBAN_MOVE_TASK: Final = PageOperation(App.KANBAN, _MOVE, TypeAdapter(TaskMove), TypeAdapter(TaskMoved))
KANBAN_COMMENT: Final = PageOperation(App.KANBAN, _COMMENT, TypeAdapter(TaskComment), TypeAdapter(CommentPosted))
TEAMS_READ: Final = PageOperation(App.TEAMS, "return " + OBSERVE + ";", TypeAdapter(TeamsQuery), TypeAdapter(TeamsPage))
TEAMS_OPEN_CHAT: Final = PageOperation(App.TEAMS, _CHAT_OPEN, TypeAdapter(ChatQuery), TypeAdapter(ChatOpened))
TEAMS_DRAFT_REPLY: Final = PageOperation(App.TEAMS, _CHAT_DRAFT, TypeAdapter(ChatDraft), TypeAdapter(ChatDrafted))
OUTLOOK_READ: Final = PageOperation(App.OUTLOOK, "return mailRead();", TypeAdapter(MailList), TypeAdapter(Mailbox))
OUTLOOK_SEARCH: Final = PageOperation(App.OUTLOOK, _MAIL_SEARCH, TypeAdapter(MailSearch), TypeAdapter(Mailbox))
OUTLOOK_OPEN_MAIL: Final = PageOperation(App.OUTLOOK, _MAIL_OPEN, TypeAdapter(MailQuery), TypeAdapter(MailOpened))
OUTLOOK_DRAFT_REPLY: Final = PageOperation(App.OUTLOOK, _MAIL_DRAFT, TypeAdapter(MailDraft), TypeAdapter(MailDrafted))
OUTLOOK_DOCUMENTS: Final = PageOperation(App.OUTLOOK, "return mailDocuments();", TypeAdapter(MailQuery), TypeAdapter(MailDocuments))
OUTLOOK_OPEN_DOCUMENT: Final = PageOperation(App.OUTLOOK, _MAIL_DOCUMENT_OPEN, TypeAdapter(MailDocument), TypeAdapter[DocumentOpened](DocumentOpened))
OUTLOOK_DOWNLOAD_DOCUMENT: Final = DocumentCollection(
    PageOperation(App.OUTLOOK, _MAIL_DOCUMENT_DOWNLOAD, TypeAdapter(MailDownload), TypeAdapter(AttachmentLink))
)


_HELPERS: Final = every_member(App, {App.KANBAN: _KANBAN, App.OUTLOOK: _MAIL, App.TEAMS: ""})
"""The page helpers each application's scripts call."""


@dataclass(frozen=True, slots=True)
class WebApps:
    browser: Browser
    origins: Origins = field(default_factory=Origins)

    def run[Q: Located, R](self, operation: WebAppOperation[Q, R], query: Q, cancel: threading.Event) -> R:
        if cancel.is_set():
            raise BrowserError("Stopped before interacting with the application.")
        return operation.perform(self, query, cancel)

    def evaluate[Q: Located, R](self, operation: PageOperation[Q, R], query: Q, cancel: threading.Event) -> str:
        helpers = _HELPERS[operation.app]
        allowed = _ORIGINS.dump_json(self.origins.of(operation.app)).decode()
        options = operation.query.dump_json(query).decode()
        expression = "(async (options, allowed) => {" + _DOM + helpers + operation.script + "})(" + options + ", " + allowed + ")"
        with self.browser.awake(query.target_id, cancel):
            return self.browser.request(Evaluate(query.target_id, expression), cancel).text
