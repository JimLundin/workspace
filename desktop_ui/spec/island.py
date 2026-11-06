"""The island bar's composition."""

from typing import Final

from desktop_ui.island_model import ActivitiesSpec, Activity, IslandSpec, Reading, StatusSpec, TextSpec

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
    # Where activities sit beside the centre island, left to right. The agent and a
    # transcription step out of the island while you dictate, a question waits or a
    # notice shows; a recording does too; the inbox's bell shows while anything
    # waits. Each activity is placed exactly once.
    activities=ActivitiesSpec(lead=(Activity.AGENT, Activity.JOB), trail=(Activity.RECORDING, Activity.INBOX)),
    # The agent's phase and a notice's title, in characters, before they elide;
    # a notice's width in pixels.
    text=TextSpec(phase=28, title=44, notice_width=340),
)
