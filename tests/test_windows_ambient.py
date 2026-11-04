"""Windows power observations distinguish charging, desktops and unknown readings."""

import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows power status")

from winapi import ambient, system_status
from winapi.machine_status import Battery, PowerUnavailable


def test_native_power_validates_missing_and_unknown_batteries() -> None:
    status = ambient.PowerStatus()
    status.ac, status.flags, status.percent = 1, 8, 73
    assert ambient.power_from_status(status) == Battery(73, powered=True, charging=True)
    status.flags = 128
    assert ambient.power_from_status(status) is PowerUnavailable.NO_BATTERY
    status.flags = 255
    assert ambient.power_from_status(status) is PowerUnavailable.UNKNOWN
    status.flags, status.percent = 0, 255
    assert ambient.power_from_status(status) is PowerUnavailable.UNKNOWN
    assert ambient.power_from_status(None) is PowerUnavailable.UNKNOWN


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
