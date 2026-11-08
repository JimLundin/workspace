"""The island bar's composition."""

from typing import Final

from desktop_ui.island_model import ActivitiesSpec, Activity, IslandSpec, Reading, StatusSpec

ISLAND: Final = IslandSpec(
    # The fixed capsule at the screen's right edge, which opens the controls menu:
    # its readings left to right, in groups. Readings in a group sit close together;
    # groups sit further apart. Leave a reading out to hide it. The keyboard shows
    # only while it types plainly.
    status=StatusSpec(
        (
            (Reading.KEYBOARD, Reading.SPEAKER, Reading.WIFI),
            (Reading.CLOCK, Reading.POWER, Reading.BATTERY, Reading.CPU, Reading.MEMORY),
        )
    ),
    # Where activities sit beside the centre island, left to right. A transcription
    # and a recording step out of the island while you dictate. Each activity is
    # placed exactly once.
    activities=ActivitiesSpec(lead=(Activity.JOB,), trail=(Activity.RECORDING,)),
)
