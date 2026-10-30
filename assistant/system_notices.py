"""Native notification identities and quiet arrival baselines for Workspace's inbox."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto


class Access(Enum):
    ALLOWED = auto()
    DENIED = auto()
    UNAVAILABLE = auto()


class Banners(Enum):
    UNMANAGED = auto()
    SUPPRESSED = auto()
    PARTIAL = auto()


@dataclass(frozen=True, slots=True)
class NoticeKey:
    identity: int
    created: int


@dataclass(frozen=True, slots=True)
class Notice:
    key: NoticeKey
    app_id: str
    app_name: str
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class Observed:
    notices: tuple[Notice, ...]
    banners: Banners = Banners.UNMANAGED


@dataclass(frozen=True, slots=True)
class Unavailable:
    access: Access


type Observation = Observed | Unavailable


def creation_time(value: object) -> int:
    """The pinned WinRT projection returns an aware Python datetime."""
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise OSError("Windows returned an invalid notification timestamp.")
    return (value - datetime(1601, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1) * 10


def arrivals(previous: Observed | None, current: Observed) -> tuple[Notice, ...]:
    """Seed history quietly; changed/reused IDs are new, failed reads are not history."""
    if previous is None:
        return ()
    known = {notice.key: notice for notice in previous.notices}
    return tuple(notice for notice in current.notices if known.get(notice.key) != notice)
