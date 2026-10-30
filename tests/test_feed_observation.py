"""Each observer's report joins one feed snapshot, and card commands reach their source's owner."""

from assistant.communications import Feed, Handle, NotificationFilter, OpenChat, Update, WindowsNotice
from assistant.console_requests import Provider, request
from assistant.feed_observation import (
    ConsolesObserved,
    FeedChange,
    FeedObservation,
    FeedSnapshot,
    NoticesObserved,
    TeamsObserved,
    ToNotices,
    ToTeams,
    TriageInput,
    TriageObserved,
    observe,
    route,
)
from assistant.feed_triage import Assessment, Board
from assistant.notification_sources import HandleNotice, Notices, OpenApp, ReopenNotice, ToggleApp, joined
from assistant.system_notices import Notice, NoticeKey
from tests.communications_fixture import communication_feed
from tests.test_console_inbox import event


def test_each_report_keeps_the_others_and_hands_triage_the_current_sources() -> None:
    # Defects: one observer's report drops another's from the snapshot, triage
    # assesses stale sources, or publishing a triage board asks triage again.
    teams = communication_feed()
    notices = Notices(
        updates=(Update(WindowsNotice(NoticeKey(1, 2), "mail"), "Review", "Budget", "Outlook", 3),),
        filter=NotificationFilter(frozenset({"chat-app"})),
    )
    requests = (request(Provider.CLAUDE, event(Provider.CLAUDE), "owned", 5),)
    board = Board(enabled=True, items=(Assessment("budget", (), "Review budget", "", "", "", 1, 4),))
    first = observe(FeedObservation(), NoticesObserved(notices))
    assert first.assess == TriageInput(joined(Feed(), notices), ())
    second = observe(first.observation, ConsolesObserved(requests))
    assert second.assess == TriageInput(first.observation.snapshot.communications, requests)
    third = observe(second.observation, TeamsObserved(teams))
    assert third.assess == TriageInput(joined(teams, notices), requests)
    fourth = observe(third.observation, TriageObserved(board))
    assert fourth == FeedChange(FeedObservation(teams, notices, FeedSnapshot(joined(teams, notices), requests, board)), None)
    revised = Notices(handled=notices.handled, filter=NotificationFilter(frozenset()))
    assert observe(fourth.observation, NoticesObserved(revised)).observation.snapshot == FeedSnapshot(joined(teams, revised), requests, board)


def test_windows_notice_commands_stay_with_the_notice_owner() -> None:
    # Defect: handling a notice waits behind, or is refused by, the Teams worker.
    notice = Notice(NoticeKey(1, 2), "mail", "Outlook", "Review", "Budget")
    for command in (HandleNotice(notice), ReopenNotice(("windows", "1:2")), OpenApp("mail"), ToggleApp("mail")):
        assert route(command) == ToNotices(command)
    for command in (OpenChat("19:one@thread.v2"), Handle(())):
        assert route(command) == ToTeams(command)
