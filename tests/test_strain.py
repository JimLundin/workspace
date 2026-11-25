from dataclasses import replace

from desktop_ui.ambient import SystemStatus
from desktop_ui.strain import Notice, StrainSpec, Watch, watched
from tests import test_bar_specs
from winapi.machine_status import AppUse, Memory

SPEC = StrainSpec(low_memory=100, recovered=200, busy_cores=0.5, busy_for=600)
STATUS = test_bar_specs.SPEC.island.status


def available(free: int) -> SystemStatus:
    return SystemStatus(memory=Memory(1_000 - free, 1_000))


def notices_over(
    readings: tuple[SystemStatus, ...],
) -> list[tuple[Notice, ...]]:
    watch = Watch()
    seen = []
    for system in readings:
        watch, notices = watched(watch, system, SPEC, STATUS)
        seen.append(notices)
    return seen


def test_low_memory_warns_once_until_memory_recovers_past_the_higher_line() -> (
    None
):
    counts = [
        len(notices)
        for notices in notices_over(
            tuple(available(free) for free in (500, 90, 80, 150, 95, 250, 90))
        )
    ]
    assert counts == [0, 1, 0, 0, 0, 0, 1]


def test_an_app_warns_once_after_holding_the_processor_for_the_whole_stretch() -> (
    None
):
    def busy(at: float, cores: float) -> SystemStatus:
        return SystemStatus(apps=(AppUse("Code", 1, cores),), ranked_at=at)

    repeated = (busy(0, 1.0),) * 700
    over_time = (
        *repeated,
        busy(300, 1.0),
        busy(599, 1.0),
        busy(600, 1.0),
        busy(630, 1.0),
        busy(660, 0.1),
        busy(690, 1.0),
        busy(1290, 1.0),
    )
    counts = [len(notices) for notices in notices_over(over_time)]
    assert counts[: len(repeated)] == [0] * len(repeated)
    assert counts[len(repeated) :] == [0, 0, 1, 0, 0, 0, 1]


def test_the_warnings_name_the_largest_apps_and_the_busy_one() -> None:
    low = replace(
        available(50),
        apps=(AppUse("small", 1, None), AppUse("msedge", 900, None)),
    )
    _, (memory,) = watched(Watch(), low, SPEC, STATUS)
    assert memory.text.index("msedge") < memory.text.index("small")
    held = SystemStatus(apps=(AppUse("Code", 1, 1.0),), ranked_at=600.0)
    _, (app,) = watched(
        Watch(ranked_at=0.0, busy_since=frozendict(Code=0.0)),
        held,
        SPEC,
        STATUS,
    )
    assert "Code" in app.title
