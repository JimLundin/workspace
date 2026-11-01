"""Windows notice observations retain loaded attention choices apart from the Teams worker."""

from dataclasses import replace
from pathlib import Path

from assistant.communications import update_fingerprint
from assistant.communications_state import StoredAcknowledgement
from assistant.feed_sources import PendingFeed, needs_attention
from assistant.notification_sources import NOTIFICATION_STATE, NotificationSources, NotificationState, notice_update
from assistant.state_store import SavedState
from tests.test_communications_service import LocalCipher
from winapi.system_notices import Notice, NoticeKey, Observed


def test_loaded_attention_choices_survive_observations_and_only_handle_the_saved_revision(tmp_path: Path) -> None:
    # Defects: load drops saved handling marks or filters; an observation loses
    # history/choices, reports unchanged arrivals as new, or keeps a revision handled.
    notice = Notice(NoticeKey(7, 11_644_473_601_0000000), "Mail", "Mail", "Invitation", "Review this meeting")
    hidden = Notice(NoticeKey(9, 11_644_473_602_0000000), "Security", "Security", "Scan finished", "Nothing found")
    captured = notice_update(notice)
    saved = NotificationState(("Security",), (StoredAcknowledgement(*captured.key, update_fingerprint(captured)),))
    store = SavedState(tmp_path / "notifications.bin", NOTIFICATION_STATE, cipher=LocalCipher())
    store.write(saved)
    notices = NotificationSources(store)
    notices.load()
    assert notices.observe(Observed((notice, hidden)))
    assert not notices.observe(Observed((notice, hidden)))
    assert not notices.observe(Observed(()))
    feed = PendingFeed(notices=notices.state)
    assert feed.notices.updates == (captured, notice_update(hidden))
    assert not needs_attention(feed, captured)
    assert all(mark.key != notice_update(hidden).key for mark in feed.notices.handled)
    assert not needs_attention(feed, notice_update(hidden))

    revised = replace(notice, body="Review the revised meeting")
    assert notices.observe(Observed((revised,)))
    feed = PendingFeed(notices=notices.state)
    assert feed.notices.updates == (notice_update(revised), notice_update(hidden))
    assert needs_attention(feed, notice_update(revised))
    assert notices.state.filter.hidden == frozenset({"Security"})
    assert store.read() == saved
