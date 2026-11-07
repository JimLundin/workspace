"""A cancellable Teams collector; browser, encrypted drafts and effects stay off Qt."""

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
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
from cell import Cell


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


@dataclass(frozen=True, slots=True)
class _Talking:
    """The worker thread's state; only it replaces this record."""

    feed: Feed = field(default_factory=Feed)
    drafts: frozendict[str, str] = frozendict()
    """The saved draft of each conversation."""
    enabled: bool = False
    dirty: bool = False
    """The saved state is behind the feed or drafts."""
    started: bool = False
    saved_target: str = ""
    """The Teams tab to reuse after a restart."""
    cursor: int = 0
    """Which followed conversation the next poll reads."""
    next_poll: float = 0.0
    next_activity: float = 0.0


@dataclass(frozen=True, slots=True)
class Communications:
    web: Teams
    store: SavedState[CommunicationsState]
    publish: Callable[[Feed], None]
    _state: Cell[_Talking] = field(default_factory=lambda: Cell(_Talking()), init=False, repr=False)
    _pending_drafts: Cell[frozendict[str, str]] = field(default_factory=lambda: Cell[frozendict[str, str]](frozendict()), init=False, repr=False)
    """Drafts submitted from other threads, under `draft_lock`, until the worker applies them."""
    draft_lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    stop: threading.Event = field(default_factory=threading.Event, init=False)
    commands: queue.Queue[Command] = field(default_factory=lambda: queue.Queue[Command](maxsize=256), init=False)
    _thread: Cell[threading.Thread | None] = field(default_factory=lambda: Cell[threading.Thread | None](None), init=False, repr=False)

    @property
    def feed(self) -> Feed:
        return self._state.get().feed

    @property
    def drafts(self) -> frozendict[str, str]:
        return self._state.get().drafts

    @property
    def enabled(self) -> bool:
        return self._state.get().enabled

    def show(self, feed: Feed) -> None:
        """Replace the feed the controller holds and publishes on its next change."""
        self._state.set(replace(self._state.get(), feed=feed))

    def poll_next(self, position: int) -> None:
        """Make the next poll read the followed conversation at `position`."""
        self._state.set(replace(self._state.get(), cursor=position))

    def _draft(self, conversation: str, text: str) -> None:
        self._state.set(replace(self._state.get(), drafts=frozendict({**self._state.get().drafts, conversation: text})))

    def start(self) -> None:
        if not self._state.get().started:
            self._state.set(replace(self._state.get(), started=True))
            thread = threading.Thread(target=self.run, name="Teams conversation", daemon=True)
            self._thread.set(thread)
            thread.start()

    def submit(self, command: Command) -> bool:
        if self.stop.is_set():
            return False
        if isinstance(command, SaveDraft):
            if len(command.text) > 32_000 or len(command.conversation) > 512:
                return False
            with self.draft_lock:
                self._pending_drafts.update(lambda pending: frozendict({**pending, command.conversation: command.text}))
            return True
        try:
            self.commands.put_nowait(command)
            return True
        except queue.Full:
            return False

    def drain_drafts(self) -> None:
        with self.draft_lock:
            pending = self._pending_drafts.get()
            self._pending_drafts.set(frozendict())
        if pending:
            self._state.set(replace(self._state.get(), drafts=frozendict({**self._state.get().drafts, **pending}), dirty=True))

    def changed(self) -> None:
        self.publish(self.feed)

    def load(self) -> None:
        state = self.store.read()
        self._state.set(replace(self._state.get(), enabled=state.enabled))
        self._state.set(replace(self._state.get(), saved_target=state.target))
        self._state.set(replace(self._state.get(), drafts=frozendict(state.drafts)))
        self.show(
            replace(
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
        )

    def save(self) -> None:
        self.store.write(
            CommunicationsState(
                target=self._state.get().saved_target,
                followed=self.feed.followed,
                drafts=tuple(self._state.get().drafts.items()),
                replies=tuple(
                    StoredReply(item.identity, item.conversation, item.title, item.text, item.created_at, item.delivery, item.detail)
                    for item in self.feed.replies
                ),
                handled=tuple(StoredAcknowledgement(mark.key[0], mark.key[1], mark.fingerprint) for mark in self.feed.handled),
                enabled=self._state.get().enabled,
            )
        )
        self._state.set(replace(self._state.get(), dirty=False))

    def connect(self) -> None:
        self.show(replace(self.feed, status=Status.CONNECTING, detail="Waiting for Edge connection access…"))
        self.changed()
        new_saved_target = self.web.connect(self._state.get().saved_target, self.stop)
        self._state.set(replace(self._state.get(), saved_target=new_saved_target))
        self._state.set(replace(self._state.get(), enabled=True))
        self.save()
        self._state.set(replace(self._state.get(), next_poll=0))
        self._state.set(replace(self._state.get(), next_activity=0))

    def collect_activity(self) -> None:
        previous_target = self.web.target
        try:
            found = self.web.activity(self.stop)
        except Exception:
            self.show(replace(self.feed, activity_detail="Teams Activity is loading or its tab is visible; chat updates continue."))
        else:
            self.show(updates_observed(self.feed, found.items))
            self.show(replace(self.feed, activity_detail=f"Teams Activity · {len(found.items)} rendered updates"))
        if self.web.target != previous_target:
            self._state.set(replace(self._state.get(), saved_target=self.web.target))
            self._state.set(replace(self._state.get(), dirty=True))
        self.changed()

    def collect(self) -> None:
        if not self.web.available(self.stop):
            self.show(
                replace(self.feed, status=Status.STALE, detail="Teams collection paused while its browser tab is visible. Switch away to resume.")
            )
            self.changed()
            return
        try:
            found = self.web.read(self.stop)
        except ChatUnavailableError:
            self.show(replace(self.feed, status=Status.STALE, detail="Teams is loading. Updates will resume automatically."))
            self.changed()
            return
        if not found.current and not self.feed.followed:
            found = self.web.discover(self.stop)
        if not found.current and not found.conversations and not self.feed.followed:
            self.show(replace(self.feed, status=Status.STALE, detail="Finish signing in or loading Teams in the Workspace browser tab."))
            self.changed()
            return
        known = {chat.identity: chat for chat in self.feed.conversations}
        known.update({chat.identity: chat for chat in found.conversations})
        followed = self.feed.followed
        if not followed:
            candidates = (found.current, *(chat.identity for chat in found.conversations if chat.kind == "chat"))
            followed = tuple(dict.fromkeys(candidate for candidate in candidates if candidate))[:4]
            self._state.set(replace(self._state.get(), dirty=True))
        self.show(replace(self.feed, conversations=tuple(known.values())[:150], followed=followed))
        self.show(observed(self.feed, found.messages, time.time()))
        unavailable = {item.conversation: item for item in self.feed.unavailable if item.conversation in followed}
        if followed:
            identity = followed[self._state.get().cursor % len(followed)]
            self._state.set(replace(self._state.get(), cursor=self._state.get().cursor + 1))
            try:
                found = self.web.select(identity, self.stop)
            except ChatUnavailableError as error:
                unavailable[identity] = UnavailableChat(identity, error.reason)
            else:
                unavailable.pop(identity, None)
                known.update({chat.identity: chat for chat in found.conversations})
                self.show(observed(replace(self.feed, conversations=tuple(known.values())[:150]), found.messages, time.time()))
        detail = f"Teams · following {len(followed)} chats"
        if unavailable:
            detail += f" · {len(unavailable)} chat{'s' if len(unavailable) != 1 else ''} unavailable; retrying automatically"
        self.show(
            replace(
                self.feed,
                unavailable=tuple(unavailable.values()),
                status=Status.STALE if followed and len(unavailable) == len(followed) else Status.CONNECTED,
                detail=detail,
            )
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
        self.show(reply_changed(self.feed, reply))
        if chat.identity not in self._state.get().drafts:
            self._draft(chat.identity, command.text)
        self.drain_drafts()
        self.save()  # Intent and text survive a crash before touching the page.
        self.changed()
        if reply.delivery is Delivery.FAILED:
            return
        try:
            messages = self.web.send(chat.identity, command.text, self.stop)
            self.drain_drafts()
            if messages:
                self.show(observed(self.feed, tuple(replace(message, own=True) for message in messages), time.time()))
                self.show(handle(self.feed, command.handling))
                reply = replace(reply, delivery=Delivery.OBSERVED, detail="Reply observed in the selected Teams chat.")
                if self._state.get().drafts.get(chat.identity) == command.text:
                    self._draft(chat.identity, "")
            else:
                reply = replace(
                    reply,
                    delivery=Delivery.UNKNOWN,
                    detail="Teams did not provide reply readback. Inspect the chat; nothing will be resent automatically.",
                )
        except Exception:
            # A failure after entering the effect may already have posted. Never expose page content in diagnostics.
            reply = replace(reply, delivery=Delivery.UNKNOWN, detail="The send outcome is uncertain. Your text is saved; inspect this chat in Teams.")
        self.show(reply_changed(self.feed, reply))
        self.save()
        self.changed()

    def handled(self, command: Handle) -> None:
        before = self.feed
        self.show(handle(self.feed, command.marks))
        if self.feed == before:
            return
        try:
            self.save()
        except Exception:
            self.show(before)
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
                    self.show(
                        replace(
                            self.feed,
                            activity_detail=(
                                "Handled here · Teams read state confirmed."
                                if confirmed
                                else "Handled here · Teams read state could not be confirmed. Open Teams to check it."
                            ),
                        )
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
                self._state.set(replace(self._state.get(), next_poll=0))
                self._state.set(replace(self._state.get(), next_activity=0))
            case Follow(identities):
                self.follow(identities)
            case Seen(key):
                self.show(acknowledge(self.feed, key))
                self.changed()
            case Handle():
                self.handled(command)
            case Reopen(key):
                self.show(reopen(self.feed, key))
                self.save()
                self.changed()
            case OpenUpdate(key):
                self.open_update(key)
            case SaveDraft(identity, text):
                if len(text) <= 32_000 and len(identity) <= 512:
                    self._draft(identity, text)
                    self._state.set(replace(self._state.get(), dirty=True))
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
            self.show(
                reply_changed(
                    self.feed,
                    replace(
                        reply,
                        delivery=Delivery.REVIEWED,
                        detail="You checked this attempt in Teams. Delivery remains unverified; future replies are enabled.",
                    ),
                )
            )
            self.save()
            self.changed()

    def disconnect(self) -> None:
        self._state.set(replace(self._state.get(), enabled=False))
        self.web.close()
        self.show(replace(self.feed, status=Status.DISCONNECTED, detail="Teams disconnected. Saved drafts and observed messages remain available."))
        self.save()
        self.changed()

    def follow(self, identities: tuple[str, ...]) -> None:
        known = {chat.identity for chat in self.feed.conversations}
        followed = tuple(dict.fromkeys(identity for identity in identities if identity in known))[:MAX_FOLLOWED]
        self.show(replace(self.feed, followed=followed))
        self.save()
        self._state.set(replace(self._state.get(), next_poll=0))
        self.changed()

    def run(self) -> None:
        try:
            try:
                self.load()
            except Exception:
                self._state.set(replace(self._state.get(), enabled=False))
                self.show(replace(self.feed, detail="Saved Teams preferences could not be read. Reconnect to start a new session."))
            self.changed()
            if self._state.get().enabled:
                try:
                    self.connect()
                except Exception:
                    self.show(replace(self.feed, status=Status.STALE, detail="Teams needs a fresh Edge connection. Use Connect Teams to retry."))
                    self.changed()
            while not self.stop.is_set():
                self.drain_drafts()
                try:
                    command = self.commands.get(timeout=0.4)
                    self.command(command)
                except queue.Empty:
                    pass
                except Exception:
                    self.show(
                        replace(
                            self.feed,
                            status=Status.STALE,
                            detail="Teams is unavailable. Your drafts are retained; reconnect or refresh to retry.",
                        )
                    )
                    self.changed()
                if self._state.get().enabled and self.web.target and time.monotonic() >= self._state.get().next_poll:
                    try:
                        self.collect()
                    except Exception:
                        self.show(
                            replace(
                                self.feed,
                                status=Status.STALE,
                                detail="Teams updates are incomplete. Refresh or reconnect; saved content is still available.",
                            )
                        )
                        self.changed()
                    self._state.set(replace(self._state.get(), next_poll=time.monotonic() + 4))
                if self._state.get().enabled and self.web.target and time.monotonic() >= self._state.get().next_activity:
                    self.collect_activity()
                    self._state.set(replace(self._state.get(), next_activity=time.monotonic() + 20))
                if self._state.get().dirty:
                    try:
                        self.save()
                    except OSError:
                        self.show(replace(self.feed, detail="Teams drafts could not be saved. Keep this session open and retry."))
                        self.changed()
        finally:
            self.drain_drafts()
            if self._state.get().dirty:
                try:
                    self.save()
                except OSError:
                    self.show(replace(self.feed, detail="The latest Teams draft could not be saved."))
                    self.changed()
            self.web.close()

    def close(self) -> None:
        self.stop.set()
        if (thread := self._thread.get()) is not None:
            thread.join(timeout=5)
