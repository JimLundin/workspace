"""The assistant's inbox feed: Teams and the desktop's Windows notices, triaged together."""

from pathlib import Path

from assistant.communications import WindowsNotice
from assistant.feed_inbox import FeedInbox
from assistant.feed_sources import PendingFeed
from assistant.notification_sources import NOTIFICATION_STATE
from assistant.state_store import SavedState
from tests.communications_fixture import communication_feed
from tests.test_communications_service import LocalCipher
from winapi.system_notices import Notice, NoticeKey, Observed


class Triaged:
    """Each feed triage was handed, in order."""

    def __init__(self) -> None:
        self.feeds: tuple[PendingFeed, ...] = ()

    def assess(self, feed: PendingFeed) -> None:
        self.feeds = (*self.feeds, feed)


def test_app_arrivals_reach_triage_joined(tmp_path: Path) -> None:
    # Defect: triage sees Teams work without the Windows notices it must assess
    # with it, or an unchanged notice observation is triaged again.
    triage = Triaged()
    inbox = FeedInbox.load(SavedState(tmp_path / "notifications.bin", NOTIFICATION_STATE, cipher=LocalCipher()), triage.assess)
    notice = Notice(NoticeKey(11, 100), "owned", "Mail", "Review this", "Immediate fictional notice")
    inbox.notices(Observed((notice,)))
    inbox.communications(communication_feed())
    assert triage.feeds[-1].teams.messages
    assert any(item.source == WindowsNotice(notice.key, notice.app_id) for item in triage.feeds[-1].notices.updates)
    count = len(triage.feeds)
    inbox.notices(Observed((notice,)))
    assert len(triage.feeds) == count
