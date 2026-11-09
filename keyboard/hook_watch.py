"""Decide when Windows has silently removed the low-level keyboard hook.

Windows drops a hook that misses LowLevelHooksTimeout and tells nobody. Raw
keyboard input still reaches the layout's window, so keyboard input the hook
never saw is the evidence, and a probe key the hook should see confirms it.
Ticks are Windows message times in milliseconds, which wrap at 2**32.
"""

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
    """Raw keyboard input arrived at `since` and the hook has not seen it yet."""

    since: int


@dataclass(frozen=True, slots=True)
class Probing:
    """A probe key was sent at `sent` to check the unanswered input."""

    since: int
    sent: int


type Watch = ANSWERED | Unanswered | Probing


@dataclass(frozen=True, slots=True)
class Probe:
    """Send a probe key the hook should see; Windows may refuse it."""

    since: int


@dataclass(frozen=True, slots=True)
class Reinstall:
    """The hook missed real input and the probe: replace it."""

    since: int
    last_hook: int | None
    """The newest event the dead hook saw, if any."""


def offset(later: int, earlier: int) -> int:
    """Signed milliseconds from `earlier` to `later` across the 2**32 wrap."""
    return (later - earlier + 0x8000_0000) % 0x1_0000_0000 - 0x8000_0000


def keyboard_input(watch: Watch, tick: int) -> Watch:
    """Raw keyboard input arrived; only the earliest unanswered input counts."""
    match watch:
        case Unanswered() | Probing():
            return watch
        case _ if watch is ANSWERED:
            return Unanswered(tick)
        case _:
            assert_never(watch)


def assess(watch: Watch, hook: int | None, now: int) -> Watch | Probe | Reinstall:
    """`hook` is the newest event time the hook has seen; `now` is the current tick."""
    match watch:
        case Unanswered(since=since) | Probing(since=since) if hook is not None and offset(since, hook) <= ANSWER_SLACK_MS:
            return ANSWERED
        case Unanswered(since=since):
            return Probe(since) if offset(now, since) >= SUSPECT_MS else watch
        case Probing(since=since, sent=sent):
            return Reinstall(since, hook) if offset(now, sent) >= PROBE_MS else watch
        case _ if watch is ANSWERED:
            return watch
        case _:
            assert_never(watch)


def probed(probe: Probe, now: int, *, sent: bool) -> Watch:
    """Windows refuses probes on the lock screen and into elevated windows, where
    the hook cannot see keys either; a refused probe proves nothing."""
    return Probing(probe.since, now) if sent else ANSWERED
