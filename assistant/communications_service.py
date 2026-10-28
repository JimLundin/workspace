"""A cancellable Teams collector; browser, encrypted drafts and effects stay off Qt."""

import json
import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

from .browser_values import BrowserError
from .communications import (
    MAX_FOLLOWED,
    MAX_HANDLED,
    Acknowledgement,
    Command,
    Connect,
    Delivery,
    Disconnect,
    Feed,
    Follow,
    Handle,
    HandleNotice,
    NotificationFilters,
    OpenChat,
    OpenUpdate,
    Refresh,
    Reopen,
    Reply,
    ResolveAttempt,
    SaveDraft,
    Seen,
    Send,
    Status,
    TeamsActivity,
    UnavailableChat,
    WindowsNotice,
    WindowsObserved,
    acknowledge,
    handle,
    notice_update,
    notices_observed,
    observed,
    reopen,
    reply_changed,
    update_fingerprint,
    updates_observed,
)
from .communications_browser import ChatUnavailableError, TeamsWeb, obj, string
from .llm import Json
from .system_notices import NoticeKey
from .system_notices import Observed as Notices


class SavedState:
    """Save the user's drafts/settings/outgoing attempts; incoming bodies stay in memory."""

    __slots__ = ("path", "protect", "unprotect")

    def __init__(
        self, path: Path, *, protect: Callable[[bytes], bytes], unprotect: Callable[[bytes], bytes],
    ) -> None:
        self.path, self.protect, self.unprotect = path, protect, unprotect

    def read(self) -> dict[str, Json]:
        if not self.path.exists():
            return {}
        return obj(cast(Json, json.loads(self.unprotect(self.path.read_bytes()))))

    def write(self, state: dict[str, Json]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        candidate = self.path.with_suffix(".tmp")
        try:
            candidate.write_bytes(self.protect(json.dumps(state, ensure_ascii=False).encode("utf-8")))
            candidate.replace(self.path)
        finally:
            candidate.unlink(missing_ok=True)


def windows_store(path: Path) -> SavedState:
    from winapi.protection import protect, unprotect  # noqa: PLC0415

    return SavedState(path, protect=protect, unprotect=unprotect)


class Communications:
    __slots__ = (
        "commands", "cursor", "dirty", "dismiss_notice", "draft_lock", "drafts", "enabled", "feed", "next_activity", "next_poll",
        "pending_drafts", "pending_notices", "publish", "saved_target",
        "started", "stop", "store", "thread", "web",
    )

    def __init__(
        self, web: TeamsWeb, store: SavedState, publish: Callable[[Feed, dict[str, str]], None],
        dismiss_notice: Callable[[NoticeKey], None] = lambda _: None,
    ) -> None:
        self.web, self.store, self.publish = web, store, publish
        self.dismiss_notice = dismiss_notice
        self.feed = Feed()
        self.drafts: dict[str, str] = {}
        self.pending_drafts: dict[str, str] = {}
        self.pending_notices: Notices | None = None
        self.draft_lock = threading.Lock()
        self.enabled = self.dirty = self.started = False
        self.saved_target = ""
        self.cursor = 0
        self.next_poll = 0.0
        self.next_activity = 0.0
        self.stop = threading.Event()
        self.commands: queue.Queue[Command] = queue.Queue(maxsize=256)
        self.thread = threading.Thread(target=self.run, name="Teams conversation", daemon=True)

    def start(self) -> None:
        if not self.started:
            self.started = True
            self.thread.start()

    def submit(self, command: Command) -> bool:
        if self.stop.is_set():
            return False
        if isinstance(command, WindowsObserved):
            with self.draft_lock:
                self.pending_notices = command.observation
            return True
        if isinstance(command, SaveDraft):
            if len(command.text) > 32_000 or len(command.conversation) > 512:
                return False
            with self.draft_lock:
                self.pending_drafts[command.conversation] = command.text
            return True
        try:
            self.commands.put_nowait(command)
            return True
        except queue.Full:
            return False

    def drain_drafts(self) -> None:
        with self.draft_lock:
            pending, self.pending_drafts = self.pending_drafts, {}
            notices, self.pending_notices = self.pending_notices, None
        if pending:
            self.drafts.update(pending)
            self.dirty = True
        if notices is not None:
            before = self.feed
            self.feed = notices_observed(self.feed, notices)
            if self.feed != before:
                self.changed()

    def changed(self) -> None:
        self.publish(self.feed, dict(self.drafts))

    def load(self) -> None:
        state = self.store.read()
        self.enabled = state.get("enabled") is True
        self.saved_target = string(state.get("target", ""), limit=512)
        watches = state.get("followed", [])
        drafts = state.get("drafts", {})
        if not isinstance(watches, list) or len(watches) > MAX_FOLLOWED or not isinstance(drafts, dict) or len(drafts) > 150:
            raise BrowserError("Saved Teams preferences are invalid.")
        self.feed = replace(self.feed, followed=tuple(string(item, limit=512) for item in watches))
        muted = state.get("muted_apps", [])
        if not isinstance(muted, list) or len(muted) > 256:
            raise BrowserError("Saved notification filters are invalid.")
        self.feed = replace(self.feed, muted_apps=tuple(string(app, limit=512, required=True) for app in muted))
        self.drafts = {key: string(value, limit=32_000) for key, value in drafts.items()}
        replies = state.get("replies", [])
        if not isinstance(replies, list) or len(replies) > 50:
            raise BrowserError("Saved Teams reply evidence is invalid.")
        recovered: list[Reply] = []
        for value in replies:
            row = obj(value)
            stamp = row.get("created_at")
            if isinstance(stamp, bool) or not isinstance(stamp, (float, int)):
                raise BrowserError("Saved Teams reply timestamp is invalid.")
            delivery = Delivery[string(row.get("delivery"), limit=32)]
            if delivery in (Delivery.QUEUED, Delivery.SENDING):
                delivery = Delivery.UNKNOWN
            recovered.append(Reply(string(row.get("identity"), limit=512), string(row.get("conversation"), limit=512),
                                   string(row.get("title"), limit=300), string(row.get("text"), limit=32_000), float(stamp),
                                   delivery, string(row.get("detail", ""), limit=1000)))
        self.feed = replace(self.feed, replies=tuple(recovered))
        handled = state.get("handled", [])
        if not isinstance(handled, list) or len(handled) > MAX_HANDLED:
            raise BrowserError("Saved inbox handling state is invalid.")
        marks: list[Acknowledgement] = []
        for raw in handled:
            row = obj(raw)
            first, second = string(row.get("source"), limit=512, required=True), string(row.get("identity"), limit=512, required=True)
            digest = string(row.get("fingerprint"), limit=64, required=True)
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise BrowserError("Saved inbox revision is invalid.")
            marks.append(Acknowledgement((first, second), digest))
        self.feed = replace(self.feed, handled=tuple(marks))

    def save(self) -> None:
        replies: list[Json] = [{"identity": item.identity, "conversation": item.conversation, "title": item.title, "text": item.text,
                               "created_at": item.created_at, "delivery": item.delivery.name, "detail": item.detail}
                              for item in self.feed.replies]
        self.store.write({"enabled": self.enabled, "target": self.saved_target, "followed": list(self.feed.followed),
                          "muted_apps": list(self.feed.muted_apps),
                          "drafts": dict(self.drafts), "replies": replies,
                          "handled": [{"source": mark.key[0], "identity": mark.key[1], "fingerprint": mark.fingerprint}
                                      for mark in self.feed.handled]})
        self.dirty = False

    def connect(self) -> None:
        self.feed = replace(self.feed, status=Status.CONNECTING, detail="Waiting for Edge connection access…")
        self.changed()
        self.saved_target = self.web.connect(self.saved_target, self.stop)
        self.enabled = True
        self.save()
        self.next_poll = 0
        self.next_activity = 0

    def collect_activity(self) -> None:
        previous_target = self.web.target
        try:
            found = self.web.activity(self.stop)
        except Exception:
            self.feed = replace(self.feed, activity_detail="Teams Activity is loading or its tab is visible; chat updates continue.")
        else:
            self.feed = updates_observed(self.feed, found.items)
            self.feed = replace(self.feed, activity_detail=f"Teams Activity · {len(found.items)} rendered updates")
        if self.web.target != previous_target:
            self.saved_target = self.web.target
            self.dirty = True
        self.changed()

    def collect(self) -> None:
        if not self.web.available(self.stop):
            self.feed = replace(self.feed, status=Status.STALE,
                                detail="Teams collection paused while its browser tab is visible. Switch away to resume.")
            self.changed()
            return
        try:
            found = self.web.read(self.stop)
        except ChatUnavailableError:
            self.feed = replace(self.feed, status=Status.STALE, detail="Teams is loading. Updates will resume automatically.")
            self.changed()
            return
        if not found.current and not self.feed.followed:
            found = self.web.discover(self.stop)
        if not found.current and not found.conversations and not self.feed.followed:
            self.feed = replace(self.feed, status=Status.STALE, detail="Finish signing in or loading Teams in the Workspace browser tab.")
            self.changed()
            return
        known = {chat.identity: chat for chat in self.feed.conversations}
        known.update({chat.identity: chat for chat in found.conversations})
        followed = self.feed.followed
        if not followed:
            candidates = (found.current, *(chat.identity for chat in found.conversations if chat.kind == "chat"))
            selected: list[str] = []
            for candidate in candidates:
                if candidate and candidate not in selected:
                    selected.append(candidate)
            followed = tuple(selected[:4])
            self.dirty = True
        self.feed = replace(self.feed, conversations=tuple(known.values())[:150], followed=followed)
        self.feed = observed(self.feed, found.messages, time.time())
        unavailable = {item.conversation: item for item in self.feed.unavailable if item.conversation in followed}
        if followed:
            identity = followed[self.cursor % len(followed)]
            self.cursor += 1
            try:
                found = self.web.select(identity, self.stop)
            except ChatUnavailableError as error:
                unavailable[identity] = UnavailableChat(identity, error.reason)
            else:
                unavailable.pop(identity, None)
                known.update({chat.identity: chat for chat in found.conversations})
                self.feed = observed(replace(self.feed, conversations=tuple(known.values())[:150]), found.messages, time.time())
        detail = f"Teams · following {len(followed)} chats"
        if unavailable:
            detail += f" · {len(unavailable)} chat{'s' if len(unavailable) != 1 else ''} unavailable; retrying automatically"
        self.feed = replace(self.feed, unavailable=tuple(unavailable.values()),
                            status=Status.STALE if followed and len(unavailable) == len(followed) else Status.CONNECTED, detail=detail)
        self.changed()

    def send(self, command: Send) -> None:
        if any(reply.identity == command.identity for reply in self.feed.replies):
            return
        chat = self.feed.conversation(command.conversation)
        if chat is None or not command.text.strip() or len(command.text) > 32_000:
            return
        reply = Reply(command.identity, chat.identity, chat.title, command.text, time.time())
        if self.feed.status is not Status.CONNECTED or chat.identity not in self.feed.followed:
            reply = replace(reply, delivery=Delivery.FAILED, detail="Reconnect and follow this chat before sending. Your text is retained below.")
        elif any(item.conversation == chat.identity and item.delivery is Delivery.UNKNOWN for item in self.feed.replies):
            reply = replace(reply, delivery=Delivery.FAILED,
                            detail="An earlier send has an uncertain outcome. Inspect it in Teams before sending again.")
        else:
            reply = replace(reply, delivery=Delivery.SENDING)
        self.feed = reply_changed(self.feed, reply)
        self.drafts.setdefault(chat.identity, command.text)
        self.drain_drafts()
        self.save()  # Intent and text survive a crash before touching the page.
        self.changed()
        if reply.delivery is Delivery.FAILED:
            return
        try:
            messages = self.web.send(chat.identity, command.text, self.stop)
            self.drain_drafts()
            if messages:
                self.feed = observed(self.feed, tuple(replace(message, own=True) for message in messages), time.time())
                self.feed = handle(self.feed, command.handling)
                reply = replace(reply, delivery=Delivery.OBSERVED, detail="Reply observed in the selected Teams chat.")
                if self.drafts.get(chat.identity) == command.text:
                    self.drafts[chat.identity] = ""
            else:
                reply = replace(reply, delivery=Delivery.UNKNOWN,
                                detail="Teams did not provide reply readback. Inspect the chat; nothing will be resent automatically.")
        except Exception:
            # A failure after entering the effect may already have posted. Never expose page content in diagnostics.
            reply = replace(reply, delivery=Delivery.UNKNOWN, detail="The send outcome is uncertain. Your text is saved; inspect this chat in Teams.")
        self.feed = reply_changed(self.feed, reply)
        self.save()
        self.changed()

    def handled(self, command: Handle) -> None:
        before = self.feed
        self.feed = handle(self.feed, command.marks)
        if self.feed == before:
            return
        try:
            self.save()
        except Exception:
            self.feed = before
            self.changed()
            raise
        self.changed()
        accepted = {mark.key for mark in command.marks if mark in self.feed.handled and mark not in before.handled}
        for update in self.feed.updates:
            if update.key not in accepted:
                continue
            match update.source:
                case WindowsNotice(key, _):
                    self.dismiss_notice(key)
                case TeamsActivity(identity):
                    try:
                        confirmed = self.web.activity_read(identity, self.stop)
                    except Exception:
                        confirmed = False
                    self.feed = replace(self.feed, activity_detail=("Handled here · Teams read state confirmed." if confirmed else
                                        "Handled here · Teams read state could not be confirmed. Open Teams to check it."))
                    self.changed()

    def command(self, command: Command) -> None:  # noqa: PLR0915  # Dispatch typed commands in one owner.
        match command:
            case Connect():
                self.connect()
            case Disconnect():
                self.enabled = False
                self.web.close()
                self.feed = replace(self.feed, status=Status.DISCONNECTED,
                                    detail="Teams disconnected. Saved drafts and observed messages remain available.")
                self.save()
                self.changed()
            case Refresh():
                self.next_poll = 0
                self.next_activity = 0
            case Follow(identities):
                known = {chat.identity for chat in self.feed.conversations}
                followed: list[str] = []
                for identity in identities:
                    if identity in known and identity not in followed:
                        followed.append(identity)
                self.feed = replace(self.feed, followed=tuple(followed[:MAX_FOLLOWED]))
                self.save()
                self.next_poll = 0
                self.changed()
            case NotificationFilters(apps):
                if len(apps) <= 256 and all(app and len(app) <= 512 for app in apps):
                    self.feed = replace(self.feed, muted_apps=tuple(dict.fromkeys(apps, True)))
                    self.save()
                    self.changed()
            case Seen(key):
                self.feed = acknowledge(self.feed, key)
                self.changed()
            case Handle():
                self.handled(command)
            case HandleNotice(notice):
                captured = notice_update(notice)
                if not any(item.key == captured.key for item in self.feed.updates):
                    self.feed = updates_observed(self.feed, (captured,))
                self.handled(Handle((Acknowledgement(captured.key, update_fingerprint(captured)),)))
            case Reopen(key):
                self.feed = reopen(self.feed, key)
                self.save()
                self.changed()
            case WindowsObserved(notices):
                self.feed = notices_observed(self.feed, notices)
                self.changed()
            case OpenUpdate(key):
                update = next((item for item in self.feed.updates if item.key == key), None)
                if update is not None:
                    match update.source:
                        case TeamsActivity(identity):
                            self.web.open_activity(identity, self.stop)
                        case WindowsNotice(_, app_id):
                            if app_id:
                                os.startfile("shell:AppsFolder\\" + app_id)
            case SaveDraft(identity, text):
                if len(text) <= 32_000 and len(identity) <= 512:
                    self.drafts[identity] = text
                    self.dirty = True
            case Send():
                self.send(command)
            case OpenChat(identity):
                self.web.open(identity, self.stop)
            case ResolveAttempt(identity):
                reply = next((item for item in self.feed.replies if item.identity == identity), None)
                if reply is not None and reply.delivery is Delivery.UNKNOWN:
                    self.feed = reply_changed(self.feed, replace(reply, delivery=Delivery.REVIEWED,
                                              detail="You checked this attempt in Teams. Delivery remains unverified; future replies are enabled."))
                    self.save()
                    self.changed()

    def run(self) -> None:
        try:
            try:
                self.load()
            except Exception:
                self.enabled = False
                self.feed = replace(self.feed, detail="Saved Teams preferences could not be read. Reconnect to start a new session.")
            self.changed()
            if self.enabled:
                try:
                    self.connect()
                except Exception:
                    self.feed = replace(self.feed, status=Status.STALE, detail="Teams needs a fresh Edge connection. Use Connect Teams to retry.")
                    self.changed()
            while not self.stop.is_set():
                self.drain_drafts()
                try:
                    command = self.commands.get(timeout=.4)
                    self.command(command)
                except queue.Empty:
                    pass
                except Exception:
                    self.feed = replace(self.feed, status=Status.STALE,
                                        detail="Teams is unavailable. Your drafts are retained; reconnect or refresh to retry.")
                    self.changed()
                if self.enabled and self.web.target and time.monotonic() >= self.next_poll:
                    try:
                        self.collect()
                    except Exception:
                        self.feed = replace(self.feed, status=Status.STALE,
                                            detail="Teams updates are incomplete. Refresh or reconnect; saved content is still available.")
                        self.changed()
                    self.next_poll = time.monotonic() + 4
                if self.enabled and self.web.target and time.monotonic() >= self.next_activity:
                    self.collect_activity()
                    self.next_activity = time.monotonic() + 20
                if self.dirty:
                    try:
                        self.save()
                    except OSError:
                        self.feed = replace(self.feed, detail="Teams drafts could not be saved. Keep this session open and retry.")
                        self.changed()
        finally:
            self.drain_drafts()
            if self.dirty:
                try:
                    self.save()
                except OSError:
                    self.feed = replace(self.feed, detail="The latest Teams draft could not be saved.")
                    self.changed()
            self.web.close()

    def close(self) -> None:
        self.stop.set()
        if self.started:
            self.thread.join(timeout=5)
