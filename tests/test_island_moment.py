"""The island's moment policy and a notice's lifetime, from pure observations."""

from contracts.agent_session import Begin, Session, transition
from desktop_ui.agent_progress import phases
from desktop_ui.island_moment import (
    LINGER,
    SHOWN,
    WAIT,
    Asked,
    Live,
    Notice,
    Notices,
    advance,
    hover,
    moment,
    observe,
    read,
    rows,
    shown,
    unread,
)
from tests.agent_requests import asked

REPLY = Notice("reply:1", "Compare the budget sheets", "Revenue is up 4%.", "reply:1", 10)
FINDING = Notice("canvas:result:2", "Budget checked", "Approved totals match.", "result:2", 20)


def announced(*current: Notice, now: float = 100) -> Notices:
    return advance(observe(Notices(), current, now), blocked=False, now=now)


def test_dictation_and_a_question_hold_the_island_and_the_notice_shows_after_them() -> None:
    # Defects: a notice interrupts dictation or a waiting question, is lost while
    # they hold the island, or comes back with only what was left of its time.
    waiting = advance(observe(Notices(), (REPLY,), 100), blocked=True, now=100)
    assert moment(dictating=True, asking=True, notices=waiting) is Live.DICTATION
    assert moment(dictating=False, asking=True, notices=waiting) is Live.QUESTION
    assert moment(dictating=False, asking=False, notices=waiting) is None
    interrupted = advance(advance(waiting, blocked=False, now=101), blocked=True, now=104)
    assert shown(interrupted) is None
    resumed = advance(interrupted, blocked=False, now=110)
    assert moment(dictating=False, asking=False, notices=resumed) == REPLY
    assert shown(advance(resumed, blocked=False, now=110 + SHOWN - 0.1)) == REPLY


def test_a_shown_notice_collapses_into_the_bell_as_unread() -> None:
    # Defects: the notice never leaves the island, leaves without counting as
    # unread, or is counted in the bell while it is still on the island.
    notices = announced(REPLY)
    assert (shown(notices), unread(notices)) == (REPLY, 0)
    collapsed = advance(notices, blocked=False, now=100 + SHOWN)
    assert (shown(collapsed), unread(collapsed)) == (None, 1)


def test_the_pointer_holds_a_notice_and_leaving_lets_it_go_shortly_after() -> None:
    # Defects: hovering doesn't stop the expiry, or leaving never restarts it.
    held = advance(hover(announced(REPLY), inside=True, now=101), blocked=False, now=100 + SHOWN + 30)
    assert shown(held) == REPLY
    left = hover(held, inside=False, now=200)
    assert shown(advance(left, blocked=False, now=200 + LINGER - 0.1)) == REPLY
    assert shown(advance(left, blocked=False, now=200 + LINGER)) is None


def test_a_notice_that_waits_too_long_goes_straight_to_the_bell() -> None:
    # Defect: a notice held back by a long dictation pops up long after the fact.
    waiting = advance(observe(Notices(), (REPLY,), 100), blocked=True, now=100)
    stale = advance(advance(waiting, blocked=True, now=100 + WAIT), blocked=False, now=100 + WAIT + 1)
    assert (shown(stale), unread(stale)) == (None, 1)


def test_only_new_notices_are_announced_and_the_newest_is_presented() -> None:
    # Defects: every session refresh re-announces old replies, or the older of
    # two simultaneous announcements takes the island.
    notices = announced(REPLY, FINDING)
    assert shown(notices) == FINDING
    again = advance(observe(read(notices, frozenset({FINDING.identity})), (REPLY, FINDING), 101), blocked=False, now=101)
    assert (shown(again), unread(again)) == (None, 1)
    revised = Notice("canvas:result:3", "Budget checked", "Forecast totals differ.", "result:2", 30)
    assert shown(advance(observe(again, (REPLY, revised), 102), blocked=False, now=102)) == revised


def test_opening_a_notice_reads_it_and_the_bell_lists_questions_and_notices_newest_first() -> None:
    # Defects: an opened notice stays on the island or in the count, or the list
    # is out of order or unbounded.
    notices = announced(REPLY, FINDING)
    opened = read(notices, frozenset({FINDING.identity}))
    assert (shown(opened), unread(opened)) == (None, 1)
    session = transition(transition(Session(identity="s"), Begin("Check the sheets", 15)), asked("sheet", "Which sheet?", "", 16))
    question = next(phases(session))
    assert rows((question,), opened) == (FINDING, Asked(question), REPLY)
    many = announced(*(Notice(f"n{index}", "Update", "", None, index) for index in range(8)))
    assert [row.identity for row in rows((), many) if isinstance(row, Notice)] == ["n7", "n6", "n5", "n4", "n3"]
