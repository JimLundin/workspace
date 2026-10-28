"""Teams web observations and exact-chat actions in one owned background tab."""

import contextlib
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import quote, urlsplit

from assistant.browser import Browser, BrowserResult
from assistant.browser_session import Attached, BrowserConnection, Owner, Product
from assistant.browser_values import BrowserError, InterruptedError, NavigationContextError, NavigationLoadingError
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

HOSTS = frozenset({"teams.microsoft.com", "teams.cloud.microsoft"})


class BrowserPort(Protocol):
    """The connection and page effects owned by a Teams collector's browser."""

    @property
    def connection(self) -> BrowserConnection | None: ...

    @property
    def owner(self) -> Owner: ...

    def connect(self, cancel: threading.Event, *, visible: bool = False) -> None: ...

    def request(self, operation: str, args: dict[str, Json], cancel: threading.Event) -> BrowserResult: ...

    def awake(self, target: str, cancel: threading.Event) -> contextlib.AbstractContextManager[None]: ...

    def activate_page(self, target: str, cancel: threading.Event) -> None: ...

    def close(self) -> None: ...


class ChatUnavailableError(BrowserError):
    __slots__ = ("reason",)

    def __init__(self, reason: Literal["missing", "loading"]) -> None:
        self.reason: Literal["missing", "loading"] = reason
        super().__init__("That Teams chat is not available yet. Other followed chats can keep updating.")


# Read only. Neither a conversation title nor a notification supplies a routing key.
OBSERVE = r"""(() => {
 const clean = value => (value || '').replace(/\u00a0/g, ' ').trim();
 const source = document.querySelector('[data-tid="sendMessageCommands-send"]');
 const current = source?.getAttribute('data-track-thread-id') || '';
 const selected = document.querySelector('[role="treeitem"][data-tabster*="LeftRailSelectedItem"]');
 const selectedKey = (selected?.getAttribute('data-fui-tree-item-value')||'').match(/19:[^\s/]+@(?:thread\.v2|unq\.gbl\.spaces)/)?.[0];
 const ready = !!document.querySelector('[data-tid="ckeditor"][contenteditable="true"]') && (!selectedKey || selectedKey===current);
 const seen = new Set();
 const conversations = [];
 for (const row of document.querySelectorAll('[role="treeitem"]')) {
   const value = row.getAttribute('data-fui-tree-item-value') || '';
   const match = value.match(/19:[^\s/]+@(?:thread\.v2|unq\.gbl\.spaces)/);
   if (!match || !['chat','muted-chat'].includes(row.getAttribute('data-item-type')) || seen.has(match[0])) continue;
   const title = clean(row.innerText).split('\n').filter(Boolean)[0] || 'Teams conversation';
   conversations.push({identity:match[0], title:title.slice(0,300), kind:match[0].includes('meeting_')?'meeting':'chat'});
   seen.add(match[0]);
 }
 const title = clean(document.querySelector('[data-tid="chat-title"]')?.innerText).slice(0,300);
 if (current && !seen.has(current)) conversations.push({
   identity:current,title:title||'Teams conversation',kind:current.includes('meeting_')?'meeting':'chat'
 });
 const messages = [];
 for (const row of document.querySelectorAll('[data-mid]')) {
   const identity = row.getAttribute('data-mid');
   const body = document.getElementById('content-'+identity);
   if (!identity || !body || !row.contains(body)) continue;
   const direct = clean(row.querySelector('[data-tid="message-author-name"]')?.innerText);
   const labels = (row.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id));
   const linked = labels.find(e=>e?.getAttribute('data-tid')==='message-author-name');
   const author = direct || clean(linked?.innerText) || 'Teams participant';
   const text = clean(body.innerText);
   if (!text) continue;
   const reactions = [...row.querySelectorAll('[data-tid*="reaction"]')]
     .map(e=>clean(e.getAttribute('aria-label')||e.innerText)).filter(Boolean);
   messages.push({identity,sender:author,text:text.slice(0,16000),
     created_at:/^\d{13}$/.test(identity)?Number(identity)/1000:0,reactions:[...new Set(reactions)].slice(0,20),
     own:row.getAttribute('data-tid')==='my-message' || !!row.querySelector('[data-tid="my-message"]')});
 }
 const result = {current,title,conversations:conversations.slice(0,150),messages:ready?messages.slice(-80):[],editor_ready:ready};
 while (JSON.stringify(result).length > 18500 && result.messages.length > 1) result.messages.shift();
 while (JSON.stringify(result).length > 18500 && result.conversations.length > 1) result.conversations.pop();
 if (JSON.stringify(result).length > 18500 && result.messages.length) {
   result.messages[0].text = result.messages[0].text.slice(0,4000)+'\n[Message continues in Teams]';
 }
 return result;
})()"""


ACTIVITY_OBSERVE = r"""(() => {
 const clean = value => (value || '').replace(/\u00a0/g,' ').trim();
 const items = [];
 for (const row of document.querySelectorAll('[data-tid="activity-feed-list-item"]')) {
   const wrap = row.closest('[data-tid="activity-feed-list-item-wrap"]');
   const identity = wrap?.id;
   if (!identity || !/^\d{1,32}$/.test(identity)) continue;
   const title = clean(row.querySelector('[data-tid="activity-feed-item-title"]')?.innerText);
   if (!title) continue;
   const reactionIcon = row.querySelector('[data-tid^="activity-feed-item-activity-icon-"]');
   const reaction = !!reactionIcon;
   const reactionLabel = clean(reactionIcon?.getAttribute('aria-label') || reactionIcon?.getAttribute('title') ||
     reactionIcon?.querySelector('img')?.getAttribute('alt') || '');
   const preview = clean(row.querySelector('[id^="activity-feed-item-message-preview-"]')?.innerText);
   const place = clean(row.querySelector('[id^="activity-feed-item-location-"]')?.innerText);
   const text = [reaction?reactionLabel:'',preview,place].filter(Boolean).join('\n').slice(0,4000) || title;
   const kind = /\b(invited|invitation|meeting invite)\b/i.test(title+' '+text)?'invitation':
     /\bmentioned\b/i.test(title)?'mention':reaction?'reaction':'update';
   const clock = row.querySelector('[id^="activity-feed-item-timestamp-"]');
   const raw = clock?.getAttribute('datetime') || clock?.querySelector('time[datetime]')?.getAttribute('datetime') ||
     clock?.getAttribute('title') || '';
   const parsed = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:/.test(raw) ? Date.parse(raw) : NaN;
   const date_hint = [...new Set([clean(raw),clean(clock?.innerText)].filter(Boolean))].join(' · ').slice(0,256);
   items.push({identity,title:title.slice(0,512),text,kind,created_at:Number.isFinite(parsed)?parsed/1000:0,date_hint});
 }
 const result = {ready:!!document.querySelector('[data-tid="activity-list-container"]'),items:items.slice(0,80)};
 while(JSON.stringify(result).length>18500 && result.items.length>1)result.items.pop();
 return result;
})()"""


@dataclass(frozen=True, slots=True)
class ActivityObservation:
    ready: bool = field(kw_only=True)
    items: tuple[Update, ...]


def activity_time(created: Json, hint: Json, observed_at: float) -> SourceTime:
    label = string(hint, limit=256).strip()
    match created:
        case bool():
            raise BrowserError('Teams returned an invalid activity date.')
        case None | 0:
            day = datetime.fromtimestamp(observed_at, UTC).astimezone().date()
            return SourceDateHint(label, day) if label else SourceDateStatus.UNKNOWN
        case int() | float() as stamp if 0 < stamp < 100_000_000_000:
            return SourceDate(float(stamp))
        case _:
            raise BrowserError('Teams returned an invalid activity date.')


def activity_observation(value: Json, at: float) -> ActivityObservation:
    data = obj(value)
    ready, rows = data.get("ready"), data.get("items")
    if not isinstance(ready, bool) or not isinstance(rows, list) or len(rows) > 80:
        raise BrowserError("Teams returned an invalid activity list.")
    kinds = {"reaction": UpdateKind.REACTION, "invitation": UpdateKind.INVITATION, "mention": UpdateKind.MENTION, "update": UpdateKind.UPDATE}
    updates: list[Update] = []
    for raw in rows:
        row = obj(raw)
        identity = string(row.get("identity"), limit=32, required=True)
        kind = string(row.get("kind"), limit=32)
        if not identity.isascii() or not identity.isdecimal() or kind not in kinds:
            raise BrowserError("Teams did not expose an exact activity identity.")
        updates.append(Update(TeamsActivity(identity), string(row.get("title"), limit=512, required=True),
                              string(row.get("text"), limit=4000, required=True), "Teams", at, kinds[kind],
                              source_time=activity_time(row.get('created_at'), row.get('date_hint', ''), at)))
    return ActivityObservation(tuple(updates), ready=ready)


def obj(value: Json) -> dict[str, Json]:
    if not isinstance(value, dict):
        raise BrowserError("Teams returned an invalid observation.")
    return value


def string(value: Json, *, limit: int = 16_000, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise BrowserError("Teams returned an invalid text field.")
    return value


def chat_identity(value: Json) -> str:
    identity = string(value, limit=512, required=True)
    if not identity.startswith("19:") or "@" not in identity or any(char.isspace() for char in identity):
        raise BrowserError("Teams did not expose an exact conversation identity.")
    return identity


@dataclass(frozen=True, slots=True)
class Observation:
    current: str
    title: str
    conversations: tuple[Conversation, ...]
    messages: tuple[Message, ...]
    editor_ready: bool


def observation(value: Json, at: float) -> Observation:
    data = obj(value)
    current = string(data.get("current", ""), limit=512)
    if current:
        current = chat_identity(current)
    raw_chats, raw_messages = data.get("conversations"), data.get("messages")
    if not isinstance(raw_chats, list) or not isinstance(raw_messages, list) or len(raw_chats) > 150 or len(raw_messages) > 80:
        raise BrowserError("Teams returned an invalid conversation list.")
    chats: list[Conversation] = []
    for raw in raw_chats:
        row = obj(raw)
        kind = row.get("kind")
        if kind not in ("chat", "meeting"):
            raise BrowserError("Teams returned an invalid conversation kind.")
        chats.append(Conversation(chat_identity(row.get("identity")), string(row.get("title"), limit=300, required=True),
                                  "meeting" if kind == "meeting" else "chat"))
    messages: list[Message] = []
    for raw in raw_messages:
        row = obj(raw)
        stamp, reactions = row.get("created_at"), row.get("reactions")
        if isinstance(stamp, bool) or not isinstance(stamp, (float, int)) or not 0 <= stamp < 100_000_000_000:
            raise BrowserError("Teams returned an invalid timestamp.")
        if not isinstance(reactions, list) or len(reactions) > 20:
            raise BrowserError("Teams returned invalid reactions.")
        if current:
            messages.append(Message(current, string(row.get("identity"), limit=512, required=True),
                                    string(row.get("sender"), limit=300, required=True), string(row.get("text"), required=True),
                                    float(stamp), at, tuple(string(item, limit=1000) for item in reactions), own=row.get("own") is True))
    ready = data.get("editor_ready")
    if not isinstance(ready, bool):
        raise BrowserError("Teams returned an invalid editor state.")
    return Observation(current, string(data.get("title", ""), limit=300), tuple(chats), tuple(messages), ready)


class TeamsWeb:
    """Reuse one existing Teams tab; pause collection while the user views it."""

    __slots__ = ("browser", "opening", "target")

    def __init__(self, folder: Path, *, browser: BrowserPort | None = None) -> None:
        self.browser: BrowserPort = browser if browser is not None else Browser(folder, source=Product.EDGE)
        self.target = ""
        self.opening: dict[str, str] = {}

    def activity(self, cancel: threading.Event) -> ActivityObservation:
        if not any(page.get("id") == self.target for page in self.pages(cancel)):
            self.connect(self.target, cancel)
        if not self.available(cancel):
            raise BrowserError("Teams activity collection is paused while its tab is visible.")
        with self.browser.awake(self.target, cancel):
            deadline = time.monotonic() + 15
            while not cancel.is_set():
                try:
                    found = activity_observation(self.evaluate(ACTIVITY_OBSERVE, cancel, target=self.target), time.time())
                    if found.ready:
                        return found
                    self.evaluate("""(() => {
                      const button=document.querySelector('[data-tid="app-layout-area--nav"] button[aria-label="Activity"]');
                      if(!button)return false;button.click();return true;
                    })()""", cancel, target=self.target)
                except NavigationContextError:
                    pass
                if time.monotonic() >= deadline or cancel.wait(.4):
                    break
        raise ChatUnavailableError("loading")

    def activity_read(self, identity: str, cancel: threading.Event) -> bool:
        """Use the exact activity menu, and verify its resulting read action label."""
        self.activity(cancel)
        with self.browser.awake(self.target, cancel):
            opened = self.evaluate("""(() => {
              const wrap=document.getElementById(""" + json.dumps(identity) + """);
              if(wrap?.getAttribute('data-tid')!=='activity-feed-list-item-wrap')return false;
              const row=wrap.querySelector('[data-tid="activity-feed-list-item"]');
              if(!row)return false;row.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));
              const button=row.querySelector('button[id^="activity-feed-item-context-menu-"]');
              if(!button)return false;button.click();return true;
            })()""", cancel, target=self.target)
            if opened is not True or cancel.wait(.2):
                return False
            label = self.evaluate("document.querySelector('[data-tid=\"toggleActivityRead\"]')?.innerText || ''", cancel,
                                  target=self.target)
            if label == "Mark as unread":
                self.dismiss_activity_menu(cancel)
                return True
            if label != "Mark as read":
                self.dismiss_activity_menu(cancel)
                return False
            self.evaluate("""(() => {
              const item=document.querySelector('[data-tid="toggleActivityRead"]');
              if(item?.innerText!=='Mark as read')return false;item.click();return true;
            })()""", cancel, target=self.target)
            if cancel.wait(.4):
                return False
            # Reopen that same menu. A disappeared item or unchanged label is not confirmation.
            self.evaluate("""(() => {
              document.getElementById(""" + json.dumps(identity) + """)
                ?.querySelector('button[id^="activity-feed-item-context-menu-"]')?.click();return true;
            })()""", cancel, target=self.target)
            if cancel.wait(.2):
                return False
            verified = self.evaluate("document.querySelector('[data-tid=\"toggleActivityRead\"]')?.innerText || ''", cancel,
                                      target=self.target) == "Mark as unread"
            self.dismiss_activity_menu(cancel)
            return verified

    def dismiss_activity_menu(self, cancel: threading.Event) -> None:
        self.evaluate("""(() => {
          document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',code:'Escape',bubbles:true}));return true;
        })()""", cancel, target=self.target)

    def open_activity(self, identity: str, cancel: threading.Event) -> None:
        self.activity(cancel)
        with self.browser.awake(self.target, cancel):
            result = self.evaluate("""(() => {
              const wrap=document.getElementById(""" + json.dumps(identity) + """);
              if(wrap?.getAttribute('data-tid')!=='activity-feed-list-item-wrap')return false;
              const row=wrap.querySelector('[data-tid="activity-feed-list-item"]');
              if(!row)return false;row.click();return true;
            })()""", cancel, target=self.target)
            if result is not True:
                raise BrowserError("That Teams activity is no longer rendered. Refresh before opening it.")
        self.browser.activate_page(self.target, cancel)

    def evaluate(self, expression: str, cancel: threading.Event, *, target: str = "") -> Json:
        return cast(Json, json.loads(self.browser.request("evaluate", {"target_id": target or self.target, "expression": expression}, cancel).text))

    def pages(self, cancel: threading.Event) -> tuple[dict[str, Json], ...]:
        rows: list[dict[str, Json]] = []
        offset = 0
        while not cancel.is_set():
            page = obj(cast(Json, json.loads(self.browser.request("tabs", {"limit": 40, "offset": offset}, cancel).text)))
            items = page.get("tabs")
            if not isinstance(items, list):
                raise BrowserError("Edge did not return its page list.")
            rows.extend(obj(item) for item in items)
            following = page.get("next_offset")
            if following is None:
                return tuple(rows)
            if isinstance(following, bool) or not isinstance(following, int) or not offset < following <= 20_000:
                raise BrowserError("Edge returned an invalid page offset.")
            offset = following
        return tuple(rows)

    def connect(self, saved_target: str, cancel: threading.Event) -> str:
        self.browser.connect(cancel)
        connection = self.browser.connection
        if connection is None:
            raise BrowserError("The Teams browser connection is unavailable.")
        for host in sorted(HOSTS):
            connection.call("Browser.setPermission", {"permission": {"name": "notifications"},
                                                     "setting": "denied", "origin": "https://" + host}, cancel)
        rows = self.pages(cancel)
        teams = tuple(page for page in rows if urlsplit(string(page.get("url"))).hostname in HOSTS)
        if not teams:
            raise BrowserError("Open Teams web in Edge and sign in, then connect here.")
        # CDP IDs can expire across browser restarts. Adopt an existing Teams
        # page instead of allocating another collector whenever that happens.
        existing = next((page for page in teams if page.get("id") == self.target), None)
        existing = existing or next((page for page in teams if page.get("id") == saved_target), teams[0])
        self.target = string(existing.get("id"), limit=512, required=True)
        return self.target

    def available(self, cancel: threading.Event) -> bool:
        return not isinstance(self.browser.owner, Attached) or self.evaluate("document.visibilityState", cancel) == "hidden"

    def read(self, cancel: threading.Event, *, target: str = "") -> Observation:
        for _ in range(3):
            try:
                return observation(self.evaluate(OBSERVE, cancel, target=target), time.time())
            except NavigationContextError:
                if cancel.wait(.15):
                    raise InterruptedError("Stopped while Teams was navigating.") from None
        raise ChatUnavailableError("loading")

    def show_chats(self, cancel: threading.Event, *, target: str = "") -> bool:
        return self.evaluate("""(() => {
          if(document.querySelector('[role="treeitem"][data-fui-tree-item-value]'))return false;
          const chat=document.querySelector('[data-tid="app-layout-area--nav"] button[aria-label="Chat"]');
          if(!chat)return false;
          chat.click();return true;
        })()""", cancel, target=target) is True

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
                if cancel.wait(.3):
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
            if cancel.wait(.3):
                raise BrowserError("Stopped while Teams was loading.")
            current = self.read(cancel, target=target)
        if current.current == identity and current.editor_ready:
            self.opening.pop(target or self.target, None)
            return current
        encoded = json.dumps(identity)
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
                while not cancel.wait(.3):
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
        while not cancel.wait(.3):
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
        page = next((page for page in self.pages(cancel) if page.get("id") == selected), None)
        if page is None:
            raise ChatUnavailableError("missing")
        address = urlsplit(string(page.get("url")))
        if address.hostname not in HOSTS:
            raise ChatUnavailableError("missing")
        url = f"https://teams.cloud.microsoft/l/chat/{quote(chat_identity(identity), safe=':@')}/conversations?webjoin=true"
        if self.opening.get(selected) != identity:
            self.opening[selected] = identity
            with contextlib.suppress(NavigationLoadingError):
                self.browser.request("open", {"url": url, "target_id": selected}, cancel)
        deadline = time.monotonic() + 20
        while not cancel.wait(.3):
            try:
                self.evaluate("""(() => {
                  if(location.pathname!=='/dl/launcher/launcher.html')return false;
                  const web=document.querySelector('#openTeamsClientInBrowser');
                  if(!web || web.disabled)return false;
                  web.click();return true;
                })()""", cancel, target=target)
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
        encoded, content = json.dumps(identity), json.dumps(text)
        prepared = self.evaluate(f"""(() => {{
          const send=document.querySelector('[data-tid="sendMessageCommands-send"]');
          const editor=document.querySelector('[data-tid="ckeditor"][contenteditable="true"]');
          if(send?.getAttribute('data-track-thread-id')!=={encoded} || !editor || editor.innerText.trim()) return false;
          editor.focus();
          return document.execCommand('insertText', false, {content});
        }})()""", cancel)
        if prepared is not True:
            raise BrowserError("The Teams reply editor is unavailable or already contains a draft. Nothing was sent.")
        sent = self.evaluate(f"""(() => {{
          const send=document.querySelector('[data-tid="sendMessageCommands-send"]');
          const editor=document.querySelector('[data-tid="ckeditor"][contenteditable="true"]');
          if(send?.getAttribute('data-track-thread-id')!=={encoded} || !editor ||
             editor.innerText.replace(/\\u00a0/g,' ').trim()!=={content}.trim() || send.disabled ||
             send.getAttribute('aria-disabled')==='true') return false;
          send.click(); return true;
        }})()""", cancel)
        if sent is not True:
            raise BrowserError("Teams did not accept the prepared reply. Inspect its editor before trying again.")
        deadline = time.monotonic() + 12
        while not cancel.wait(.4):
            after = self.read(cancel)
            if after.current != identity:
                break
            candidates = tuple(message for message in after.messages if message.identity not in known and message.text.strip() == text.strip())
            cleared = self.evaluate("!document.querySelector('[data-tid=\"ckeditor\"][contenteditable=\"true\"]')?.innerText.trim()", cancel)
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
