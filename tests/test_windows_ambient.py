"""Windows power, Wi-Fi, speaker, processor and memory observations, including unknown readings."""

import sys
import time
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows power status")

from winapi import resources, system_status
from winapi.machine_status import cpu_load


def test_speaker_level_round_trips_through_the_default_endpoint_without_changing_it() -> None:
    # Defects: the level binding reads or writes the wrong native value, or the
    # write accepts a level outside 0 to 1. Writing back the current level leaves
    # the user's volume as it was.
    before = system_status.audio()
    if before.volume is None:
        raise unittest.SkipTest("No default playback endpoint reports a level.")
    assert system_status.set_volume(before.volume)
    after = system_status.audio()
    assert after.volume is not None and abs(after.volume - before.volume) < 0.01 and after.speakers is before.speakers
    for invalid in (-0.1, 1.1, float("nan")):
        try:
            system_status.set_volume(invalid)
        except ValueError:
            continue
        raise AssertionError(f"An out-of-range speaker level was written: {invalid}")


def test_processor_and_memory_bindings_read_real_values() -> None:
    # Defects: a wrong MEMORYSTATUSEX size makes Windows reject every memory read,
    # or the FILETIME halves are combined so later samples run backwards.
    memory = resources.memory_load()
    assert memory is not None and 0 < memory <= 100
    first = resources.cpu_times()
    assert first is not None and first.kernel >= first.idle > 0
    later = first
    for _ in range(50):  # Windows advances these counters at its clock tick, about 16 ms.
        time.sleep(0.02)
        if (sample := resources.cpu_times()) is not None:
            later = sample
        if later.kernel + later.user > first.kernel + first.user:
            break
    load = cpu_load(first, later)
    assert load is not None and 0 <= load <= 100
