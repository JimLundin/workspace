"""Activity owns the centre; fixed navigation and truthful readings own the right."""

from dataclasses import replace

from contracts.recording_state import RecordingState
from desktop_ui.ambient import SPEAKERS, WIFI, Ambient, SystemStatus
from desktop_ui.components.meaning import Tone
from desktop_ui.island_model import (
    Action,
    CapsuleView,
    Capture,
    Control,
    Glyph,
    Job,
    Key,
    Marker,
    Observed,
    Text,
    Zone,
    capture,
    island,
)
from desktop_ui.spec.island import ISLAND
from winapi.machine_status import Battery, Speakers, Wifi

SPEC = ISLAND
RESTING = Observed(None, RecordingState(), Ambient("10:22", Battery(73, powered=False, charging=False)), SystemStatus(), dictating=False)
RECORDING = RecordingState(phase="recording", seconds=125)


def view(observed: Observed, key: Key, *, expanded: bool = False, hovered: Key | None = None) -> CapsuleView:
    """Read one identity without depending on other capsules' inventory positions."""
    return next(each for each in island(observed, SPEC, expanded=expanded, hovered=hovered) if each.key is key)


def test_idle_has_only_device_status_and_clock_power_on_right() -> None:
    # Defect: idle readings reappear in the centre, or the fixed capsule gains a reading.
    views = island(RESTING, SPEC)
    assert tuple(each.key for each in views) == (Key.STATUS,)
    assert tuple(each.zone for each in views) == (Zone.RIGHT,)
    assert views[-1].slots == (
        (
            Glyph("speaker-unknown"),
            Glyph("wifi-unknown"),
        ),
        (
            Text("10:22", reserve="00:00"),
            Glyph("battery"),
            Text("73%", reserve="100%"),
            Glyph("cpu"),
            Text("—", reserve="100%"),
            Glyph("memory"),
            Text("—", reserve="100%"),
        ),
    )


def test_a_plain_keyboard_is_a_reading_beside_the_speaker_and_wifi() -> None:
    # Defects: the keyboard shows while the layout remaps, or it becomes a
    # control in its own slot, spaced apart from the speaker and Wi-Fi.
    plain = view(replace(RESTING, plain_keyboard=True), Key.STATUS)
    assert plain.slots[0] == (Glyph("keyboard"), Glyph("speaker-unknown"), Glyph("wifi-unknown"))
    assert len(plain.slots) == len(view(RESTING, Key.STATUS).slots)
    assert Glyph("keyboard") not in view(RESTING, Key.STATUS).slots[0]


def test_processor_and_memory_are_plain_readings_that_reserve_their_widest_value() -> None:
    # Defects: a reading becomes a control, a value from 9% to 100% resizes the
    # fixed capsule because its reserve follows the value, CPU and memory swap
    # symbols, an unread value shows as 0% (a healthy-looking lie), or the
    # capsule's accessible name omits the readings.
    for cpu, memory, shown in ((23, 61, ("23%", "61%")), (100, 9, ("100%", "9%")), (None, None, ("—", "—"))):
        status = view(replace(RESTING, system=SystemStatus(cpu=cpu, memory=memory)), Key.STATUS)
        assert status.slots[-1][-4:] == (Glyph("cpu"), Text(shown[0], reserve="100%"), Glyph("memory"), Text(shown[1], reserve="100%"))
        assert not any(isinstance(part, Control) for slot in status.slots for part in slot)
    label = view(replace(RESTING, system=SystemStatus(cpu=23, memory=61)), Key.STATUS).label
    assert label.startswith("CPU 23%, memory 61%. ")
    assert view(RESTING, Key.STATUS).label.startswith("CPU unavailable, memory unavailable. ")


def test_fixed_controls_survive_all_activity_menu_and_device_states() -> None:
    # Defect: moments hide status, or status becomes a central activity.
    for speakers in Speakers:
        for wifi in Wifi:
            baseline = replace(RESTING, system=SystemStatus(speakers, wifi))
            for observed in (
                baseline,
                replace(baseline, dictating=True),
                replace(baseline, job=Job.TRANSCRIBING, recording=RECORDING),
            ):
                for expanded in (False, True):
                    # The open menu is the status capsule itself; its row stays.
                    fixed = view(observed, Key.STATUS, expanded=expanded)
                    assert fixed.slots == view(baseline, Key.STATUS).slots
                    assert expanded or fixed == view(baseline, Key.STATUS)
                    activity = (each for each in island(observed, SPEC, expanded=expanded) if each.zone is not Zone.RIGHT)
                    assert all(Text("10:22") not in slot for each in activity for slot in each.slots)
            status = view(baseline, Key.STATUS)
            assert status.slots[-2] == (Glyph(SPEAKERS[baseline.system.speakers].icon), Glyph(WIFI[baseline.system.wifi].icon))
            assert status.action is Action.OPEN_MENU
            assert SPEAKERS[baseline.system.speakers].description in status.label
            assert WIFI[baseline.system.wifi].description in status.label


def test_charger_and_low_battery_lead_the_machine_readings_at_the_right() -> None:
    # Defects: a low battery loses its tone, the charger glyph is wrong, or the
    # processor and memory readings no longer follow the battery's percentage.
    low = replace(RESTING, ambient=Ambient("09:41", Battery(15, powered=False, charging=False)))
    assert view(low, Key.STATUS).slots[-1][:3] == (Text("09:41", reserve="00:00"), Glyph("battery"), Text("15%", Tone.LOW, reserve="100%"))
    full = replace(RESTING, ambient=Ambient("09:41", Battery(99, powered=True, charging=False)))
    assert view(full, Key.STATUS).slots[-1][:3] == (Text("09:41", reserve="00:00"), Glyph("charger"), Text("99%", reserve="100%"))
    assert view(full, Key.STATUS).slots[-1][3] == Glyph("cpu")


def test_concurrent_activity_has_distinct_indicators_and_recording_stop_under_the_pointer() -> None:
    # Defects: transcription and recording share one indicator, or Stop shows at rest.
    busy = replace(RESTING, job=Job.TRANSCRIBING, recording=RECORDING)
    job, recording = view(busy, Key.ISLAND).slots
    assert job == (Marker.DOTS,) and recording == (Marker.DOT, Text("02:05"))
    assert view(busy, Key.ISLAND).label.startswith("Transcribing. 02:05")
    assert view(busy, Key.ISLAND, hovered=Key.ISLAND).slots[-1][-1] == Control("stop", "Stop recording", Action.STOP_RECORDING)


def test_dictation_detaches_every_other_activity_without_persistent_facts() -> None:
    # Defect: dictation shares the centre with other activity, or loses its stop press.
    observed = replace(RESTING, dictating=True, job=Job.TRANSCRIBING, recording=RECORDING)
    dynamic = tuple(each for each in island(observed, SPEC) if each.zone is not Zone.RIGHT)
    assert tuple(each.key for each in dynamic) == (Key.JOB, Key.ISLAND, Key.RECORDING)
    assert dynamic[0].slots == ((Marker.DOTS,),)
    assert dynamic[1].slots == ((Glyph("mic.fill", Tone.MICROPHONE), Marker.WAVE),)
    assert dynamic[1].action is Action.STOP_DICTATION


def test_the_status_capsule_expands_into_the_menu() -> None:
    # Defects: the menu opens as the centre island instead of the capsule that
    # opened it, that capsule loses its readings while open, or activity stays
    # in the centre while the menu lists it.
    busy = replace(RESTING, job=Job.TRANSCRIBING, recording=RECORDING)
    opened = island(busy, SPEC, expanded=True)
    readings = view(busy, Key.STATUS).slots
    assert opened == (CapsuleView(Key.STATUS, Zone.RIGHT, readings, "Workspace controls · Escape closes", Action.CLOSE_MENU),)


def test_recording_phases_read_and_stop_as_capture_allows() -> None:
    assert capture(RecordingState(phase="recording", seconds=3725)) == Capture("1:02:05", can_stop=True, attention=False)
    assert capture(RecordingState(phase="stopping")) == Capture("Stopping…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="finishing")) == Capture("Saving…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="paused")) == Capture("Check recording", can_stop=False, attention=True)
    assert capture(RecordingState(phase="saved", seconds=900)) is None
