"""Each observer's report joins the feed triage assesses without dropping another's."""

from assistant.communications import Feed, NotificationFilter, Update, WindowsNotice
from assistant.feed_observation import FeedObservation, NoticesObserved, TeamsObserved, observe
from assistant.notification_sources import Notices, joined
from assistant.system_notices import NoticeKey
from tests.communications_fixture import communication_feed


def test_each_report_keeps_the_others_in_the_joined_feed() -> None:
    # Defect: one observer's report drops another's, or triage sees notices
    # without Teams work or a stale notification filter.
    teams = communication_feed()
    notices = Notices(
        updates=(Update(WindowsNotice(NoticeKey(1, 2), "mail"), "Review", "Budget", "Outlook", 3),),
        filter=NotificationFilter(frozenset({"chat-app"})),
    )
    first = observe(FeedObservation(), NoticesObserved(notices))
    assert first.communications == joined(Feed(), notices)
    second = observe(first, TeamsObserved(teams))
    assert second == FeedObservation(teams, notices, joined(teams, notices))
    revised = Notices(handled=notices.handled, filter=NotificationFilter(frozenset()))
    assert observe(second, NoticesObserved(revised)) == FeedObservation(teams, revised, joined(teams, revised))
