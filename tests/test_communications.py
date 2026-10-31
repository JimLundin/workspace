import threading
from dataclasses import replace
from pathlib import Path

from assistant.browser_values import BrowserError, NavigationContextError
from assistant.communications import (
    MAX_MESSAGES,
    Acknowledgement,
    Feed,
    Message,
    SourceDateHint,
    SourceDateStatus,
    TeamsActivity,
    Update,
    UpdateKind,
    acknowledge,
    chat_tickets,
    fingerprint,
    handle,
    observed,
    reopen,
    update_fingerprint,
    updates_observed,
)
from assistant.communications_browser import TeamsWeb, activity_observation
from assistant.llm import Json
from assistant.web_apps import ActivityItem, ActivityPage
from tests.teams_fixture import Browser


def test_message_identity_is_scoped_to_chat_and_reactions_do_not_realert() -> None:
    first = Message("chat-one", "same-id", "Anna", "The draft is ready.", 10, 20)
    other = replace(first, conversation="chat-two", sender="Sam")
    feed = observed(Feed(), (first, other), 20)
    feed = acknowledge(feed, first.key)
    repeated = replace(first, observed_at=30, reactions=("👍 1",))
    updated = observed(feed, (repeated,), 30)
    assert len(updated.messages) == 2
    assert not updated.unseen(updated.messages[0])
    assert updated.messages[0].observed_at == 20
    assert updated.unseen_chats == 1
    edited = observed(updated, (replace(repeated, text="The revised draft is ready."),), 40)
    assert edited.unseen_chats == 2


def test_bounded_history_prunes_acknowledgements_with_their_messages() -> None:
    first = Message("chat", "0", "Anna", "First", 0, 0)
    feed = acknowledge(observed(Feed(), (first,), 0), first.key)
    messages = tuple(Message("chat", str(index), "Anna", "Update", index, index) for index in range(1, MAX_MESSAGES + 2))
    feed = observed(feed, messages, 1000)
    assert len(feed.messages) == MAX_MESSAGES
    assert first.key not in {message.key for message in feed.messages}
    assert feed.acknowledged == ()


def test_external_observation_rejects_missing_source_identity() -> None:
    browser = Browser()
    browser.documents = ({"current": "Anna", "title": "Anna", "conversations": [], "messages": [], "editor_ready": True},)
    try:
        TeamsWeb(Path("unused"), browser=browser).read(threading.Event())
    except BrowserError:
        pass
    else:
        raise AssertionError("A display name cannot become a Teams conversation identity.")


def test_read_uses_a_fresh_observation_after_a_launcher_redirect_retires_its_context() -> None:
    value: Json = {"current": "19:one@thread.v2", "title": "Anna", "conversations": [], "messages": [], "editor_ready": True}
    browser = Browser()
    browser.documents = (NavigationContextError("Cannot find context with specified id"), value)
    web = TeamsWeb(Path("unused"), browser=browser)
    assert web.read(threading.Event()).current == "19:one@thread.v2"
    assert browser.reads == 2


def test_inbox_groups_chat_backlog_and_handles_only_captured_revisions() -> None:
    first = Message("chat", "first", "Anna", "Review the figures", 1, 2)
    second = replace(first, identity="second", text="And check the total", created_at=3)
    own = replace(first, identity="own", text="Will do", created_at=4, own=True)
    feed = observed(Feed(followed=("chat",)), (first, second, own), 5)
    tickets = chat_tickets(feed)
    assert len(tickets) == 1 and tickets[0].messages == (first, second)
    captured = tuple(Acknowledgement(item.key, fingerprint(item.text)) for item in tickets[0].messages)
    newer = replace(second, identity="third", text="One more question", created_at=6)
    edited = replace(first, text="Review the revised figures")
    changed = observed(feed, (newer, edited), 7)
    handled = handle(changed, captured)
    assert {item.identity for item in chat_tickets(handled)[0].messages} == {"first", "third"}
    assert not handled.unseen(second)
    assert handled.unseen(edited)
    assert first.key not in {mark.key for mark in handled.handled}


def test_activity_repeats_replace_one_ticket_and_handled_items_can_be_reopened() -> None:
    update = Update(TeamsActivity("123"), "Anna reacted", "👍 · Planning", "Teams", 10, UpdateKind.REACTION)
    feed = updates_observed(Feed(), (update,))
    done = handle(feed, (Acknowledgement(update.key, update_fingerprint(update)),))
    repeated = updates_observed(done, (replace(update, created_at=20),))
    assert len(repeated.updates) == 1 and repeated.updates[0].created_at == 10
    assert not repeated.pending_update(repeated.updates[0])
    assert reopen(repeated, update.key).pending_update(update)
    edited = updates_observed(done, (replace(update, text="Changed context"),))
    assert edited.pending_update(edited.updates[0])


def test_an_undated_activity_keeps_its_visible_date_hint_or_stays_unknown() -> None:
    # Defect: Teams' visible relative date is dropped, or collection time
    # stands in for a date the page never showed.
    observed = activity_observation(
        ActivityPage(
            (
                ActivityItem("1", "Reminder", "Tomorrow.", "update", 0, "Yesterday"),
                ActivityItem("2", "Reminder", "Tomorrow.", "update", 0),
            ),
            ready=True,
        ),
        86_400,
    )
    hinted, unknown = (update.source_time for update in observed.items)
    assert isinstance(hinted, SourceDateHint) and hinted.label == "Yesterday"
    assert unknown is SourceDateStatus.UNKNOWN
