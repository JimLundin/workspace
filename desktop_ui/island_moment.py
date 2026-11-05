"""Which moment holds the island, and how a notice comes and goes: pure decisions from observed facts.

A moment takes the island over (docs/toolbar-design.md, "What the bar shows"):
dictation, live from you, wins over a question waiting on you, and both win
over a notice, the agent's news for you. A notice waits while a higher moment
or an expansion holds the island, shows for a few seconds once it's free, stays
while the pointer is over it, and then collapses into the bell as unread.
"""

from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Final, assert_never

from desktop_ui.agent_progress import Phase

SHOWN: Final = 6.0  # Seconds a notice holds the island.
LINGER: Final = 1.5  # Seconds it stays after the pointer leaves.
WAIT: Final = 30.0  # Seconds an announcement waits behind a higher moment before it goes straight to the bell.
RECENT: Final = 5  # Notices the bell lists.


@dataclass(frozen=True, slots=True)
class Notice:
    """The agent's news: a finished reply or a canvas finding, and the canvas item it opens."""

    identity: str
    title: str
    text: str
    target: str | None  # None opens the canvas as it is.
    at: float  # When it happened, for the bell's newest-first order.
    question: bool = field(default=False, kw_only=True)  # A question the bell already counts and lists as one.


@dataclass(frozen=True, slots=True)
class Waiting:
    notice: Notice
    since: float


@dataclass(frozen=True, slots=True)
class Showing:
    notice: Notice
    until: float


@dataclass(frozen=True, slots=True)
class Held:
    """Under the pointer: it stays until the pointer leaves."""

    notice: Notice


type Presenting = Waiting | Showing | Held


@dataclass(frozen=True, slots=True)
class Notices:
    known: frozenset[str] = frozenset()  # Identities already announced.
    recent: tuple[Notice, ...] = ()  # Newest last.
    unread: frozenset[str] = frozenset()
    presenting: Presenting | None = None


class Live(Enum):
    DICTATION = auto()
    QUESTION = auto()


type Moment = Live | Notice


def observe(notices: Notices, current: tuple[Notice, ...], now: float) -> Notices:
    """Announce what is new since the last observation; the newest new notice is presented next."""
    new = tuple(notice for notice in current if notice.identity not in notices.known)
    if not new:
        return replace(notices, known=notices.known | frozenset(notice.identity for notice in current))
    recent = (*(notice for notice in notices.recent if notice.identity not in {each.identity for each in new}), *new)[-RECENT:]
    kept = frozenset(notice.identity for notice in recent)
    return Notices(
        notices.known | frozenset(notice.identity for notice in current),
        recent,
        (notices.unread | frozenset(notice.identity for notice in new if not notice.question)) & kept,
        Waiting(new[-1], now),
    )


def advance(notices: Notices, *, blocked: bool, now: float) -> Notices:
    """The clock and the island's other owners move the presented notice on.

    `blocked` is a higher moment, or an expansion the person opened, holding the island.
    """
    presenting = notices.presenting
    match presenting:
        case None:
            return notices
        case Waiting(notice=notice, since=since):
            following: Presenting | None = None if now - since >= WAIT else presenting if blocked else Showing(notice, now + SHOWN)
        case Showing(notice=notice, until=until):
            following = Waiting(notice, now) if blocked else None if until <= now else presenting
        case Held(notice=notice):
            following = Waiting(notice, now) if blocked else presenting
        case _:
            assert_never(presenting)
    return notices if following == presenting else replace(notices, presenting=following)


def hover(notices: Notices, *, inside: bool, now: float) -> Notices:
    match notices.presenting, inside:
        case Showing(notice=notice), True:
            return replace(notices, presenting=Held(notice))
        case Held(notice=notice), False:
            return replace(notices, presenting=Showing(notice, now + LINGER))
        case _:
            return notices


def read(notices: Notices, identities: frozenset[str]) -> Notices:
    """Opened or dismissed: these leave the unread count, and a presented one leaves the island."""
    presenting = notices.presenting
    match presenting:
        case Waiting(notice=notice) | Showing(notice=notice) | Held(notice=notice) if notice.identity in identities:
            presenting = None
        case _:
            pass
    return replace(notices, unread=notices.unread - identities, presenting=presenting)


def shown(notices: Notices) -> Notice | None:
    match notices.presenting:
        case Showing(notice=notice) | Held(notice=notice):
            return notice
        case Waiting() | None:
            return None
        case _:
            assert_never(notices.presenting)


def unread(notices: Notices) -> int:
    """Unread notices for the bell; the one on the island now isn't counted twice."""
    showing = shown(notices)
    return len(notices.unread - ({showing.identity} if showing is not None else set()))


def moment(*, dictating: bool, asking: bool, notices: Notices) -> Moment | None:
    if dictating:
        return Live.DICTATION
    if asking:
        return Live.QUESTION
    return shown(notices)


@dataclass(frozen=True, slots=True)
class Asked:
    """A question waiting on you, as the bell lists it."""

    phase: Phase


type Row = Asked | Notice


def rows(questions: tuple[Phase, ...], notices: Notices) -> tuple[Row, ...]:
    """The bell's list: questions and recent notices together, newest first, a handful at most."""

    def at(row: Row) -> float:
        match row:
            case Asked(phase=phase):
                return phase.turn.created_at
            case Notice(at=when):
                return when
            case _:
                assert_never(row)

    listed: tuple[Row, ...] = (*(Asked(phase) for phase in questions), *(notice for notice in notices.recent if not notice.question))
    return tuple(sorted(listed, key=at, reverse=True))[:RECENT]


@dataclass(frozen=True, slots=True)
class Inbox:
    """The bell's list, opened in the island."""

    rows: tuple[Row, ...]
