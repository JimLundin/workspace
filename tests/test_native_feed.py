"""Native arrivals and handling do not wait for a Teams navigation to finish."""

from dataclasses import replace

from assistant.communications import Acknowledgement, Feed, Handle, HandleNotice, NotificationFilters, Reopen, notice_update, update_fingerprint
from assistant.native_feed import NativeFeed, acted, forward, observed, project
from assistant.system_notices import Notice, NoticeKey, Observed


def test_native_arrival_and_handling_survive_stale_worker_snapshots_and_absent_center_rows() -> None:
    notice = Notice(NoticeKey(11, 100), "owned", "Mail", "Review this", "Fictional notification")
    update = notice_update(notice)
    worker = Feed()
    state = observed(NativeFeed(), Observed((notice,)))
    visible = project(state, worker)
    assert visible.pending_update(update)
    command = Handle((Acknowledgement(update.key, update_fingerprint(update)),))
    assert forward(visible, command) == (HandleNotice(notice),)
    changed = acted(state, visible, command)
    assert changed.dismiss == (notice.key,)
    state = observed(changed.state, Observed(()))
    assert not project(state, worker).pending_update(update)
    state = acted(state, visible, Reopen(update.key)).state
    handled_worker = replace(visible, handled=command.marks)
    assert project(state, handled_worker).pending_update(update)
    state = acted(state, visible, command).state
    assert not project(state, worker).pending_update(update)


def test_changed_notice_revision_cannot_be_handled_by_a_stale_action_and_app_filter_is_immediate() -> None:
    old = Notice(NoticeKey(11, 100), "owned", "Mail", "Review this", "First revision")
    old_update = notice_update(old)
    new = replace(old, body="Second revision")
    state = observed(NativeFeed(), Observed((new,)))
    feed = project(state, Feed())
    command = Handle((Acknowledgement(old_update.key, update_fingerprint(old_update)),))
    assert not acted(state, feed, command).dismiss
    assert project(acted(state, feed, command).state, Feed()).pending_update(notice_update(new))
    state = acted(state, feed, NotificationFilters(("owned",))).state
    assert project(state, Feed()).muted_apps == ("owned",)
