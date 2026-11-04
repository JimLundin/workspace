"""Activity owns the centre; fixed navigation and truthful readings own the right."""

from dataclasses import replace

from assistant.recording_state import RecordingState
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.components.meaning import Tint, Tone
from desktop_ui.island_model import (
    Action,
    Agent,
    Badge,
    CapsuleView,
    Capture,
    Control,
    Expansion,
    Glyph,
    Job,
    Key,
    Marker,
    Observed,
    Spinner,
    Text,
    Zone,
    capture,
    island,
    keyboard,
)
from winapi.machine_status import Battery, Speakers, Wifi

RESTING = Observed(
    None, None, RecordingState(), Ambient("10:22", Battery(73, powered=False, charging=False)), SystemStatus(), 0, None, dictating=False
)
WORKING = Agent("Comparing both sheets", waiting=False)
ASKING = Agent("Which sheet should the reply cover?", waiting=True)
RECORDING = RecordingState(phase="recording", seconds=125)


def view(observed: Observed, key: Key, *, expanded: Expansion | None = None, hovered: Key | None = None) -> CapsuleView:
    """Read one identity without depending on other capsules' inventory positions."""
    return next(each for each in island(observed, expanded=expanded, hovered=hovered) if each.key is key)


def test_idle_has_only_icon_navigation_device_status_and_clock_power_on_right() -> None:
    # Defect: idle readings reappear in the centre or navigation acquires text.
    views = island(RESTING)
    assert tuple(each.key for each in views) == (Key.CANVAS, Key.STATUS)
    assert tuple(each.zone for each in views) == (Zone.LEFT, Zone.RIGHT)
    assert views[0] == CapsuleView(Key.CANVAS, Zone.LEFT, ((Glyph("canvas"),),), "Canvas · Open your work canvas", Action.OPEN_CANVAS)
    assert views[-1].slots == (
        (
            Control("speaker-unknown", "Speaker status unavailable · Open sound settings", Action.OPEN_SOUND_SETTINGS),
            Control("wifi-unknown", "Wi-Fi status unavailable · Open Wi-Fi settings", Action.OPEN_WIFI_SETTINGS),
        ),
        (Text("10:22", reserve="00:00"), Glyph("battery"), Text("73%", reserve="100%")),
    )


def test_fixed_controls_survive_all_activity_menu_and_device_states() -> None:
    # Defect: moments hide status, or status becomes a central activity.
    for speakers in Speakers:
        for wifi in Wifi:
            baseline = replace(RESTING, system=SystemStatus(speakers, wifi), keyboard="NAV")
            for observed in (
                baseline,
                replace(baseline, dictating=True),
                replace(baseline, agent=ASKING),
                replace(baseline, agent=WORKING, job=Job.TRANSCRIBING, recording=RECORDING),
            ):
                for expanded in (None, Expansion.MENU, Expansion.REQUEST):
                    # The open menu is the status capsule itself; the other fixed controls stay.
                    for key in (Key.CANVAS, Key.LAYER) if expanded is Expansion.MENU else (Key.CANVAS, Key.LAYER, Key.STATUS):
                        assert view(observed, key, expanded=expanded) == view(baseline, key)
                    activity = (each for each in island(observed, expanded=expanded) if each.zone not in (Zone.LEFT, Zone.RIGHT))
                    assert all(Text("10:22") not in slot for each in activity for slot in each.slots)
            status = view(baseline, Key.STATUS)
            assert status.slots[0] == (
                Control(baseline.system.speaker_icon, baseline.system.speaker_description + " · Open sound settings", Action.OPEN_SOUND_SETTINGS),
                Control(baseline.system.wifi_icon, baseline.system.wifi_description + " · Open Wi-Fi settings", Action.OPEN_WIFI_SETTINGS),
            )
            assert status.action is Action.OPEN_MENU
            assert baseline.system.speaker_description in status.label
            assert baseline.system.wifi_description in status.label


def test_charger_and_low_battery_stay_in_far_right_readings() -> None:
    low = replace(RESTING, ambient=Ambient("09:41", Battery(15, powered=False, charging=False)))
    assert view(low, Key.STATUS).slots[-1] == (Text("09:41", reserve="00:00"), Glyph("battery"), Text("15%", Tone.LOW, reserve="100%"))
    full = replace(RESTING, ambient=Ambient("09:41", Battery(99, powered=True, charging=False)))
    assert view(full, Key.STATUS).slots[-1] == (Text("09:41", reserve="00:00"), Glyph("charger"), Text("99%", reserve="100%"))


def test_concurrent_activity_has_distinct_indicators_and_stable_agent_stop() -> None:
    # Defect: hover shifts Stop, or transcription borrows the agent's ring.
    busy = replace(RESTING, agent=WORKING, job=Job.TRANSCRIBING, recording=RECORDING)
    active = view(busy, Key.ISLAND, hovered=Key.ISLAND)
    agent, job, recording = active.slots
    assert agent == (Spinner("Agent: Comparing both sheets"), Text("Comparing both sheets"), Control("stop", "Stop agent work", Action.STOP_AGENT))
    assert job == (Marker.DOTS,) and recording[:2] == (Marker.DOT, Text("02:05"))
    assert "Transcribing" in active.label
    assert view(replace(RESTING, agent=WORKING), Key.ISLAND) == view(replace(RESTING, agent=WORKING), Key.ISLAND, hovered=Key.ISLAND)
    long = view(replace(RESTING, agent=Agent("Reading every attachment in the budget thread", waiting=False)), Key.ISLAND)
    assert long.slots[0][1] == Text("Reading every attachment in…")


def test_dictation_detaches_every_other_activity_without_persistent_facts() -> None:
    observed = replace(RESTING, dictating=True, agent=WORKING, job=Job.ANSWERING, recording=RECORDING, inbox=2)
    dynamic = tuple(each for each in island(observed) if each.zone not in (Zone.LEFT, Zone.RIGHT))
    assert tuple(each.key for each in dynamic) == (Key.AGENT, Key.JOB, Key.ISLAND, Key.RECORDING, Key.INBOX)
    assert dynamic[0].slots == ((Spinner("Agent: Comparing both sheets"), Control("stop", "Stop agent work", Action.STOP_AGENT)),)
    assert dynamic[1].slots == ((Marker.DOTS,),)
    assert dynamic[2].slots == ((Glyph("mic.fill", Tone.MICROPHONE), Marker.WAVE),)
    assert dynamic[2].action is Action.STOP_DICTATION


def test_waiting_question_wins_except_during_dictation() -> None:
    question = view(replace(RESTING, agent=ASKING), Key.ISLAND)
    assert (question.tint, question.action) == (Tint.ATTENTION, Action.OPEN_QUESTION)
    assert question.slots == ((Text("Needs you", strong=True), Glyph("down")),)
    beside = view(replace(RESTING, agent=ASKING, dictating=True), Key.AGENT)
    assert (beside.tint, beside.action) == (Tint.ATTENTION, Action.OPEN_QUESTION)


def test_the_status_capsule_expands_into_the_menu_and_a_question_into_the_island() -> None:
    # Defects: the menu opens as the centre island instead of the capsule that
    # opened it, that capsule loses its readings while open, a question expands
    # the status capsule, or activity stays in the centre while the menu lists it.
    busy = replace(RESTING, agent=WORKING, job=Job.ANSWERING, recording=RECORDING, inbox=2)
    opened = island(busy, expanded=Expansion.MENU)
    assert tuple(each.key for each in opened) == (Key.INBOX, Key.CANVAS, Key.STATUS)
    readings = view(busy, Key.STATUS).slots
    assert opened[-1] == CapsuleView(Key.STATUS, Zone.RIGHT, readings, "Workspace controls · Escape closes", Action.CLOSE_MENU)
    asking = replace(busy, agent=ASKING)
    assert tuple(each.key for each in island(asking, expanded=Expansion.REQUEST)) == (Key.ISLAND, Key.INBOX, Key.CANVAS, Key.STATUS)
    assert view(asking, Key.STATUS, expanded=Expansion.REQUEST) == view(asking, Key.STATUS)


def test_inbox_only_exists_while_pending_and_keeps_exact_count_in_label() -> None:
    assert Key.INBOX not in tuple(each.key for each in island(RESTING))
    many = view(replace(RESTING, inbox=120), Key.INBOX)
    assert many.slots == ((Glyph("bell"), Badge("99+")),)
    assert many.label.startswith("120 clarifications need your input")
    assert view(replace(RESTING, inbox=1), Key.INBOX).label.startswith("1 clarification needs your input")


def test_keyboard_is_temporary_icon_only_with_state_in_accessible_label() -> None:
    assert keyboard(enabled=True, layer=None) is None
    assert keyboard(enabled=False, layer=None) == "Colemak"
    assert keyboard(enabled=True, layer="NAV · locked") == "NAV · locked"
    layer = view(replace(RESTING, keyboard="NAV"), Key.LAYER)
    assert (layer.zone, layer.action, layer.slots) == (Zone.RIGHT, Action.OPEN_KEYMAP, ((Glyph("keyboard"),),))
    assert "NAV" in layer.label


def test_recording_phases_read_and_stop_as_capture_allows() -> None:
    assert capture(RecordingState(phase="recording", seconds=3725)) == Capture("1:02:05", can_stop=True, attention=False)
    assert capture(RecordingState(phase="stopping")) == Capture("Stopping…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="finishing")) == Capture("Saving…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="paused")) == Capture("Check recording", can_stop=False, attention=True)
    assert capture(RecordingState(phase="saved", seconds=900)) is None
