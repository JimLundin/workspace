from dataclasses import dataclass
from typing import Final, assert_never

ANSWER_SLACK_MS: Final = 1000
"""A hook event this much older than raw input can still be the same key: Windows
lets a hook run for up to 1000 ms (the LowLevelHooksTimeout cap) before posting it."""
SUSPECT_MS: Final = 250
"""Unanswered raw input this old starts a probe."""
PROBE_MS: Final = 1000
"""A probe the hook has not seen after this long means the hook is gone. Slow hooks
earlier in the chain can each hold an event for up to LowLevelHooksTimeout."""


ANSWERED = sentinel("ANSWERED")
"""The hook has seen every keyboard input so far."""


@dataclass(frozen=True, slots=True)
class Unanswered:
    since: int


@dataclass(frozen=True, slots=True)
class Probing:
    since: int
    sent: int


type Watch = ANSWERED | Unanswered | Probing


@dataclass(frozen=True, slots=True)
class Probe:
    since: int


@dataclass(frozen=True, slots=True)
class Reinstall:
    since: int
    last_hook: int | None
    """The newest event the dead hook saw, if any."""


def offset(later: int, earlier: int) -> int:
    return (later - earlier + 0x8000_0000) % 0x1_0000_0000 - 0x8000_0000


def keyboard_input(watch: Watch, tick: int) -> Watch:
    match watch:
        case Unanswered() | Probing():
            return watch
        case _ if watch is ANSWERED:
            return Unanswered(tick)
        case _:
            assert_never(watch)


def assess(
    watch: Watch, hook: int | None, now: int
) -> Watch | Probe | Reinstall:
    match watch:
        case Unanswered(since=since) | Probing(since=since) if (
            hook is not None and offset(since, hook) <= ANSWER_SLACK_MS
        ):
            return ANSWERED
        case Unanswered(since=since):
            return Probe(since) if offset(now, since) >= SUSPECT_MS else watch
        case Probing(since=since, sent=sent):
            return (
                Reinstall(since, hook)
                if offset(now, sent) >= PROBE_MS
                else watch
            )
        case _ if watch is ANSWERED:
            return watch
        case _:
            assert_never(watch)


def probed(probe: Probe, now: int, *, sent: bool) -> Watch:
    return Probing(probe.since, now) if sent else ANSWERED
