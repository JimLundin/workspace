"""Windows notices and the notification filter are owned apart from the Teams worker."""

from dataclasses import replace
from pathlib import Path

from assistant.communications import Feed
from assistant.notification_sources import (
    NOTIFICATION_STATE,
    HandleNotice,
    Notices,
    NotificationSources,
    ReopenNotice,
    ToggleApp,
    handled,
    joined,
    notice_update,
    observed,
)
from assistant.state_store import SavedState
from tests.test_communications_service import LocalCipher
from winapi.system_notices import Notice, NoticeKey, Observed


def owner(path: Path, dismissed: list[NoticeKey]) -> NotificationSources:
    def dismiss(key: NoticeKey) -> None:
        # Defect: Windows loses the notice before its handling mark is durable.
        assert result.store.read().handled
        dismissed.append(key)

    result = NotificationSources(SavedState(path, NOTIFICATION_STATE, cipher=LocalCipher()), dismiss)
    result.load()
    return result


def test_handling_is_saved_before_dismissal_and_survives_restart_and_reobservation(tmp_path: Path) -> None:
    dismissed: list[NoticeKey] = []
    notices = owner(tmp_path / "notifications.bin", dismissed)
    notice = Notice(NoticeKey(7, 11_644_473_601_0000000), "Mail", "Mail", "Invitation", "Review this meeting")
    assert notices.observe(Observed((notice,)))
    update = notice_update(notice)
    assert joined(Feed(), notices.state).needs_attention(update)
    assert notices.command(HandleNotice(notice))
    assert dismissed == [notice.key]
    restarted = owner(tmp_path / "notifications.bin", dismissed)
    restarted.observe(Observed((notice,)))
    assert not joined(Feed(), restarted.state).needs_attention(update)
    assert restarted.command(ReopenNotice(update.key))
    assert joined(Feed(), owner(tmp_path / "notifications.bin", dismissed).state).pending_update(update)


def test_a_notice_handled_from_the_bar_before_the_feed_observed_it_is_still_saved(tmp_path: Path) -> None:
    dismissed: list[NoticeKey] = []
    notices = owner(tmp_path / "notifications.bin", dismissed)
    notice = Notice(NoticeKey(8, 11_644_473_602_0000000), "Mail", "Mail", "New update", "Check it")
    assert notices.command(HandleNotice(notice))
    assert dismissed == [notice.key]
    assert not joined(Feed(), notices.state).pending_update(notice_update(notice))


def test_a_stale_handling_target_leaves_the_revised_notice_pending() -> None:
    old = Notice(NoticeKey(11, 100), "owned", "Mail", "Review this", "First revision")
    new = replace(old, body="Second revision")
    state = handled(observed(Notices(), Observed((new,))), old)
    assert joined(Feed(), state).needs_attention(notice_update(new))


def test_hiding_an_app_toggles_survives_reload_and_never_marks_its_work_handled(tmp_path: Path) -> None:
    notices = owner(tmp_path / "notifications.bin", [])
    notice = Notice(NoticeKey(9, 100), "Security", "Security", "Scan finished", "Nothing found")
    notices.observe(Observed((notice,)))
    assert notices.command(ToggleApp("Mail")) and notices.command(ToggleApp("Security"))
    assert notices.command(ToggleApp("Mail"))
    restarted = owner(tmp_path / "notifications.bin", [])
    restarted.observe(Observed((notice,)))
    feed = joined(Feed(), restarted.state)
    assert feed.notification_filter.hidden == {"Security"}
    assert feed.pending_update(notice_update(notice)) and not feed.needs_attention(notice_update(notice))
