"""Each feed source variant decides its key, origin, pending rule and triage evidence once."""

from dataclasses import replace

from assistant.communications import (
    ChatTicket,
    Conversation,
    Delivery,
    Feed,
    Message,
    Reply,
    TeamsActivity,
    Update,
    WindowsNotice,
)
from assistant.feed_origin import App
from assistant.feed_sources import (
    Attention,
    ChatTicketSource,
    FeedSource,
    NoticesObserved,
    PendingFeed,
    ReplySource,
    SourceKind,
    TeamsObserved,
    UpdateSource,
    attention,
    chat_message,
    evidence,
    key,
    listed,
    observe,
    origin,
    triage_evidence,
)
from assistant.notification_sources import Notices, NotificationFilter
from tests.communications_fixture import communication_feed
from winapi.system_notices import NoticeKey

CHAT = Conversation("chat", "Planning")
FIRST = Message("chat", "one", "Anna", "Review the figures", 1, 1)
SECOND = Message("chat", "two", "Anna", "And the budget", 2, 2)
ACTIVITY = Update(TeamsActivity("mention"), "Anna mentioned you", "Budget", "Teams", 3)
MAIL = Update(WindowsNotice(NoticeKey(1, 2), "Microsoft.OutlookForWindows"), "Forecast", "Figures", "Outlook", 4)
OTHER = Update(WindowsNotice(NoticeKey(3, 4), "contoso"), "Deploy", "Finished", "Contoso", 5)
REPLY = Reply("reply", "chat", "Anna", "On it", 6)


def test_each_report_keeps_the_others_in_the_pending_feed() -> None:
    # Defect: one observer's report drops another's, or triage sees notices
    # without Teams work or a stale notification filter.
    teams = communication_feed()
    notices = Notices(
        updates=(Update(WindowsNotice(NoticeKey(1, 2), "mail"), "Review", "Budget", "Outlook", 3),),
        filter=NotificationFilter(frozenset({"chat-app"})),
    )
    first = observe(PendingFeed(), NoticesObserved(notices))
    assert first == PendingFeed(notices=notices)
    second = observe(first, TeamsObserved(teams))
    assert second == PendingFeed(teams, notices)
    revised = Notices(handled=notices.handled, filter=NotificationFilter(frozenset()))
    assert observe(second, NoticesObserved(revised)) == PendingFeed(teams, revised)


def test_each_source_variant_owns_its_attention_key_origin_and_evidence() -> None:
    # Defect: the feed and triage disagree about a variant, e.g. an in-flight
    # send is quoted to triage, or a source is badged wrongly.
    table: tuple[tuple[FeedSource, Attention, SourceKind, App, int], ...] = (
        (ChatTicketSource(ChatTicket("chat", (FIRST, SECOND)), CHAT), Attention.TRIAGE, SourceKind.CHAT, App.TEAMS, 2),
        (UpdateSource(ACTIVITY), Attention.TRIAGE, SourceKind.ACTIVITY, App.TEAMS, 1),
        (UpdateSource(MAIL), Attention.TRIAGE, SourceKind.WINDOWS, App.OUTLOOK, 1),
        (UpdateSource(OTHER), Attention.TRIAGE, SourceKind.WINDOWS, App.WINDOWS, 1),
        (ReplySource(REPLY), Attention.SETTLING, SourceKind.REPLY, App.TEAMS, 0),
        (ReplySource(replace(REPLY, delivery=Delivery.SENDING)), Attention.SETTLING, SourceKind.REPLY, App.TEAMS, 0),
        (ReplySource(replace(REPLY, delivery=Delivery.UNKNOWN)), Attention.TRIAGE, SourceKind.REPLY, App.TEAMS, 1),
        (ReplySource(replace(REPLY, delivery=Delivery.FAILED)), Attention.TRIAGE, SourceKind.REPLY, App.TEAMS, 1),
        (ReplySource(replace(REPLY, delivery=Delivery.OBSERVED)), Attention.RESOLVED, SourceKind.REPLY, App.TEAMS, 0),
        (ReplySource(replace(REPLY, delivery=Delivery.REVIEWED)), Attention.RESOLVED, SourceKind.REPLY, App.TEAMS, 0),
    )
    for source, expected, kind, app, quoted in table:
        assert (attention(source), key(source).kind, origin(source).app, len(evidence(source))) == (expected, kind, app, quoted), source
        assert all(item.origin == origin(source) for item in evidence(source))


def test_pending_listing_keeps_filtered_notices_unhandled_and_replies_until_they_retire() -> None:
    # Defect: filtering a notice handles it, or pending work drops a delivered reply before the person sees it.
    feed = PendingFeed(
        teams=Feed(
            conversations=(CHAT,),
            followed=("chat",),
            messages=(FIRST,),
            replies=(replace(REPLY, delivery=Delivery.OBSERVED),),
        ),
        notices=Notices(updates=(MAIL, OTHER), filter=NotificationFilter(frozenset({"contoso"}))),
    )
    pending = tuple(key(source) for source in listed(feed))
    # The filtered notice is visible elsewhere, never quoted to triage.
    assert [item.kind for item in triage_evidence(feed)] == [SourceKind.CHAT, SourceKind.WINDOWS]
    assert [item.kind for item in pending] == [SourceKind.CHAT, SourceKind.WINDOWS, SourceKind.REPLY]


def test_chat_evidence_names_its_exact_message_for_research() -> None:
    # Defect: research resolves evidence to another message and quotes the wrong conversation's history.
    other = Message("other", "three", "Sam", "Lunch?", 3, 3)
    feed = Feed(conversations=(CHAT,), followed=("chat", "other"), messages=(FIRST, other))
    quoted = {item.body: item.identity for item in triage_evidence(PendingFeed(feed))}
    assert chat_message(feed, quoted["Lunch?"]) == other and chat_message(feed, quoted["Review the figures"]) == FIRST
    assert chat_message(feed, "chat:missing") is None
