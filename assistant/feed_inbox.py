"""The inbox's pending feed: each observer's latest report, triaged as it changes.

Teams arrives from the assistant's own browser worker; Windows notifications
arrive from the desktop, which observes them, over the link. Either report
replaces that observer's last and the whole feed goes to triage.
"""

import threading
from collections.abc import Callable

from assistant.communications import Feed
from assistant.feed_sources import NoticesObserved, PendingFeed, TeamsObserved, observe
from assistant.notification_sources import NotificationSources, NotificationState
from assistant.state_store import SavedState
from winapi.system_notices import Observed

type Assess = Callable[[PendingFeed], None]


class FeedInbox:
    __slots__ = ("_assess", "_feed", "_lock", "_sources")

    def __init__(self, notifications: SavedState[NotificationState], assess: Assess) -> None:
        self._sources = NotificationSources(notifications)
        self._sources.load()
        self._assess = assess
        self._feed = PendingFeed()
        self._lock = threading.Lock()

    def communications(self, feed: Feed) -> None:
        """Any thread: Teams' latest conversations."""
        with self._lock:
            self._feed = observe(self._feed, TeamsObserved(feed))
            current = self._feed
        self._assess(current)

    def notices(self, observation: Observed) -> None:
        """Any thread: the desktop's latest Windows notifications; unchanged ones aren't triaged again."""
        with self._lock:
            if not self._sources.observe(observation):
                return
            self._feed = observe(self._feed, NoticesObserved(self._sources.state))
            current = self._feed
        self._assess(current)
