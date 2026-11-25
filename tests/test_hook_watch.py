from collections.abc import Iterable
from dataclasses import dataclass

from keyboard.hook_watch import (
    ANSWERED,
    Probe,
    Reinstall,
    Watch,
    assess,
    keyboard_input,
    probed,
)


@dataclass(frozen=True, slots=True)
class Raw:
    tick: int


@dataclass(frozen=True, slots=True)
class HookEvent:
    tick: int


@dataclass(frozen=True, slots=True)
class Timer:
    tick: int
    probe_sent: bool = True


type Observation = Raw | HookEvent | Timer


def actions(observations: Iterable[Observation]) -> list[tuple[str, int]]:
    watch: Watch = ANSWERED
    hook: int | None = None
    taken: list[tuple[str, int]] = []
    for observation in observations:
        match observation:
            case Raw(tick):
                watch = keyboard_input(watch, tick)
            case HookEvent(tick):
                hook = tick
            case Timer(tick, probe_sent=sent):
                match assess(watch, hook, tick):
                    case Probe() as probe:
                        taken.append(("probe", tick))
                        watch = probed(probe, tick, sent=sent)
                    case Reinstall(since=since):
                        taken.append(("reinstall", since))
                        watch = ANSWERED
                    case state:
                        watch = state
    return taken


def timers(start: int, stop: int) -> list[Timer]:
    return [Timer(tick) for tick in range(start, stop, 200)]


def played(*groups: Iterable[Observation]) -> list[Observation]:
    return sorted(
        (observation for group in groups for observation in group),
        key=observed_at,
    )


def observed_at(observation: Observation) -> int:
    return observation.tick


def test_mouse_use_and_idle_time_never_probe() -> None:
    assert actions([HookEvent(100), Raw(100), *timers(200, 600_000)]) == []


def test_keys_answered_by_a_live_hook_never_probe_even_when_raw_input_comes_first() -> (
    None
):
    observations: list[Observation] = [
        HookEvent(1_000),
        Raw(1_950),
        Timer(2_000),
        Raw(5_000),
        HookEvent(5_000),
        Timer(5_100),
    ]
    assert (
        actions(
            [
                *observations,
                Raw(9_000),
                Timer(9_100),
                HookEvent(9_000),
                *timers(9_300, 20_000),
            ]
        )
        == []
    )


def test_keyboard_input_the_hook_never_sees_reinstalls_after_a_failed_probe() -> (
    None
):
    typing = [Raw(tick) for tick in range(30_000, 32_000, 50)]
    assert actions(
        played(
            [HookEvent(1_000), Raw(1_000), Timer(1_100)],
            typing,
            timers(30_100, 31_600),
        )
    ) == [("probe", 30_300), ("reinstall", 30_000)]


def test_a_probe_the_hook_answers_cancels_the_reinstall() -> None:
    observations: list[Observation] = [
        HookEvent(1_000),
        Raw(30_000),
        Timer(30_300),
        HookEvent(30_900),
        *timers(31_100, 40_000),
    ]
    assert actions(observations) == [("probe", 30_300)]


def test_refused_probes_on_the_lock_screen_or_in_elevated_windows_never_reinstall() -> (
    None
):
    typing = [Raw(tick) for tick in range(30_000, 60_000, 100)]
    refused = [
        Timer(tick, probe_sent=False) for tick in range(30_100, 60_000, 200)
    ]
    taken = actions(played([HookEvent(1_000)], typing, refused))
    assert taken[:2] == [("probe", 30_300), ("probe", 30_700)]
    assert {name for name, _ in taken} == {"probe"}


def test_one_outage_reinstalls_once_and_the_new_hook_settles_the_watch() -> (
    None
):
    outage: list[Observation] = [
        HookEvent(1_000),
        Raw(30_000),
        *timers(30_100, 31_400),
    ]
    late_probe_input: list[Observation] = [
        Raw(30_300),
        *timers(31_500, 31_600),
        HookEvent(31_510),
    ]
    typing: list[Observation] = [
        event
        for at in range(32_000, 60_000, 100)
        for event in (Raw(at), HookEvent(at))
    ]
    taken = actions(
        [*outage, *late_probe_input, *played(typing, timers(31_700, 60_000))]
    )
    assert taken == [
        ("probe", 30_300),
        ("reinstall", 30_000),
        ("probe", 31_500),
    ]


def test_tick_wraparound_keeps_answered_input_answered() -> None:
    top = 0xFFFF_FFFF
    assert (
        actions(
            [HookEvent(top - 10), Raw(5), Timer(100), Timer(300), Timer(2_000)]
        )
        == []
    )
    assert actions(
        [HookEvent(top - 5_000), Raw(5), Timer(300), Timer(1_400)]
    ) == [("probe", 300), ("reinstall", 5)]
