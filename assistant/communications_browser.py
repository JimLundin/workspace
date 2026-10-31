"""Teams web observations and exact-chat actions in one owned background tab."""

import contextlib
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import quote, urlsplit

from pydantic import TypeAdapter, ValidationError

from assistant.browser import Browser, BrowserResult
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
    UpdateKind,
)
from assistant.llm import Json
from assistant.web_apps import ACTIVITY_OBSERVE, ACTIVITY_PAGE, OBSERVE, TEAMS_READ, ActivityItem, ActivityPage, ChatIdentity, TeamsPage, decoded

HOSTS = frozenset({"teams.microsoft.com", "teams.cloud.microsoft"})
_JSON = TypeAdapter(Json)
_STATUS = TypeAdapter(BrowserStatus)
_TEXT = TypeAdapter(str)


def _literal(value: str) -> str:
    """A JavaScript string literal for an exact identity or text in a page script."""
    return _TEXT.dump_json(value).decode()


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


def update_kind(item: ActivityItem) -> UpdateKind:
    match item.kind:
        case "reaction":
            return UpdateKind.REACTION
        case "invitation":
            return UpdateKind.INVITATION
        case "mention":
            return UpdateKind.MENTION
        case "update":
            return UpdateKind.UPDATE


def activity_observation(page: ActivityPage, at: float) -> ActivityObservation:
    updates = tuple(
        Update(TeamsActivity(item.identity), item.title, item.text, "Teams", at, update_kind(item), source_time=activity_time(item, at))
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
    chats = tuple(Conversation(chat.identity, chat.title, chat.kind) for chat in page.conversations)
    messages = tuple(
        Message(page.current, post.identity, post.sender, post.text, post.created_at, at, post.reactions, own=post.own)
        for post in page.messages
        if page.current
    )
    return Observation(page.current, page.title, chats, messages, editor_ready=page.editor_ready)


class TeamsWeb:
    """Reuse one existing Teams tab; pause collection while the user views it."""

    __slots__ = ("browser", "opening", "target")

    def __init__(self, folder: Path, *, browser: BrowserPort | None = None) -> None:
        self.browser: BrowserPort = browser if browser is not None else Browser(folder, source=Product.EDGE)
        self.target = ""
        self.opening: dict[str, str] = {}

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
                    self.evaluate(
                        """(() => {
                      const button=document.querySelector('[data-tid="app-layout-area--nav"] button[aria-label="Activity"]');
                      if(!button)return false;button.click();return true;
                    })()""",
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
            opened = self.evaluate(
                """(() => {
              const wrap=document.getElementById("""
                + _literal(identity)
                + """);
              if(wrap?.getAttribute('data-tid')!=='activity-feed-list-item-wrap')return false;
              const row=wrap.querySelector('[data-tid="activity-feed-list-item"]');
              if(!row)return false;row.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));
              const button=row.querySelector('button[id^="activity-feed-item-context-menu-"]');
              if(!button)return false;button.click();return true;
            })()""",
                cancel,
                target=self.target,
            )
            if opened is not True or cancel.wait(0.2):
                return False
            label = self.evaluate("document.querySelector('[data-tid=\"toggleActivityRead\"]')?.innerText || ''", cancel, target=self.target)
            if label == "Mark as unread":
                self.dismiss_activity_menu(cancel)
                return True
            if label != "Mark as read":
                self.dismiss_activity_menu(cancel)
                return False
            self.evaluate(
                """(() => {
              const item=document.querySelector('[data-tid="toggleActivityRead"]');
              if(item?.innerText!=='Mark as read')return false;item.click();return true;
            })()""",
                cancel,
                target=self.target,
            )
            if cancel.wait(0.4):
                return False
            # Reopen that same menu. A disappeared item or unchanged label is not confirmation.
            self.evaluate(
                """(() => {
              document.getElementById("""
                + _literal(identity)
                + """)
                ?.querySelector('button[id^="activity-feed-item-context-menu-"]')?.click();return true;
            })()""",
                cancel,
                target=self.target,
            )
            if cancel.wait(0.2):
                return False
            verified = (
                self.evaluate("document.querySelector('[data-tid=\"toggleActivityRead\"]')?.innerText || ''", cancel, target=self.target)
                == "Mark as unread"
            )
            self.dismiss_activity_menu(cancel)
            return verified

    def dismiss_activity_menu(self, cancel: threading.Event) -> None:
        self.evaluate(
            """(() => {
          document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',code:'Escape',bubbles:true}));return true;
        })()""",
            cancel,
            target=self.target,
        )

    def open_activity(self, identity: str, cancel: threading.Event) -> None:
        self.activity(cancel)
        with self.browser.awake(self.target, cancel):
            result = self.evaluate(
                """(() => {
              const wrap=document.getElementById("""
                + _literal(identity)
                + """);
              if(wrap?.getAttribute('data-tid')!=='activity-feed-list-item-wrap')return false;
              const row=wrap.querySelector('[data-tid="activity-feed-list-item"]');
              if(!row)return false;row.click();return true;
            })()""",
                cancel,
                target=self.target,
            )
            if result is not True:
                raise BrowserError("That Teams activity is no longer rendered. Refresh before opening it.")
        self.browser.activate_page(self.target, cancel)

    def evaluated(self, expression: str, cancel: threading.Event, *, target: str = "") -> str:
        return self.browser.request(Evaluate(target or self.target, expression), cancel).text

    def evaluate(self, expression: str, cancel: threading.Event, *, target: str = "") -> Json:
        return _JSON.validate_json(self.evaluated(expression, cancel, target=target))

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
        self.target = existing.id
        return self.target

    def available(self, cancel: threading.Event) -> bool:
        match self.browser.owner:
            case Attached():
                return self.evaluate("document.visibilityState", cancel) == "hidden"
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
        return (
            self.evaluate(
                """(() => {
          if(document.querySelector('[role="treeitem"][data-fui-tree-item-value]'))return false;
          const chat=document.querySelector('[data-tid="app-layout-area--nav"] button[aria-label="Chat"]');
          if(!chat)return false;
          chat.click();return true;
        })()""",
                cancel,
                target=target,
            )
            is True
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
        pending = self.opening.get(target or self.target)
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
            self.opening.pop(target or self.target, None)
            return current
        encoded = _literal(identity)
        expression = f"""(() => {{
          const identity={encoded};
          const row=[...document.querySelectorAll('[role="treeitem"]')].find(e=>{{
            const match=(e.getAttribute('data-fui-tree-item-value')||'').match(/19:[^\\s/]+@(?:thread\\.v2|unq\\.gbl\\.spaces)/);
            return match?.[0]===identity;
          }});
          if(!row) return false;
          row.click(); return true;
        }})()"""
        result = self.evaluate(expression, cancel, target=target)
        if result is not True:
            opened = self.show_chats(cancel, target=target)
            if opened:
                deadline = time.monotonic() + 15
                while not cancel.wait(0.3):
                    current = self.read(cancel, target=target)
                    if current.current == identity and current.editor_ready:
                        self.opening.pop(target or self.target, None)
                        return current
                    result = self.evaluate(expression, cancel, target=target)
                    if result is True or len(current.conversations) > 1 or time.monotonic() >= deadline:
                        break
        if result is not True:
            return self._reopen(identity, cancel, target=target)
        deadline = time.monotonic() + 15
        while not cancel.wait(0.3):
            current = self.read(cancel, target=target)
            if current.current == identity and current.editor_ready:
                self.opening.pop(target or self.target, None)
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
        if self.opening.get(selected) != identity:
            self.opening[selected] = identity
            with contextlib.suppress(NavigationLoadingError):
                self.browser.request(Open(url, selected), cancel)
        deadline = time.monotonic() + 20
        while not cancel.wait(0.3):
            try:
                self.evaluate(
                    """(() => {
                  if(location.pathname!=='/dl/launcher/launcher.html')return false;
                  const web=document.querySelector('#openTeamsClientInBrowser');
                  if(!web || web.disabled)return false;
                  web.click();return true;
                })()""",
                    cancel,
                    target=target,
                )
                current = self.read(cancel, target=target)
                if current.current == identity and current.editor_ready:
                    self.opening.pop(selected, None)
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
        encoded, content = _literal(identity), _literal(text)
        prepared = self.evaluate(
            f"""(() => {{
          const send=document.querySelector('[data-tid="sendMessageCommands-send"]');
          const editor=document.querySelector('[data-tid="ckeditor"][contenteditable="true"]');
          if(send?.getAttribute('data-track-thread-id')!=={encoded} || !editor || editor.innerText.trim()) return false;
          editor.focus();
          return document.execCommand('insertText', false, {content});
        }})()""",
            cancel,
        )
        if prepared is not True:
            raise BrowserError("The Teams reply editor is unavailable or already contains a draft. Nothing was sent.")
        sent = self.evaluate(
            f"""(() => {{
          const send=document.querySelector('[data-tid="sendMessageCommands-send"]');
          const editor=document.querySelector('[data-tid="ckeditor"][contenteditable="true"]');
          if(send?.getAttribute('data-track-thread-id')!=={encoded} || !editor ||
             editor.innerText.replace(/\\u00a0/g,' ').trim()!=={content}.trim() || send.disabled ||
             send.getAttribute('aria-disabled')==='true') return false;
          send.click(); return true;
        }})()""",
            cancel,
        )
        if sent is not True:
            raise BrowserError("Teams did not accept the prepared reply. Inspect its editor before trying again.")
        deadline = time.monotonic() + 12
        while not cancel.wait(0.4):
            after = self.read(cancel)
            if after.current != identity:
                break
            candidates = tuple(message for message in after.messages if message.identity not in known and message.text.strip() == text.strip())
            cleared = self.evaluate('!document.querySelector(\'[data-tid="ckeditor"][contenteditable="true"]\')?.innerText.trim()', cancel)
            if len(candidates) == 1 and cleared is True:
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
            self.opening.clear()
