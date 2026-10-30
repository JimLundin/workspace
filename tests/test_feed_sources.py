"""Each feed source variant decides its key, origin, pending rule and triage evidence once."""

from dataclasses import replace

from assistant.communications import (
    ChatTicket,
    Conversation,
    Delivery,
    Feed,
    Message,
    NotificationFilter,
    Reply,
    TeamsActivity,
    Update,
    WindowsNotice,
)
from assistant.console_requests import Provider, State, request
from assistant.feed_origin import App
from assistant.feed_sources import (
    Attention,
    ChatMessageSource,
    ChatTicketSource,
    ConsoleSource,
    FeedSource,
    ReplySource,
    SourceKind,
    UpdateSource,
    attention,
    chat_message,
    evidence,
    key,
    listed,
    origin,
    triage_evidence,
)
from assistant.system_notices import NoticeKey
from tests.test_console_inbox import event

CHAT = Conversation("chat", "Planning")
FIRST = Message("chat", "one", "Anna", "Review the figures", 1, 1)
SECOND = Message("chat", "two", "Anna", "And the budget", 2, 2)
ACTIVITY = Update(TeamsActivity("mention"), "Anna mentioned you", "Budget", "Teams", 3)
MAIL = Update(WindowsNotice(NoticeKey(1, 2), "Microsoft.OutlookForWindows"), "Forecast", "Figures", "Outlook", 4)
OTHER = Update(WindowsNotice(NoticeKey(3, 4), "contoso"), "Deploy", "Finished", "Contoso", 5)
REPLY = Reply("reply", "chat", "Anna", "On it", 6)
QUESTION = request(Provider.CLAUDE, event(Provider.CLAUDE), "question", 7)


def test_each_source_variant_owns_its_attention_key_origin_and_evidence() -> None:
    # Defect: the feed and triage disagree about a variant, e.g. a direct console
    # question or an in-flight send is quoted to triage, or a source is badged wrongly.
    table: tuple[tuple[FeedSource, Attention, SourceKind, App, int], ...] = (
        (ChatTicketSource(ChatTicket("chat", (FIRST, SECOND)), CHAT), Attention.TRIAGE, SourceKind.CHAT, App.TEAMS, 2),
        (ChatMessageSource(FIRST, CHAT, unseen=True), Attention.TRIAGE, SourceKind.CHAT_MESSAGE, App.TEAMS, 1),
        (ChatMessageSource(FIRST, CHAT, unseen=False), Attention.RESOLVED, SourceKind.CHAT_MESSAGE, App.TEAMS, 0),
        (UpdateSource(ACTIVITY, handled=False), Attention.TRIAGE, SourceKind.ACTIVITY, App.TEAMS, 1),
        (UpdateSource(MAIL, handled=False), Attention.TRIAGE, SourceKind.WINDOWS, App.OUTLOOK, 1),
        (UpdateSource(OTHER, handled=True), Attention.RESOLVED, SourceKind.WINDOWS, App.WINDOWS, 0),
        (ReplySource(REPLY), Attention.SETTLING, SourceKind.REPLY, App.TEAMS, 0),
        (ReplySource(replace(REPLY, delivery=Delivery.SENDING)), Attention.SETTLING, SourceKind.REPLY, App.TEAMS, 0),
        (ReplySource(replace(REPLY, delivery=Delivery.UNKNOWN)), Attention.TRIAGE, SourceKind.REPLY, App.TEAMS, 1),
        (ReplySource(replace(REPLY, delivery=Delivery.FAILED)), Attention.TRIAGE, SourceKind.REPLY, App.TEAMS, 1),
        (ReplySource(replace(REPLY, delivery=Delivery.OBSERVED)), Attention.RESOLVED, SourceKind.REPLY, App.TEAMS, 0),
        (ReplySource(replace(REPLY, delivery=Delivery.REVIEWED)), Attention.RESOLVED, SourceKind.REPLY, App.TEAMS, 0),
        (ConsoleSource(QUESTION), Attention.DIRECT, SourceKind.CONSOLE, App.CLAUDE, 0),
        (ConsoleSource(replace(QUESTION, state=State.INFORMATION)), Attention.TRIAGE, SourceKind.CONSOLE, App.CLAUDE, 1),
        (ConsoleSource(replace(QUESTION, state=State.ANSWERED)), Attention.RESOLVED, SourceKind.CONSOLE, App.CLAUDE, 0),
        (ConsoleSource(replace(QUESTION, state=State.EXPIRED)), Attention.RESOLVED, SourceKind.CONSOLE, App.CLAUDE, 0),
    )
    for source, expected, kind, app, quoted in table:
        assert (attention(source), key(source).kind, origin(source).app, len(evidence(source))) == (expected, kind, app, quoted), source
        assert all(item.origin == origin(source) for item in evidence(source))


def test_pending_listing_keeps_filtered_notices_unhandled_and_replies_until_they_retire() -> None:
    # Defect: filtering a notice handles it, or pending work drops a delivered reply before the person sees it.
    feed = Feed(
        conversations=(CHAT,),
        followed=("chat",),
        messages=(FIRST,),
        updates=(MAIL, OTHER),
        replies=(replace(REPLY, delivery=Delivery.OBSERVED),),
        notification_filter=NotificationFilter(frozenset({"contoso"})),
    )
    requests = (QUESTION, replace(QUESTION, identity="answered", state=State.ANSWERED))
    pending = tuple(key(source) for source in listed(feed, requests, history=False))
    # The filtered notice and the waiting question are visible elsewhere, never quoted to triage.
    assert [item.kind for item in triage_evidence(feed, requests)] == [SourceKind.CHAT, SourceKind.WINDOWS]
    assert [item.kind for item in pending] == [SourceKind.CHAT, SourceKind.WINDOWS, SourceKind.REPLY, SourceKind.CONSOLE]
    history = tuple(listed(feed, requests, history=True))
    assert [attention(source) for source in history if isinstance(source, UpdateSource)] == [Attention.TRIAGE, Attention.TRIAGE]
    assert len(history) == 6


def test_chat_evidence_names_its_exact_message_for_research() -> None:
    # Defect: research resolves evidence to another message and quotes the wrong conversation's history.
    other = Message("other", "three", "Sam", "Lunch?", 3, 3)
    feed = Feed(conversations=(CHAT,), followed=("chat", "other"), messages=(FIRST, other))
    quoted = {item.body: item.identity for item in triage_evidence(feed, ())}
    assert chat_message(feed, quoted["Lunch?"]) == other and chat_message(feed, quoted["Review the figures"]) == FIRST
    assert chat_message(feed, "chat:missing") is None
