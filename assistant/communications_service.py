"""A cancellable Teams collector; browser, encrypted drafts and effects stay off Qt."""

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from assistant.communications import (
    MAX_FOLLOWED,
    Acknowledgement,
    Command,
    Connect,
    Delivery,
    Disconnect,
    Feed,
    Follow,
    Handle,
    Message,
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
    acknowledge,
    handle,
    observed,
    reopen,
    reply_changed,
    updates_observed,
)
from assistant.communications_browser import ActivityObservation, ChatUnavailableError, Observation
from assistant.communications_state import CommunicationsState, StoredAcknowledgement, StoredReply
from assistant.state_store import SavedState


class Teams(Protocol):
    """Observed Teams work and exact-source actions consumed by the collector."""

    @property
    def target(self) -> str: ...

    def connect(self, saved_target: str, cancel: threading.Event) -> str: ...

    def available(self, cancel: threading.Event) -> bool: ...

    def read(self, cancel: threading.Event, *, target: str = "") -> Observation: ...

    def discover(self, cancel: threading.Event) -> Observation: ...

    def select(self, identity: str, cancel: threading.Event, *, target: str = "") -> Observation: ...

    def activity(self, cancel: threading.Event) -> ActivityObservation: ...

    def activity_read(self, identity: str, cancel: threading.Event) -> bool: ...

    def open_activity(self, identity: str, cancel: threading.Event) -> None: ...

    def send(self, identity: str, text: str, cancel: threading.Event) -> tuple[Message, ...]: ...

    def open(self, identity: str, cancel: threading.Event) -> None: ...

    def close(self) -> None: ...


class Communications:
    __slots__ = (
        "commands",
        "cursor",
        "dirty",
        "draft_lock",
        "drafts",
        "enabled",
        "feed",
        "next_activity",
        "next_poll",
        "pending_drafts",
        "publish",
        "saved_target",
        "started",
        "stop",
        "store",
        "thread",
        "web",
    )

    def __init__(self, web: Teams, store: SavedState[CommunicationsState], publish: Callable[[Feed], None]) -> None:
        self.web, self.store, self.publish = web, store, publish
        self.feed = Feed()
        self.drafts: dict[str, str] = {}
        self.pending_drafts: dict[str, str] = {}
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
        if pending:
            self.drafts.update(pending)
            self.dirty = True

    def changed(self) -> None:
        self.publish(self.feed)

    def load(self) -> None:
        state = self.store.read()
        self.enabled = state.enabled
        self.saved_target = state.target
        self.drafts = dict(state.drafts)
        self.feed = replace(
            self.feed,
            followed=state.followed,
            replies=tuple(
                Reply(
                    row.identity,
                    row.conversation,
                    row.title,
                    row.text,
                    row.created_at,
                    Delivery.UNKNOWN if row.delivery in (Delivery.QUEUED, Delivery.SENDING) else row.delivery,
                    row.detail,
                )
                for row in state.replies
            ),
            handled=tuple(Acknowledgement((mark.source, mark.identity), mark.fingerprint) for mark in state.handled),
        )

    def save(self) -> None:
        self.store.write(
            CommunicationsState(
                target=self.saved_target,
                followed=self.feed.followed,
                drafts=tuple(self.drafts.items()),
                replies=tuple(
                    StoredReply(item.identity, item.conversation, item.title, item.text, item.created_at, item.delivery, item.detail)
                    for item in self.feed.replies
                ),
                handled=tuple(StoredAcknowledgement(mark.key[0], mark.key[1], mark.fingerprint) for mark in self.feed.handled),
                enabled=self.enabled,
            )
        )
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
            self.feed = replace(
                self.feed, status=Status.STALE, detail="Teams collection paused while its browser tab is visible. Switch away to resume."
            )
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
        self.feed = replace(
            self.feed,
            unavailable=tuple(unavailable.values()),
            status=Status.STALE if followed and len(unavailable) == len(followed) else Status.CONNECTED,
            detail=detail,
        )
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
            reply = replace(
                reply, delivery=Delivery.FAILED, detail="An earlier send has an uncertain outcome. Inspect it in Teams before sending again."
            )
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
                reply = replace(
                    reply,
                    delivery=Delivery.UNKNOWN,
                    detail="Teams did not provide reply readback. Inspect the chat; nothing will be resent automatically.",
                )
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
                case TeamsActivity(identity):
                    try:
                        confirmed = self.web.activity_read(identity, self.stop)
                    except Exception:
                        confirmed = False
                    self.feed = replace(
                        self.feed,
                        activity_detail=(
                            "Handled here · Teams read state confirmed."
                            if confirmed
                            else "Handled here · Teams read state could not be confirmed. Open Teams to check it."
                        ),
                    )
                    self.changed()
                case WindowsNotice():
                    pass  # notification_sources owns Windows notices.

    def command(self, command: Command) -> None:
        match command:
            case Connect():
                self.connect()
            case Disconnect():
                self.disconnect()
            case Refresh():
                self.next_poll = 0
                self.next_activity = 0
            case Follow(identities):
                self.follow(identities)
            case Seen(key):
                self.feed = acknowledge(self.feed, key)
                self.changed()
            case Handle():
                self.handled(command)
            case Reopen(key):
                self.feed = reopen(self.feed, key)
                self.save()
                self.changed()
            case OpenUpdate(key):
                self.open_update(key)
            case SaveDraft(identity, text):
                if len(text) <= 32_000 and len(identity) <= 512:
                    self.drafts[identity] = text
                    self.dirty = True
            case Send():
                self.send(command)
            case OpenChat(identity):
                self.web.open(identity, self.stop)
            case ResolveAttempt(identity):
                self.resolve_attempt(identity)

    def open_update(self, key: tuple[str, str]) -> None:
        update = next((item for item in self.feed.updates if item.key == key), None)
        if update is not None:
            match update.source:
                case TeamsActivity(identity):
                    self.web.open_activity(identity, self.stop)
                case WindowsNotice():
                    pass

    def resolve_attempt(self, identity: str) -> None:
        reply = next((item for item in self.feed.replies if item.identity == identity), None)
        if reply is not None and reply.delivery is Delivery.UNKNOWN:
            self.feed = reply_changed(
                self.feed,
                replace(
                    reply,
                    delivery=Delivery.REVIEWED,
                    detail="You checked this attempt in Teams. Delivery remains unverified; future replies are enabled.",
                ),
            )
            self.save()
            self.changed()

    def disconnect(self) -> None:
        self.enabled = False
        self.web.close()
        self.feed = replace(self.feed, status=Status.DISCONNECTED, detail="Teams disconnected. Saved drafts and observed messages remain available.")
        self.save()
        self.changed()

    def follow(self, identities: tuple[str, ...]) -> None:
        known = {chat.identity for chat in self.feed.conversations}
        followed: list[str] = []
        for identity in identities:
            if identity in known and identity not in followed:
                followed.append(identity)
        self.feed = replace(self.feed, followed=tuple(followed[:MAX_FOLLOWED]))
        self.save()
        self.next_poll = 0
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
                    command = self.commands.get(timeout=0.4)
                    self.command(command)
                except queue.Empty:
                    pass
                except Exception:
                    self.feed = replace(
                        self.feed, status=Status.STALE, detail="Teams is unavailable. Your drafts are retained; reconnect or refresh to retry."
                    )
                    self.changed()
                if self.enabled and self.web.target and time.monotonic() >= self.next_poll:
                    try:
                        self.collect()
                    except Exception:
                        self.feed = replace(
                            self.feed,
                            status=Status.STALE,
                            detail="Teams updates are incomplete. Refresh or reconnect; saved content is still available.",
                        )
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
