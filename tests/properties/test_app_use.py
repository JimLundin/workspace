"""However processes come and go between two samples, the apps' processor use adds up to the time spent since."""

from dataclasses import dataclass

from hypothesis import strategies

from tests.properties.generation import cases, property_test
from winapi.machine_status import ProcessSample, ProcessUse, apps

SECOND = 10_000_000


@dataclass(frozen=True, slots=True)
class Samples:
    before: ProcessSample
    after: ProcessSample
    spent: int
    """The processor time every process in `after` spent since `before`, or since it started."""


def samples(draw: strategies.DrawFn) -> Samples:
    names = strategies.sampled_from(("a.exe", "b.exe", "c"))
    earlier = draw(
        strategies.dictionaries(
            strategies.integers(1, 40),
            strategies.tuples(names, strategies.integers(0, 1_000 * SECOND)),
            max_size=20,
        )
    )
    later = draw(
        strategies.dictionaries(
            strategies.integers(1, 40),
            strategies.tuples(
                names,
                strategies.integers(0, 10_000),
                strategies.integers(0, 4 * SECOND),
            ),
            max_size=20,
        )
    )
    before = ProcessSample(
        0.0,
        tuple(
            ProcessUse(pid, name, 0, cpu)
            for pid, (name, cpu) in earlier.items()
        ),
    )
    after = ProcessSample(
        2.0,
        tuple(
            ProcessUse(
                pid,
                name,
                memory,
                (
                    earlier[pid][1]
                    if pid in earlier and earlier[pid][0] == name
                    else 0
                )
                + spent,
            )
            for pid, (name, memory, spent) in later.items()
        ),
    )
    return Samples(before, after, sum(spent for _, _, spent in later.values()))


@property_test(cases(samples))
def test_apps_account_for_every_process_once(case: Samples) -> None:
    # Defects: a process is counted under two apps or dropped from its own, a reused
    # id goes negative, or the memory of the apps differs from the processes'.
    used = tuple(apps(case.before, case.after))
    cores = [app.cores for app in used]
    assert all(core is not None and core >= 0 for core in cores)
    assert abs(sum(core or 0 for core in cores) * 2.0 * SECOND - case.spent) < 1
    assert sum(app.memory for app in used) == sum(
        process.memory for process in case.after.processes
    )
    assert len({app.name for app in used}) == len(used)
