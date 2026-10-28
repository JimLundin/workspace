import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from assistant.browser import Browser
from assistant.browser_values import NavigationLoadingError
from assistant.communications import (
    Acknowledgement,
    Connect,
    Conversation,
    Delivery,
    Feed,
    Handle,
    HandleNotice,
    Message,
    NotificationFilters,
    Reply,
    ResolveAttempt,
    SaveDraft,
    Send,
    Status,
    TeamsActivity,
    Update,
    WindowsObserved,
    fingerprint,
    update_fingerprint,
)
from assistant.communications_browser import ChatUnavailableError, Observation, TeamsWeb
from assistant.communications_service import Communications, SavedState
from assistant.system_notices import Notice, NoticeKey, Observed


class Web(TeamsWeb):
    __slots__ = ("after_send", "connects", "result", "sends")

    def __init__(self) -> None:
        super().__init__(Path("unused-browser-profile"))
        self.connects = 0
        self.sends: list[tuple[str, str]] = []
        self.after_send: Callable[[], None] = lambda: None
        self.result: tuple[Message, ...] = ()

    def connect(self, saved_target: str, cancel: threading.Event) -> str:
        self.connects += 1
        self.target = "owned-page"
        return self.target

    def read(self, cancel: threading.Event, *, target: str = "") -> Observation:
        return Observation("19:one@thread.v2", "Anna", (Conversation("19:one@thread.v2", "Anna"),), (), True)

    def available(self, cancel: threading.Event) -> bool:
        return True

    def discover(self, cancel: threading.Event) -> Observation:
        return self.read(cancel)

    def select(self, identity: str, cancel: threading.Event, *, target: str = "") -> Observation:
        return self.read(cancel)

    def send(self, identity: str, text: str, cancel: threading.Event) -> tuple[Message, ...]:
        self.sends.append((identity, text))
        self.after_send()
        return self.result

    def close(self) -> None:
        pass


def service(path: Path) -> tuple[Communications, Web]:
    web = Web()
    store = SavedState(path, protect=lambda data: b"fixture:" + data[::-1], unprotect=lambda data: data[8:][::-1])
    controller = Communications(web, store, lambda feed, drafts: None)
    controller.feed = Feed(status=Status.CONNECTED, conversations=(Conversation("19:one@thread.v2", "Anna"),),
                           followed=("19:one@thread.v2",))
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


def test_windows_delivery_enters_the_same_inbox_and_dismissal_follows_saved_handling(tmp_path: Path) -> None:
    controller, _web = service(tmp_path / "saved.bin")
    notice = Notice(NoticeKey(7, 11_644_473_601_0000000), "Mail", "Mail", "Invitation", "Review this meeting")
    controller.submit(WindowsObserved(Observed((notice,))))
    controller.drain_drafts()
    assert len(controller.feed.updates) == 1
    update = controller.feed.updates[0]
    dismissed: list[NoticeKey] = []
    def dismiss(key: NoticeKey) -> None:
        assert controller.store.read()["handled"]
        dismissed.append(key)
    controller.dismiss_notice = dismiss
    controller.command(Handle((Acknowledgement(update.key, update_fingerprint(update)),)))
    assert dismissed == [notice.key]
    assert not controller.feed.pending_update(update)
    controller.submit(WindowsObserved(Observed((notice,))))
    controller.drain_drafts()
    assert len(controller.feed.updates) == 1 and not controller.feed.pending_update(controller.feed.updates[0])


def test_notification_filters_survive_reload_without_marking_source_work_handled(tmp_path: Path) -> None:
    controller, _ = service(tmp_path / "saved.bin")
    controller.command(NotificationFilters(("Mail", "Security")))
    restarted, _ = service(tmp_path / "saved.bin")
    restarted.load()
    assert restarted.feed.muted_apps == ("Mail", "Security")
    assert not restarted.feed.handled


def test_failed_teams_read_confirmation_does_not_claim_native_acknowledgement(tmp_path: Path) -> None:
    controller, _web = service(tmp_path / "saved.bin")
    update = Update(TeamsActivity("123"), "Reaction", "Someone reacted", "Teams", 1)
    controller.feed = replace(controller.feed, updates=(update,))
    with patch.object(Web, "activity_read", return_value=False):
        controller.command(Handle((Acknowledgement(update.key, update_fingerprint(update)),)))
    assert not controller.feed.pending_update(update)
    assert "could not be confirmed" in controller.feed.activity_detail


def test_dismissing_a_glass_card_before_the_inbox_paints_still_saves_handling(tmp_path: Path) -> None:
    controller, _web = service(tmp_path / "saved.bin")
    notice = Notice(NoticeKey(8, 11_644_473_602_0000000), "Mail", "Mail", "New update", "Check it")
    dismissed: list[NoticeKey] = []
    controller.dismiss_notice = dismissed.append
    controller.command(HandleNotice(notice))
    assert dismissed == [notice.key]
    assert len(controller.feed.updates) == 1 and not controller.feed.pending_update(controller.feed.updates[0])
    assert controller.store.read()["handled"]


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
    controller, _web = service(tmp_path / "saved.bin")
    controller.feed = replace(controller.feed, followed=("19:one@thread.v2", "19:missing@thread.v2"))
    message = Message("19:one@thread.v2", "old", "Anna", "Updated while another chat is unavailable", 1, 2)
    current = Observation("19:one@thread.v2", "Anna", (Conversation("19:one@thread.v2", "Anna"),), (message,), True)
    with patch.object(Web, "read", return_value=current), patch.object(
        Web, "select", side_effect=(current, ChatUnavailableError("missing")),
    ):
        controller.collect()
        controller.collect()
    assert controller.feed.messages == (message,)
    assert controller.feed.status is Status.CONNECTED
    assert len(controller.feed.unavailable) == 1
    assert controller.feed.unavailable[0].conversation == "19:missing@thread.v2"
    assert "1 chat" in controller.feed.detail
    with patch.object(Web, "select", return_value=current):
        controller.cursor = 1
        controller.collect()
    assert controller.feed.unavailable == ()


def test_saved_followed_chat_recovers_when_no_conversation_pane_is_open(tmp_path: Path) -> None:
    controller, _web = service(tmp_path / "saved.bin")
    empty = Observation("", "", (), (), False)
    message = Message("19:one@thread.v2", "loaded", "Anna", "Back from Activity", 1, 2)
    current = Observation("19:one@thread.v2", "Anna", controller.feed.conversations, (message,), True)
    with patch.object(Web, "read", return_value=empty), patch.object(Web, "select", return_value=current) as selected:
        controller.collect()
    selected.assert_called_once_with("19:one@thread.v2", controller.stop)
    assert controller.feed.messages == (message,)
    assert controller.feed.status is Status.CONNECTED


def test_first_collection_discovers_chat_navigation_before_choosing_chats(tmp_path: Path) -> None:
    controller, _web = service(tmp_path / "saved.bin")
    controller.feed = Feed()
    empty = Observation("", "", (), (), False)
    current = Observation("19:one@thread.v2", "Anna", (Conversation("19:one@thread.v2", "Anna"),), (), True)
    with patch.object(Web, "read", return_value=empty), patch.object(Web, "discover", return_value=current) as discovered:
        controller.collect()
    discovered.assert_called_once_with(controller.stop)
    assert controller.feed.followed == ("19:one@thread.v2",)
    assert controller.feed.status is Status.CONNECTED


def test_first_collection_opens_a_discovered_chat_when_teams_has_no_current_chat(tmp_path: Path) -> None:
    controller, _web = service(tmp_path / "saved.bin")
    controller.feed = Feed()
    landing = Observation("", "", (Conversation("19:one@thread.v2", "Anna"),), (), False)
    current = Observation("19:one@thread.v2", "Anna", landing.conversations, (), True)
    with patch.object(Web, "read", return_value=landing), patch.object(Web, "discover", return_value=landing), patch.object(
        Web, "select", return_value=current,
    ) as selected:
        controller.collect()
    selected.assert_called_once_with("19:one@thread.v2", controller.stop)
    assert controller.feed.followed == ("19:one@thread.v2",)
    assert controller.feed.status is Status.CONNECTED


def test_rechecking_a_loading_exact_chat_does_not_restart_teams_navigation(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    web.target = "owned-page"
    identity = "19:one@thread.v2"
    page = {"id": web.target, "url": "https://teams.cloud.microsoft/v2/"}
    web.opening[web.target] = identity
    current = Observation(identity, "Anna", controller.feed.conversations, (), True)
    with patch.object(Web, "pages", return_value=(page,)), patch.object(Web, "read", return_value=current), patch.object(
        Web, "evaluate", return_value=False,
    ), patch.object(
        Browser, "request",
    ) as navigate:
        assert web._reopen(identity, controller.stop).current == identity
    navigate.assert_not_called()
    assert web.opening == {}


def test_pending_navigation_keeps_observing_the_same_exact_chat_without_reopening(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    web.target = "owned-page"
    identity = "19:one@thread.v2"
    page = {"id": web.target, "url": "https://teams.cloud.microsoft/v2/"}
    current = Observation(identity, "Anna", controller.feed.conversations, (), True)
    with patch.object(Web, "pages", return_value=(page,)), patch.object(Web, "read", return_value=current), patch.object(
        Web, "evaluate", return_value=False,
    ), patch.object(Browser, "request", side_effect=NavigationLoadingError("Navigation is still loading")) as navigate:
        assert web._reopen(identity, controller.stop).current == identity
    assert navigate.call_count == 1
    assert web.opening == {}


def test_next_chat_waits_for_pending_navigation_instead_of_restarting_teams(tmp_path: Path) -> None:
    controller, web = service(tmp_path / "saved.bin")
    web.target = "owned-page"
    web.opening[web.target] = "19:loading@thread.v2"
    empty = Observation("", "", (), (), False)
    pending = Observation("19:loading@thread.v2", "Loading chat", (), (), True)
    requested = Observation("19:one@thread.v2", "Anna", controller.feed.conversations, (), True)
    with patch.object(Web, "read", side_effect=(empty, requested)), patch.object(Web, "evaluate", return_value=True), patch.object(
        Web, "_reopen", return_value=pending,
    ) as resume:
        assert web._select(requested.current, controller.stop).current == requested.current
    resume.assert_called_once_with("19:loading@thread.v2", controller.stop, target="")
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
