"""Toolbar policy: activity owns the centre; permanent navigation and facts own the right."""

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
ASKING = Agent("Which sheet?", waiting=True)
RECORDING = RecordingState(phase="recording", seconds=125)


def view(observed: Observed, key: Key, *, expanded: bool = False, hovered: Key | None = None) -> CapsuleView:
    """Select one identity while exercising independent expansion and hover states."""
    return next(each for each in island(observed, expanded=expanded, hovered=hovered) if each.key is key)


def test_idle_centre_is_empty_and_navigation_is_icon_only_on_the_right() -> None:
    # Defect: idle facts occupy the activity centre or Canvas loses its route/name.
    assert island(RESTING) == (
        CapsuleView(Key.STATUS, Zone.RIGHT, ((Text("10:22"), Text("73%")),), "10:22  ·  73% · Open Workspace controls", Action.OPEN_MENU),
        CapsuleView(Key.CANVAS, Zone.RIGHT, ((Glyph("canvas"),),), "Canvas · Open your work canvas", Action.OPEN_CANVAS),
    )


def test_permanent_facts_and_canvas_survive_every_activity_and_menu() -> None:
    # Defect: a moment hides permanent controls or duplicates their facts centrally.
    observations = (
        RESTING,
        replace(RESTING, dictating=True),
        replace(RESTING, agent=ASKING),
        replace(RESTING, agent=WORKING, job=Job.TRANSCRIBING, recording=RECORDING),
    )
    for observed in observations:
        for expanded in (False, True):
            for key in (Key.STATUS, Key.CANVAS):
                assert view(observed, key, expanded=expanded) == view(RESTING, key)
            activity = (each for each in island(observed, expanded=expanded) if each.zone is not Zone.RIGHT)
            assert all(Text("10:22") not in slot for each in activity for slot in each.slots)


def test_alerts_charger_and_low_battery_remain_right_hand_facts() -> None:
    alert = replace(
        RESTING, system=SystemStatus(Speakers.AUDIBLE, Wifi.DISCONNECTED), ambient=Ambient("09:41", Battery(15, powered=False, charging=False))
    )
    assert view(alert, Key.STATUS).slots == ((Glyph("speaker-on"), Glyph("wifi-off"), Text("09:41"), Text("15%", Tone.LOW)),)
    full = replace(RESTING, ambient=Ambient("09:41", Battery(99, powered=True, charging=False)))
    assert view(full, Key.STATUS).slots == ((Text("09:41"), Glyph("charger")),)


def test_agent_stop_is_stable_and_concurrent_activity_keeps_distinct_indicators() -> None:
    busy = replace(RESTING, agent=WORKING, job=Job.TRANSCRIBING, recording=RECORDING)
    active = view(busy, Key.ISLAND, hovered=Key.ISLAND)
    agent, job, recording = active.slots
    assert agent == (
        Spinner("Agent: Comparing both sheets"), Text("Comparing both sheets"), Control("stop", "Stop agent work", Action.STOP_AGENT)
    )
    assert job == (Marker.DOTS,) and recording == (Marker.DOT, Text("02:05"), Control("stop", "Stop recording", Action.STOP_RECORDING))
    assert view(replace(RESTING, agent=WORKING), Key.ISLAND) == view(replace(RESTING, agent=WORKING), Key.ISLAND, hovered=Key.ISLAND)
    long = replace(RESTING, agent=Agent("Reading every attachment in the budget thread", waiting=False))
    assert view(long, Key.ISLAND).slots[0][1] == Text("Reading every attachment in…")


def test_dictation_detaches_concurrent_work_and_questions_retain_attention() -> None:
    observed = replace(RESTING, dictating=True, agent=ASKING, job=Job.ANSWERING, recording=RECORDING)
    assert view(observed, Key.ISLAND).slots == ((Glyph("mic.fill", Tone.MICROPHONE), Marker.WAVE),)
    assert view(observed, Key.ISLAND).action is Action.STOP_DICTATION
    assert view(observed, Key.AGENT).action is Action.OPEN_QUESTION and view(observed, Key.AGENT).tint is Tint.ATTENTION
    assert view(observed, Key.JOB).slots == ((Marker.DOTS,),)
    assert view(observed, Key.RECORDING).action is Action.OPEN_CANVAS
    assert view(replace(RESTING, agent=ASKING), Key.ISLAND).slots == ((Text("Needs you", strong=True), Glyph("down")),)


def test_inbox_is_dynamic_and_keeps_exact_count_in_accessible_label() -> None:
    assert Key.INBOX not in tuple(each.key for each in island(RESTING))
    many = view(replace(RESTING, inbox=120), Key.INBOX)
    assert many.zone is Zone.TRAIL and many.slots == ((Glyph("bell"), Badge("99+")),)
    assert many.label.startswith("120 clarifications need your input")


def test_keyboard_visibility_is_preserved_but_its_reading_is_accessible_not_visual() -> None:
    assert keyboard(enabled=True, layer=None) is None
    assert keyboard(enabled=False, layer=None) == "Colemak"
    assert keyboard(enabled=True, layer="NAV · locked") == "NAV · locked"
    for label in ("Colemak", "NAV · locked"):
        shown = view(replace(RESTING, keyboard=label), Key.LAYER)
        assert shown.slots == ((Glyph("keyboard"),),)
        assert (shown.zone, shown.action, shown.label) == (Zone.RIGHT, Action.OPEN_KEYMAP, label + " · Open key map")


def test_recording_phases_keep_their_stop_and_attention_policy() -> None:
    assert capture(RecordingState(phase="recording", seconds=3725)) == Capture("1:02:05", can_stop=True, attention=False)
    assert capture(RecordingState(phase="stopping")) == Capture("Stopping…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="finishing")) == Capture("Saving…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="paused")) == Capture("Check recording", can_stop=False, attention=True)
    assert capture(RecordingState(phase="saved", seconds=900)) is None
