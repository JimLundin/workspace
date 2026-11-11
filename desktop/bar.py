"""The island bar: what it shows, its controls menu, how it moves and its sizes.
Only declarations; `desktop.__main__` builds the bar's spec from them.
"""

from typing import Final

from contracts.members import every_literal, every_member
from contracts.recording_state import Phase
from contracts.status import TRANSCRIBING, TYPING
from desktop import look, placement
from desktop_ui import ambient
from desktop_ui.desktop_pager import PagerSpec
from desktop_ui.island_layout import Bar, BarType, Capsule, Cells, Gauge, Markers, MenuGrid, Sizes
from desktop_ui.island_menu import ActivitiesRow, CellSpec, CellsRow, ControlsSpec, EntryId, Face, MenuWords, Panel, TrayRow
from desktop_ui.island_model import ELAPSED, ActivitiesSpec, Activity, IslandSpec, Phased, Reading, StatusSpec, Symbols, Words
from desktop_ui.island_motion import Springs, Timing
from desktop_ui.motion import Spring
from winapi.machine_status import Speakers, Wifi

SPEAKERS: Final = every_member(
    Speakers,
    {
        Speakers.AUDIBLE: ambient.Reading("speaker-on", "Speakers unmuted"),
        Speakers.MUTED: ambient.Reading("speaker-muted", "Speakers muted"),
        Speakers.UNKNOWN: ambient.Reading("speaker-unknown", "Speaker status unavailable"),
    },
)


WIFI: Final = every_member(
    Wifi,
    {
        Wifi.CONNECTED: ambient.Reading("wifi", "Wi-Fi connected"),
        Wifi.DISCONNECTED: ambient.Reading("wifi-off", "Wi-Fi disconnected"),
        Wifi.NO_ADAPTER: ambient.Reading("wifi-absent", "No Wi-Fi adapter"),
        Wifi.UNKNOWN: ambient.Reading("wifi-unknown", "Wi-Fi status unavailable"),
    },
)


SIZES: Final = Sizes(
    bar=Bar(top=8, edge=12, gap=6, radius=17, shadow=40, pager_gap=12),
    capsule=Capsule(
        height=34,
        control=28,
        icon=16,
        dot=8,
        dots=18,
        wave_bars=18,
        wave_bar=2,
        wave_gap=2,
        part_gap=6,
        slot_gap=12,
        text_pad=12,
        icon_pad=10,
        ring_inset=1.5,
        app_icon=18,
        app_gap=6,
        current_dot=1.5,
    ),
    menu=MenuGrid(width=320, radius=21, pad=6, head=34, track=10, gutter=8),
    markers=Markers(wave_floor=3, wave_reach=13, wave_corner=1, halo=7, dot_count=3, dots_radius=2.2, dots_lift=1.5),
    gauge=Gauge(width=24, height=12, corner=3.5, stroke=1, inset=1.5, nub=1.5, nub_height=4.5, bolt=10, knockout=1),
    cells=Cells(
        corner=12,
        lead=12,
        trail=12,
        symbol_x=4,
        text_x=38,
        text_right=4,
        label_x=36,
        label_right=10,
        tool_top=12,
        caption_side=2,
        caption_bottom=9,
        slider_label_top=8,
        slider_label=16,
        track_bottom=20,
        track_right=14,
        track=6,
        track_corner=3,
        knob=7,
        live_dot_x=20,
        live_dot=5,
        live_text_x=40,
        live_text_right=40,
        live_elide=84,
        stop_right=6,
        tray_image=22,
    ),
    type=BarType(reading=look.TYPE.reading, strong=look.TYPE.strong, detail=look.TYPE.detail),
)


CONTROLS: Final = ControlsSpec(
    every_member(
        Panel,
        {
            Panel.WORKSPACE: (
                ActivitiesRow(5),
                CellsRow(
                    4,
                    (
                        CellSpec(EntryId.OVERLAY, Face.TOGGLE, 4, "Keyboard overlay", "layers"),
                        CellSpec(EntryId.PLACEMENT, Face.TOGGLE, 4, "Placement", "grid"),
                    ),
                ),
                CellsRow(4, (CellSpec(EntryId.DARK_WHEN_AWAY, Face.TOGGLE, 8, "Dark when away", "lock"),)),
                CellsRow(5, (CellSpec(EntryId.RECORD, Face.WIDE, 8, "Record a meeting", "mic"),)),
                CellsRow(6, (CellSpec(EntryId.SOUND, Face.SLIDER, 8),)),
                CellsRow(
                    7,
                    (
                        CellSpec(EntryId.SWITCH_WINDOWS, Face.TOOL, 2, "Switch windows", "search", "Switch"),
                        CellSpec(EntryId.COPY_TRANSCRIPT, Face.TOOL, 2, "Copy latest transcript", "doc", "Transcript"),
                        CellSpec(EntryId.KEYMAP, Face.TOOL, 2, "Keyboard map", "keyboard", "Key map"),
                    ),
                ),
                TrayRow(4),
                CellsRow(3, (CellSpec(EntryId.NOTIFICATIONS, Face.LINK, 8, "Windows notification settings", "bell"),)),
                CellsRow(3, (CellSpec(EntryId.ALL_CONTROLS, Face.LINK, 8, "All Workspace controls…", "more"),)),
            ),
            Panel.SOUND: (
                CellsRow(6, (CellSpec(EntryId.SOUND, Face.SLIDER, 8),)),
                CellsRow(4, (CellSpec(EntryId.MUTE, Face.TOGGLE, 8, "Mute", "speaker-muted"),)),
            ),
        },
    ),
    MenuWords(
        on="On",
        off="Off",
        paused="Paused",
        recording="Recording",
        sound="Sound",
        unread="unavailable",
        muted="muted",
    ),
)
"""The status capsule's panels, each top to bottom: Workspace's own controls
(press its glyph, or an activity) and each reading's own (press the reading).

A panel is a grid of 8 columns. Each row is a band `tracks` tall (a track is
`menu.track` in `SIZES`, gutter included):

- `CellsRow`: entries placed left to right; `span` is their width in columns. An
  entry that doesn't apply now (Record a meeting while one records) gives its
  place to the next; an empty row takes no space.
- `ActivitiesRow`: a full-width card with its Stop for each running activity.
- `TrayRow`: the system tray's icons, a column each, wrapping onto new lines.

Each entry is placed once in a panel; the sound slider takes Windows' own name.
"""


ISLAND: Final = IslandSpec(
    # The fixed capsule at the screen's right edge: its readings left to right,
    # evenly spaced, each opening its panel. Leave a reading out to hide it.
    # The keyboard shows only while it types plainly.
    status=StatusSpec(
        (Reading.WORKSPACE, Reading.KEYBOARD, Reading.SPEAKER, Reading.WIFI, Reading.CPU, Reading.MEMORY, Reading.BATTERY, Reading.CLOCK),
        SPEAKERS,
        WIFI,
        Symbols(workspace="menu", keyboard="keyboard", charger="charger", cpu="cpu", memory="memory"),
        every_member(
            Reading,
            {
                Reading.WORKSPACE: Panel.WORKSPACE,
                Reading.KEYBOARD: Panel.WORKSPACE,
                Reading.SPEAKER: Panel.SOUND,
                Reading.WIFI: Panel.WORKSPACE,
                Reading.CPU: Panel.WORKSPACE,
                Reading.MEMORY: Panel.WORKSPACE,
                Reading.BATTERY: Panel.WORKSPACE,
                Reading.CLOCK: Panel.WORKSPACE,
            },
        ),
        low_battery=20,
        unread="—",
        mains="AC",
        gigabytes="GB",
        widest_percent="100%",
        widest_memory="00.0 GB",
        widest_clock="Wed 00 May 00:00",
        clock="%a %#d %b %H:%M",
    ),
    # Where activities sit beside the island, left to right. A transcription
    # and a recording step out of the island while you dictate. Each activity is
    # placed exactly once.
    activities=ActivitiesSpec(lead=(Activity.JOB,), trail=(Activity.RECORDING,)),
    words=Words(
        jobs=frozendict({TRANSCRIBING: "Transcribing", TYPING: "Typing"}),
        phases=every_literal(
            Phase,
            {
                "idle": None,
                "starting": Phased("Starting…", can_stop=True, attention=False),
                "recording": Phased(ELAPSED, can_stop=True, attention=False),
                "stopping": Phased("Stopping…", can_stop=False, attention=False),
                "finishing": Phased("Saving…", can_stop=False, attention=False),
                "paused": Phased("Check recording", can_stop=False, attention=True),
                "interrupted": Phased("Check recording", can_stop=False, attention=True),
                "saved": None,
            },
        ),
        stop="stop",
        microphone="mic.fill",
        stop_recording="Stop recording",
        stop_dictation="Stop dictation",
        listening="Listening · press to stop",
        open_controls="Open Workspace controls",
        close_controls="Workspace controls · Escape closes",
        charger="Charger connected",
        cpu="CPU",
        memory="memory",
        of="of",
        unavailable="unavailable",
    ),
)
"""The island bar's composition."""


SPRINGS: Final = Springs(
    morph=Spring(0.86, 0.42),
    appear=Spring(0.78, 0.42),  # A little overshoot.
    leave=Spring(1.0, 0.3),
    fade=Spring(1.0, 0.2),
)
"""The bar's own springs; its owner passes them in, tests pass their own."""


TIMING: Final = Timing(pulse=1.2, lag=1 / 6, opaque_at=0.625, wave_sample=0.05)


PAGER: Final = PagerSpec(placement.WEB_APPS, desktop="Desktop", current="current", empty="No placed apps")
"""The pager's web apps and wording."""
