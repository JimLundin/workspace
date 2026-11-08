"""Teams web observations and exact-chat actions in one owned background tab."""

import contextlib
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final, Literal, Protocol
from urllib.parse import quote, urlsplit

from pydantic import Field, TypeAdapter, ValidationError

from assistant.browser import Browser, BrowserResult
from assistant.browser_dom import script
from assistant.browser_requests import BrowserRequest, Evaluate, Open
from assistant.browser_session import Attached, BrowserConnection, Owner, Product
from assistant.browser_values import (
    BrowserError,
    BrowserStatus,
    InterruptedError,
    NavigationContextError,
    NavigationLoadingError,
    PageList,
    PageRow,
)
from assistant.communications import (
    Conversation,
    Message,
    SourceDate,
    SourceDateHint,
    SourceDateStatus,
    SourceTime,
    TeamsActivity,
    Update,
)
from assistant.web_apps import ACTIVITY_OBSERVE, ACTIVITY_PAGE, OBSERVE, TEAMS_READ, ActivityItem, ActivityPage, ChatIdentity, TeamsPage, decoded
from cell import Cell

HOSTS = frozenset({"teams.microsoft.com", "teams.cloud.microsoft"})
_CONFIRMED = TypeAdapter(Annotated[bool, Field(strict=True)])
_LABEL = TypeAdapter(Annotated[str, Field(strict=True)])
_STATUS = TypeAdapter(BrowserStatus)
_TEXT = TypeAdapter(str)


def _called(function: str, *values: str) -> str:
    """A page script function applied to exact identities or text, passed as its arguments."""
    return "(" + function + ")(" + ", ".join(_TEXT.dump_json(value).decode() for value in values) + ")"


ACTIVITY_MENU: Final = script("communications_browser.activity_menu")
DISMISS_MENU: Final = script("communications_browser.dismiss_menu")
MARK_READ: Final = script("communications_browser.mark_read")
OPEN_ACTIVITY: Final = script("communications_browser.open_activity")
OPEN_IN_BROWSER: Final = script("communications_browser.open_in_browser")
PREPARE_REPLY: Final = script("communications_browser.prepare_reply")
REOPEN_MENU: Final = script("communications_browser.reopen_menu")
SELECT_CHAT: Final = script("communications_browser.select_chat")
SEND_REPLY: Final = script("communications_browser.send_reply")
SHOW_ACTIVITY: Final = script("communications_browser.show_activity")
SHOW_CHATS: Final = script("communications_browser.show_chats")


class BrowserPort(Protocol):
    """The connection and page effects owned by a Teams collector's browser."""

    @property
    def connection(self) -> BrowserConnection | None: ...

    @property
    def owner(self) -> Owner: ...

    def connect(self, cancel: threading.Event, *, visible: bool = False) -> None: ...

    def request(self, request: BrowserRequest, cancel: threading.Event) -> BrowserResult: ...

    def awake(self, target: str, cancel: threading.Event) -> contextlib.AbstractContextManager[None]: ...

    def activate_page(self, target: str, cancel: threading.Event) -> None: ...

    def close(self) -> None: ...


class ChatUnavailableError(BrowserError):
    __slots__ = ("reason",)

    def __init__(self, reason: Literal["missing", "loading"]) -> None:
        self.reason: Literal["missing", "loading"] = reason
        super().__init__("That Teams chat is not available yet. Other followed chats can keep updating.")


@dataclass(frozen=True, slots=True)
class ActivityObservation:
    ready: bool = field(kw_only=True)
    items: tuple[Update, ...]


def activity_time(item: ActivityItem, observed_at: float) -> SourceTime:
    """An exact activity time; otherwise its visible date hint on the day it was observed."""
    if item.created_at:
        return SourceDate(item.created_at)
    label = item.date_hint.strip()
    day = datetime.fromtimestamp(observed_at, UTC).astimezone().date()
    return SourceDateHint(label, day) if label else SourceDateStatus.UNKNOWN


def activity_observation(page: ActivityPage, at: float) -> ActivityObservation:
    updates = tuple(
        Update(TeamsActivity(item.identity, item.activity), item.title, item.text, "Teams", at, source_time=activity_time(item, at))
        for item in page.items
    )
    return ActivityObservation(updates, ready=page.ready)


_CHAT = TypeAdapter(ChatIdentity)


def chat_identity(value: str) -> str:
    try:
        return _CHAT.validate_python(value)
    except ValidationError as error:
        raise BrowserError("Teams did not expose an exact conversation identity.") from error


@dataclass(frozen=True, slots=True)
class Observation:
    current: str
    title: str
    conversations: tuple[Conversation, ...]
    messages: tuple[Message, ...]
    editor_ready: bool = field(kw_only=True)


def observation(page: TeamsPage, at: float) -> Observation:
    """The page's chats, and the selected chat's messages once it has an exact identity."""
    chats = tuple(Conversation(chat.identity, chat.title) for chat in page.conversations)
    messages = tuple(
        Message(page.current, post.identity, post.sender, post.text, post.created_at, at, post.reactions, own=post.own)
        for post in page.messages
        if page.current
    )
    return Observation(page.current, page.title, chats, messages, editor_ready=page.editor_ready)


@dataclass(frozen=True, slots=True)
class _Teams:
    target: str = ""
    """The collector's Teams tab."""
    opening: frozendict[str, str] = frozendict()
    """The chat each tab is navigating to, until it is open."""


@dataclass(frozen=True, slots=True)
class TeamsWeb:
    """Reuse one existing Teams tab; pause collection while the user views it."""

    browser: BrowserPort
    _state: Cell[_Teams] = field(default_factory=lambda: Cell(_Teams()), init=False, repr=False)

    @classmethod
    def at(cls, folder: Path, *, browser: BrowserPort | None = None) -> TeamsWeb:
        return cls(browser if browser is not None else Browser.at(folder, source=Product.EDGE))

    @property
    def target(self) -> str:
        return self._state.get().target

    @property
    def opening(self) -> frozendict[str, str]:
        return self._state.get().opening

    def adopt(self, target: str) -> None:
        """Collect from this tab from now on."""
        self._state.update(lambda state: replace(state, target=target))

    def navigating(self, target: str, identity: str) -> None:
        """Record that `target` is navigating to the chat `identity`, until it opens."""
        self._state.update(lambda state: replace(state, opening=frozendict({**state.opening, target: identity})))

    def _forget(self, target: str) -> None:
        self._state.update(lambda state: replace(state, opening=frozendict((key, value) for key, value in state.opening.items() if key != target)))

    def activity(self, cancel: threading.Event) -> ActivityObservation:
        if not any(page.id == self.target for page in self.pages(cancel)):
            self.connect(self.target, cancel)
        if not self.available(cancel):
            raise BrowserError("Teams activity collection is paused while its tab is visible.")
        with self.browser.awake(self.target, cancel):
            deadline = time.monotonic() + 15
            while not cancel.is_set():
                try:
                    page = decoded(ACTIVITY_PAGE, self.evaluated(ACTIVITY_OBSERVE, cancel, target=self.target))
                    found = activity_observation(page, time.time())
                    if found.ready:
                        return found
                    self.confirmed(
                        SHOW_ACTIVITY,
                        cancel,
                        target=self.target,
                    )
                except NavigationContextError:
                    pass
                if time.monotonic() >= deadline or cancel.wait(0.4):
                    break
        raise ChatUnavailableError("loading")

    def activity_read(self, identity: str, cancel: threading.Event) -> bool:
        """Use the exact activity menu, and verify its resulting read action label."""
        self.activity(cancel)
        with self.browser.awake(self.target, cancel):
            opened = self.confirmed(
                _called(ACTIVITY_MENU, identity),
                cancel,
                target=self.target,
            )
            if not opened or cancel.wait(0.2):
                return False
            label = self.label("document.querySelector('[data-tid=\"toggleActivityRead\"]')?.innerText || ''", cancel, target=self.target)
            if label == "Mark as unread":
                self.dismiss_activity_menu(cancel)
                return True
            if label != "Mark as read":
                self.dismiss_activity_menu(cancel)
                return False
            self.confirmed(
                MARK_READ,
                cancel,
                target=self.target,
            )
            if cancel.wait(0.4):
                return False
            # Reopen that same menu. A disappeared item or unchanged label is not confirmation.
            self.confirmed(
                _called(REOPEN_MENU, identity),
                cancel,
                target=self.target,
            )
            if cancel.wait(0.2):
                return False
            verified = (
                self.label("document.querySelector('[data-tid=\"toggleActivityRead\"]')?.innerText || ''", cancel, target=self.target)
                == "Mark as unread"
            )
            self.dismiss_activity_menu(cancel)
            return verified

    def dismiss_activity_menu(self, cancel: threading.Event) -> None:
        self.confirmed(
            DISMISS_MENU,
            cancel,
            target=self.target,
        )

    def open_activity(self, identity: str, cancel: threading.Event) -> None:
        self.activity(cancel)
        with self.browser.awake(self.target, cancel):
            result = self.confirmed(
                _called(OPEN_ACTIVITY, identity),
                cancel,
                target=self.target,
            )
            if not result:
                raise BrowserError("That Teams activity is no longer rendered. Refresh before opening it.")
        self.browser.activate_page(self.target, cancel)

    def evaluated(self, expression: str, cancel: threading.Event, *, target: str = "") -> str:
        return self.browser.request(Evaluate(target or self.target, expression), cancel).text

    def confirmed(self, expression: str, cancel: threading.Event, *, target: str = "") -> bool:
        """Run a script that reports whether the page accepted its step."""
        return decoded(_CONFIRMED, self.evaluated(expression, cancel, target=target))

    def label(self, expression: str, cancel: threading.Event, *, target: str = "") -> str:
        """Read one piece of visible text, such as a menu item's label."""
        return decoded(_LABEL, self.evaluated(expression, cancel, target=target))

    def pages(self, cancel: threading.Event) -> tuple[PageRow, ...]:
        rows: tuple[PageRow, ...] = ()
        offset = 0
        while not cancel.is_set():
            status = decoded(_STATUS, self.browser.request(PageList(offset, 40), cancel).text)
            rows = (*rows, *status.tabs)
            match status.next_offset:
                case None:
                    return rows
                case following if offset < following <= 20_000:
                    offset = following
                case _:
                    raise BrowserError("Edge returned an invalid page offset.")
        return rows

    def connect(self, saved_target: str, cancel: threading.Event) -> str:
        self.browser.connect(cancel)
        connection = self.browser.connection
        if connection is None:
            raise BrowserError("The Teams browser connection is unavailable.")
        for host in sorted(HOSTS):
            connection.call(
                "Browser.setPermission", {"permission": {"name": "notifications"}, "setting": "denied", "origin": "https://" + host}, cancel
            )
        rows = self.pages(cancel)
        teams = tuple(page for page in rows if urlsplit(page.url).hostname in HOSTS)
        if not teams:
            raise BrowserError("Open Teams web in Edge and sign in, then connect here.")
        # CDP IDs can expire across browser restarts. Adopt an existing Teams
        # page instead of allocating another collector whenever that happens.
        existing = next((page for page in teams if page.id == self.target), None)
        existing = existing or next((page for page in teams if page.id == saved_target), teams[0])
        self._state.update(lambda state: replace(state, target=existing.id))
        return self.target

    def available(self, cancel: threading.Event) -> bool:
        match self.browser.owner:
            case Attached():
                return self.label("document.visibilityState", cancel) == "hidden"
            case _:
                return True

    def read(self, cancel: threading.Event, *, target: str = "") -> Observation:
        for _ in range(3):
            try:
                page = decoded(TEAMS_READ.result, self.evaluated(OBSERVE, cancel, target=target))
                return observation(page, time.time())
            except NavigationContextError:
                if cancel.wait(0.15):
                    raise InterruptedError("Stopped while Teams was navigating.") from None
        raise ChatUnavailableError("loading")

    def show_chats(self, cancel: threading.Event, *, target: str = "") -> bool:
        return self.confirmed(
            SHOW_CHATS,
            cancel,
            target=target,
        )

    def discover(self, cancel: threading.Event) -> Observation:
        """Restore Chat before the first collection, including an empty Activity pane."""
        if not self.available(cancel):
            raise BrowserError("Switch away from Workspace's collector tab before collecting.")
        with self.browser.awake(self.target, cancel):
            deadline = time.monotonic() + 15
            current = self.read(cancel)
            opened = False
            while not current.current and not current.conversations and time.monotonic() < deadline:
                if not opened:
                    opened = self.show_chats(cancel)
                if cancel.wait(0.3):
                    raise BrowserError("Stopped while Teams was loading.")
                current = self.read(cancel)
            return current

    def select(self, identity: str, cancel: threading.Event, *, target: str = "") -> Observation:
        if not target and not self.available(cancel):
            raise BrowserError("Switch away from Workspace's collector tab before collecting or sending.")
        with self.browser.awake(target or self.target, cancel):
            return self._select(identity, cancel, target=target)

    def _select(self, identity: str, cancel: threading.Event, *, target: str = "") -> Observation:
        current = self.read(cancel, target=target)
        pending = self._state.get().opening.get(target or self.target)
        if pending is not None and not current.editor_ready:
            current = self._reopen(pending, cancel, target=target)
        deadline = time.monotonic() + 15
        opened = False
        while not current.current and not current.conversations and time.monotonic() < deadline:
            if not opened:
                opened = self.show_chats(cancel, target=target)
            if cancel.wait(0.3):
                raise BrowserError("Stopped while Teams was loading.")
            current = self.read(cancel, target=target)
        if current.current == identity and current.editor_ready:
            self._forget(target or self.target)
            return current
        expression = _called(SELECT_CHAT, identity)
        result = self.confirmed(expression, cancel, target=target)
        if not result:
            opened = self.show_chats(cancel, target=target)
            if opened:
                deadline = time.monotonic() + 15
                while not cancel.wait(0.3):
                    current = self.read(cancel, target=target)
                    if current.current == identity and current.editor_ready:
                        self._forget(target or self.target)
                        return current
                    result = self.confirmed(expression, cancel, target=target)
                    if result or len(current.conversations) > 1 or time.monotonic() >= deadline:
                        break
        if not result:
            return self._reopen(identity, cancel, target=target)
        deadline = time.monotonic() + 15
        while not cancel.wait(0.3):
            current = self.read(cancel, target=target)
            if current.current == identity and current.editor_ready:
                self._forget(target or self.target)
                return current
            if time.monotonic() >= deadline:
                break
        raise ChatUnavailableError("loading")

    def _reopen(self, identity: str, cancel: threading.Event, *, target: str = "") -> Observation:
        """Open an exact chat even when Teams' sidebar hasn't rendered its row."""
        selected = target or self.target
        page = next((page for page in self.pages(cancel) if page.id == selected), None)
        if page is None:
            raise ChatUnavailableError("missing")
        address = urlsplit(page.url)
        if address.hostname not in HOSTS:
            raise ChatUnavailableError("missing")
        url = f"https://teams.cloud.microsoft/l/chat/{quote(chat_identity(identity), safe=':@')}/conversations?webjoin=true"
        if self._state.get().opening.get(selected) != identity:
            self.navigating(selected, identity)
            with contextlib.suppress(NavigationLoadingError):
                self.browser.request(Open(url, selected), cancel)
        deadline = time.monotonic() + 20
        while not cancel.wait(0.3):
            try:
                self.confirmed(
                    OPEN_IN_BROWSER,
                    cancel,
                    target=target,
                )
                current = self.read(cancel, target=target)
                if current.current == identity and current.editor_ready:
                    self._forget(selected)
                    return current
            except NavigationContextError:
                pass  # A redirect invalidated this read; the next observation uses its new context.
            if time.monotonic() >= deadline:
                break
        raise ChatUnavailableError("loading")

    def send(self, identity: str, text: str, cancel: threading.Event) -> tuple[Message, ...]:
        if not self.available(cancel):
            raise BrowserError("Switch away from Workspace's collector tab before sending.")
        with self.browser.awake(self.target, cancel):
            return self._send(identity, text, cancel)

    def _send(self, identity: str, text: str, cancel: threading.Event) -> tuple[Message, ...]:
        before = self._select(identity, cancel)
        known = {message.identity for message in before.messages}
        prepared = self.confirmed(
            _called(PREPARE_REPLY, identity, text),
            cancel,
        )
        if not prepared:
            raise BrowserError("The Teams reply editor is unavailable or already contains a draft. Nothing was sent.")
        sent = self.confirmed(
            _called(SEND_REPLY, identity, text),
            cancel,
        )
        if not sent:
            raise BrowserError("Teams did not accept the prepared reply. Inspect its editor before trying again.")
        deadline = time.monotonic() + 12
        while not cancel.wait(0.4):
            after = self.read(cancel)
            if after.current != identity:
                break
            candidates = tuple(message for message in after.messages if message.identity not in known and message.text.strip() == text.strip())
            cleared = self.confirmed('!document.querySelector(\'[data-tid="ckeditor"][contenteditable="true"]\')?.innerText.trim()', cancel)
            if len(candidates) == 1 and cleared:
                return candidates
            if time.monotonic() >= deadline:
                break
        return ()

    def open(self, identity: str, cancel: threading.Event) -> None:
        self.connect(self.target, cancel)
        self.select(identity, cancel, target=self.target)
        self.browser.activate_page(self.target, cancel)

    def close(self) -> None:
        try:
            self.browser.close()
        finally:
            self._state.update(lambda state: replace(state, opening=frozendict()))
