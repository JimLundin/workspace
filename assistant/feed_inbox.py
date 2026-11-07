"""The inbox's pending feed: each observer's latest report, triaged as it changes.

Teams arrives from the assistant's own browser worker; Windows notifications
arrive from the desktop, which observes them, over the link. Either report
replaces that observer's last and the whole feed goes to triage.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from assistant.communications import Feed
from assistant.feed_sources import NoticesObserved, PendingFeed, TeamsObserved, observe
from assistant.notification_sources import NotificationSources, NotificationState
from assistant.state_store import SavedState
from cell import Cell
from winapi.system_notices import Observed

type Assess = Callable[[PendingFeed], None]


@dataclass(frozen=True, slots=True)
class FeedInbox:
    _sources: NotificationSources
    _assess: Assess
    _feed: Cell[PendingFeed] = field(default_factory=lambda: Cell(PendingFeed()), init=False, repr=False)
    """Replaced whole under the lock."""
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def load(cls, notifications: SavedState[NotificationState], assess: Assess) -> FeedInbox:
        """The inbox with the saved notification choices loaded."""
        sources = NotificationSources(notifications)
        sources.load()
        return cls(sources, assess)

    def communications(self, feed: Feed) -> None:
        """Any thread: Teams' latest conversations."""
        with self._lock:
            current = self._feed.update(lambda pending: observe(pending, TeamsObserved(feed)))
        self._assess(current)

    def notices(self, observation: Observed) -> None:
        """Any thread: the desktop's latest Windows notifications; unchanged ones aren't triaged again."""
        with self._lock:
            if not self._sources.observe(observation):
                return
            notices = NoticesObserved(self._sources.state)
            current = self._feed.update(lambda pending: observe(pending, notices))
        self._assess(current)
