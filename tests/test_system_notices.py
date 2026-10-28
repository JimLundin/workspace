from datetime import UTC, datetime
from unittest import TestCase

from assistant.system_notices import Notice, NoticeKey, Observed, arrivals, creation_time


def notice(identity: int, created: int, body: str = 'Message') -> Notice:
    return Notice(NoticeKey(identity, created), 'app', 'Messages', 'New message', body)


def test_existing_notification_history_is_seeded_without_banner_burst() -> None:
    assert arrivals(None, Observed((notice(1, 10), notice(2, 20)))) == ()


def test_notification_updates_and_reused_ids_arrive_once() -> None:
    initial = Observed((notice(1, 10), notice(2, 20)))
    updated = Observed((notice(1, 30), notice(2, 20, 'Changed'), notice(3, 40)))
    assert arrivals(initial, updated) == updated.notices
    assert arrivals(updated, updated) == ()


def test_removing_a_source_notification_does_not_replay_its_neighbors() -> None:
    initial = Observed((notice(1, 10), notice(2, 20)))
    assert arrivals(initial, Observed((notice(2, 20),))) == ()


def test_native_datetime_projection_retains_notification_identity_and_rejects_missing_timezone() -> None:
    assert creation_time(datetime(1601, 1, 1, 0, 0, 1, 123456, tzinfo=UTC)) == 11234560
    with TestCase().assertRaises(OSError):
        creation_time(datetime(2026, 1, 1))
    with TestCase().assertRaises(OSError):
        creation_time('2026-01-01')
