import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest import TestCase

from pydantic import TypeAdapter

from assistant.browser_values import NavigationLoadingError, PageRow
from assistant.communications import (
    Acknowledgement,
    Connect,
    Conversation,
    Delivery,
    Feed,
    Handle,
    Message,
    Reply,
    ResolveAttempt,
    SaveDraft,
    Send,
    Status,
    TeamsActivity,
    Update,
    fingerprint,
    update_fingerprint,
)
from assistant.communications_browser import ActivityObservation, ChatUnavailableError, Observation, TeamsWeb
from assistant.communications_service import Communications
from assistant.communications_state import COMMUNICATIONS_STATE
from assistant.llm import Json
from assistant.state_store import SavedState
from tests.teams_fixture import Browser

_WIRE = TypeAdapter(dict[str, Json])


class Web:
    """This test owner holds Teams observations, selected chats and sent replies.

    Mutable effect receipts remain inside each fixture's lifetime. The collector
    receives immutable observations through the same Teams interface as TeamsWeb.
    """

    def __init__(self) -> None:
        self.target = ""
        self.connects = 0
        self.sends: list[tuple[str, str]] = []
        self.after_send: Callable[[], None] = lambda: None
        self.result: tuple[Message, ...] = ()
        self.current = Observation("19:one@thread.v2", "Anna", (Conversation("19:one@thread.v2", "Anna"),), (), editor_ready=True)
        self.discovered: Observation | None = None
        self.selected: Observation | None = None
        self.unavailable: frozenset[str] = frozenset()
        self.selections: tuple[str, ...] = ()
        self.discoveries = 0

    def connect(self, saved_target: str, cancel: threading.Event) -> str:
        self.connects += 1
        self.target = "owned-page"
        return self.target

    def read(self, cancel: threading.Event, *, target: str = "") -> Observation:
        return self.current

    def available(self, cancel: threading.Event) -> bool:
        return True

    def discover(self, cancel: threading.Event) -> Observation:
        self.discoveries += 1
        return self.discovered if self.discovered is not None else self.current

    def select(self, identity: str, cancel: threading.Event, *, target: str = "") -> Observation:
        self.selections += (identity,)
        if identity in self.unavailable:
            raise ChatUnavailableError("missing")
        return self.selected if self.selected is not None else self.current

    def activity(self, cancel: threading.Event) -> ActivityObservation:
        return ActivityObservation((), ready=True)

    def activity_read(self, identity: str, cancel: threading.Event) -> bool:
        return False

    def open_activity(self, identity: str, cancel: threading.Event) -> None:
        pass

    def send(self, identity: str, text: str, cancel: threading.Event) -> tuple[Message, ...]:
        self.sends.append((identity, text))
        self.after_send()
        return self.result

    def open(self, identity: str, cancel: threading.Event) -> None:
        self.select(identity, cancel)

    def close(self) -> None:
        pass


class LocalCipher:
    """Concrete byte adapter so the collector exercises its real atomic file store."""

    def protect(self, data: bytes) -> bytes:
        return b"fixture:" + data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        return data[8:][::-1]


def service(path: Path) -> tuple[Communications, Web]:
    web = Web()
    store = SavedState(path, COMMUNICATIONS_STATE, cipher=LocalCipher())
    controller = Communications(web, store, lambda feed: None)
    controller.feed = Feed(status=Status.CONNECTED, conversations=(Conversation("19:one@thread.v2", "Anna"),), followed=("19:one@thread.v2",))
    return controller, web


def test_repeated_collection_retains_one_connection(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    controller.command(Connect())
    for _ in range(4):
        controller.collect()
    assert web.connects == 1


def test_handled_chat_revisions_survive_reload_without_saving_incoming_bodies(tmp_path: Path) -> None:
    controller, _web = service(tmp_path / "saved.bin")
    message = Message("19:one@thread.v2", "one", "Anna", "Private incoming content", 1, 2)
    controller.feed = replace(controller.feed, messages=(message,))
    controller.command(Handle((Acknowledgement(message.key, fingerprint(message.text)),)))
    saved = controller.store.read()
    assert "Private incoming content" not in str(saved)
    restarted, _ = service(tmp_path / "saved.bin")
    restarted.load()
    assert not restarted.feed.unseen(message)
    assert restarted.feed.unseen(replace(message, text="Revised private content"))


def test_failed_teams_read_confirmation_does_not_claim_native_acknowledgement(tmp_path: Path) -> None:
    controller, _web = service(tmp_path / "saved.bin")
    update = Update(TeamsActivity("123"), "Reaction", "Someone reacted", "Teams", 1)
    controller.feed = replace(controller.feed, updates=(update,))
    controller.command(Handle((Acknowledgement(update.key, update_fingerprint(update)),)))
    assert not controller.feed.pending_update(update)
    assert "could not be confirmed" in controller.feed.activity_detail


def test_only_a_verified_reply_handles_its_captured_ticket_and_never_a_new_arrival(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    original = Message("19:one@thread.v2", "request", "Anna", "Please check", 1, 2)
    arrival = replace(original, identity="new", text="And this", created_at=3)
    controller.feed = replace(controller.feed, messages=(original, arrival))
    web.result = (replace(original, identity="sent", sender="You", text="Checked", created_at=4),)
    captured = (Acknowledgement(original.key, fingerprint(original.text)),)
    controller.command(Send(original.conversation, "Checked", "verified", captured))
    assert not controller.feed.unseen(original) and controller.feed.unseen(arrival)
    assert not controller.feed.unseen(controller.feed.messages[-1])


def test_one_unavailable_chat_does_not_drop_other_chats_observed_updates(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    controller.feed = replace(controller.feed, followed=("19:one@thread.v2", "19:missing@thread.v2"))
    message = Message("19:one@thread.v2", "old", "Anna", "Updated while another chat is unavailable", 1, 2)
    current = Observation("19:one@thread.v2", "Anna", (Conversation("19:one@thread.v2", "Anna"),), (message,), editor_ready=True)
    web.current = current
    web.unavailable = frozenset({"19:missing@thread.v2"})
    controller.collect()
    controller.collect()
    assert controller.feed.messages == (message,)
    assert controller.feed.status is Status.CONNECTED
    assert len(controller.feed.unavailable) == 1
    assert controller.feed.unavailable[0].conversation == "19:missing@thread.v2"
    assert "1 chat" in controller.feed.detail
    web.unavailable = frozenset()
    controller.cursor = 1
    controller.collect()
    assert not tuple(controller.feed.unavailable)


def test_saved_followed_chat_recovers_when_no_conversation_pane_is_open(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    empty = Observation("", "", (), (), editor_ready=False)
    message = Message("19:one@thread.v2", "loaded", "Anna", "Back from Activity", 1, 2)
    current = Observation("19:one@thread.v2", "Anna", controller.feed.conversations, (message,), editor_ready=True)
    web.current, web.selected = empty, current
    controller.collect()
    assert web.selections == ("19:one@thread.v2",)
    assert controller.feed.messages == (message,)
    assert controller.feed.status is Status.CONNECTED


def test_first_collection_discovers_chat_navigation_before_choosing_chats(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    controller.feed = Feed()
    empty = Observation("", "", (), (), editor_ready=False)
    current = Observation("19:one@thread.v2", "Anna", (Conversation("19:one@thread.v2", "Anna"),), (), editor_ready=True)
    web.current, web.discovered = empty, current
    controller.collect()
    assert web.discoveries == 1
    assert controller.feed.followed == ("19:one@thread.v2",)
    assert controller.feed.status is Status.CONNECTED


def test_first_collection_opens_a_discovered_chat_when_teams_has_no_current_chat(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    controller.feed = Feed()
    landing = Observation("", "", (Conversation("19:one@thread.v2", "Anna"),), (), editor_ready=False)
    current = Observation("19:one@thread.v2", "Anna", landing.conversations, (), editor_ready=True)
    web.current, web.discovered, web.selected = landing, landing, current
    controller.collect()
    assert web.selections == ("19:one@thread.v2",)
    assert controller.feed.followed == ("19:one@thread.v2",)
    assert controller.feed.status is Status.CONNECTED


def chat_document(identity: str) -> dict[str, Json]:
    return {"current": identity, "title": "Anna", "conversations": [], "messages": [], "editor_ready": True}


def test_rechecking_a_loading_exact_chat_does_not_restart_teams_navigation(tmp_path: Path) -> None:
    browser = Browser((PageRow("owned-page", "", "https://teams.cloud.microsoft/v2/"),))
    web = TeamsWeb(tmp_path, browser=browser)
    web.target = "owned-page"
    identity = "19:one@thread.v2"
    web.opening[web.target] = identity
    browser.documents = (browser.document, chat_document(identity))
    assert web.select(identity, threading.Event()).current == identity
    assert browser.opens == ()
    assert web.opening == {}


def test_pending_navigation_keeps_observing_the_same_exact_chat_without_reopening(tmp_path: Path) -> None:
    browser = Browser((PageRow("owned-page", "", "https://teams.cloud.microsoft/v2/"),))
    web = TeamsWeb(tmp_path, browser=browser)
    web.target = "owned-page"
    identity = "19:one@thread.v2"
    browser.documents = (chat_document("19:previous@thread.v2"), chat_document(identity))
    browser.navigation_failure = NavigationLoadingError("Navigation is still loading")
    assert web.select(identity, threading.Event()).current == identity
    assert len(browser.opens) == 1
    assert web.opening == {}


def test_next_chat_waits_for_pending_navigation_instead_of_restarting_teams(tmp_path: Path) -> None:
    browser = Browser((PageRow("owned-page", "", "https://teams.cloud.microsoft/v2/"),))
    web = TeamsWeb(tmp_path, browser=browser)
    web.target = "owned-page"
    web.opening[web.target] = "19:loading@thread.v2"
    browser.documents = (browser.document, chat_document("19:loading@thread.v2"), chat_document("19:one@thread.v2"))
    browser.sidebar_click = True
    assert web.select("19:one@thread.v2", threading.Event()).current == "19:one@thread.v2"
    assert browser.opens == ()
    assert web.opening == {}


def test_send_freezes_destination_and_does_not_erase_a_newer_draft(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    web.result = (Message("19:one@thread.v2", "posted-id", "You", "Original reply", 1, 2),)

    def next_draft() -> None:
        assert controller.submit(SaveDraft("19:one@thread.v2", "Next draft"))

    web.after_send = next_draft
    controller.send(Send("19:one@thread.v2", "Original reply", "original"))
    assert web.sends == [("19:one@thread.v2", "Original reply")]
    assert controller.drafts["19:one@thread.v2"] == "Next draft"
    assert controller.feed.replies[-1].delivery is Delivery.OBSERVED
    assert b"Original reply" not in controller.store.path.read_bytes()


def test_unknown_send_is_retained_across_restart_and_not_repeated(tmp_path: Path) -> None:
    path = tmp_path / "saved.bin"
    controller, _web = service(path)
    controller.send(Send("19:one@thread.v2", "Check the figures", "check"))
    assert controller.feed.replies[-1].delivery is Delivery.UNKNOWN
    recovered, next_web = service(path)
    recovered.load()
    recovered.feed = replace(recovered.feed, status=Status.CONNECTED)
    recovered.send(Send("19:one@thread.v2", "Check the figures", "retry"))
    assert next_web.sends == []
    assert recovered.feed.replies[-1].delivery is Delivery.FAILED
    assert recovered.drafts["19:one@thread.v2"] == "Check the figures"


def test_interrupted_attempt_recovers_as_unknown_without_browser_effect(tmp_path: Path) -> None:
    controller, _web = service(tmp_path / "saved.bin")
    controller.feed = replace(controller.feed, replies=(Reply("attempt", "19:one@thread.v2", "Anna", "Saved words", 1, Delivery.SENDING),))
    controller.save()
    recovered, next_web = service(controller.store.path)
    recovered.load()
    assert recovered.feed.replies[0].delivery is Delivery.UNKNOWN
    assert next_web.sends == [] and next_web.connects == 0


def test_explicit_review_keeps_uncertain_evidence_and_enables_future_replies(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    controller.send(Send("19:one@thread.v2", "Earlier reply", "earlier"))
    attempt = controller.feed.replies[-1]
    controller.command(ResolveAttempt(attempt.identity))
    assert controller.feed.replies[-1].delivery is Delivery.REVIEWED
    assert controller.feed.replies[-1].text == "Earlier reply"
    assert web.sends == [("19:one@thread.v2", "Earlier reply")]
    controller.send(Send("19:one@thread.v2", "A new reply", "new"))
    assert web.sends[-1] == ("19:one@thread.v2", "A new reply")


def test_repeated_attempt_identity_never_posts_twice(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    command = Send("19:one@thread.v2", "Only once", "attempt")
    web.result = (Message(command.conversation, "posted", "You", command.text, 1, 2),)
    controller.send(command)
    controller.send(command)
    assert web.sends == [(command.conversation, command.text)]
    assert len(controller.feed.replies) == 1


def test_latest_draft_survives_a_full_action_queue(tmp_path: Path) -> None:
    controller, _web = service(tmp_path / "saved.bin")
    for _ in range(256):
        assert controller.submit(Connect())
    for index in range(1000):
        assert controller.submit(SaveDraft("19:one@thread.v2", str(index)))
    controller.drain_drafts()
    controller.save()
    restored, _next_web = service(controller.store.path)
    restored.load()
    assert restored.drafts == {"19:one@thread.v2": "999"}


def test_invalid_saved_contract_cannot_partially_enable_communications(tmp_path: Path) -> None:
    # Defect: a generic serializer accepts non-Boolean activation or a Boolean
    # timestamp, or load applies activation before validating all saved evidence.
    controller, _ = service(tmp_path / "invalid.bin")
    invalid_states: tuple[dict[str, Json], ...] = (
        {"enabled": "true"},
        {
            "enabled": True,
            "replies": [
                {
                    "identity": "reply",
                    "conversation": "chat",
                    "title": "Atlas",
                    "text": "The requested draft",
                    "created_at": True,
                    "delivery": "UNKNOWN",
                }
            ],
        },
    )
    for state in invalid_states:
        controller.store.path.write_bytes(controller.store.cipher.protect(_WIRE.dump_json(state)))
        with TestCase().assertRaises(ValueError):
            controller.load()
        assert not controller.enabled
