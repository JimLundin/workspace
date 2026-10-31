"""The island bar's view: what each Workspace state puts on screen, and what a press does."""

from dataclasses import replace

from assistant.ambient import Ambient, SystemStatus
from assistant.icons import State
from assistant.island_model import (
    Action,
    Badge,
    CapsuleView,
    Capture,
    Control,
    Glyph,
    Key,
    Marker,
    Observed,
    Spinner,
    Text,
    Tint,
    Tone,
    Zone,
    capture,
    island,
    keyboard,
)
from assistant.recording_state import RecordingState
from winapi.machine_status import Battery, Speakers, Wifi

RESTING = Observed(State.READY, RecordingState(), Ambient("10:22", Battery(73, powered=False, charging=False)), SystemStatus(), 0, None)


def observed(state: State = State.READY, **changes: object) -> Observed:
    return replace(RESTING, state=state, **changes)


def test_rest_shows_only_the_island_with_time_and_battery() -> None:
    # Defect: persistent controls or ambient extras come back beside the island.
    assert island(observed()) == (
        CapsuleView(Key.ISLAND, Zone.ISLAND, ((Text("10:22"), Text("73%")),), "10:22  ·  73% · Open Workspace controls", Action.OPEN_MENU),
    )


def test_alerts_charger_and_low_battery_read_in_the_resting_facts() -> None:
    # Defect: system alerts disappear, the charger is lost, or a low battery looks like any other.
    alert = observed(system=SystemStatus(Speakers.AUDIBLE, Wifi.DISCONNECTED), ambient=Ambient("09:41", Battery(15, powered=False, charging=False)))
    assert island(alert)[0].slots == ((Glyph("speaker-on"), Glyph("wifi-off"), Text("09:41"), Text("15%", Tone.LOW)),)
    full = observed(ambient=Ambient("09:41", Battery(99, powered=True, charging=False)))
    assert island(full)[0].slots == ((Text("09:41"), Glyph("charger")),)


def test_processing_takes_the_leading_slot_and_only_agent_work_offers_stop() -> None:
    # Defect: processing replaces the clock, or hovering offers Stop for transcription, which can't stop.
    assert island(observed(State.WORKING), hovered=Key.ISLAND)[0].slots == ((Spinner("Transcribing"),), (Text("10:22"), Text("73%")))
    assert island(observed(State.AGENT))[0].slots[0] == (Spinner("Agent working"),)
    assert island(observed(State.AGENT), hovered=Key.ISLAND)[0].slots[0] == (
        Spinner("Agent working"),
        Control("stop", "Stop agent work", Action.STOP_AGENT),
    )


def test_a_recording_joins_the_island_at_rest_and_detaches_during_a_moment() -> None:
    # Defect: the recording sits apart from the island at rest, or stays inside it while dictation takes over.
    recording = RecordingState(phase="recording", seconds=125)
    resting = island(observed(recording=recording), hovered=Key.ISLAND)
    assert [view.key for view in resting] == [Key.ISLAND]
    assert resting[0].slots[-1] == (Marker.DOT, Text("02:05"), Control("stop", "Stop recording", Action.STOP_RECORDING))
    dictating = island(observed(State.LISTENING, recording=recording, inbox=2))
    assert [(view.key, view.zone) for view in dictating] == [(Key.ISLAND, Zone.ISLAND), (Key.RECORDING, Zone.TRAIL), (Key.INBOX, Zone.TRAIL)]
    assert dictating[1].slots == ((Marker.DOT, Text("02:05")),) and dictating[1].action is Action.OPEN_CANVAS


def test_dictation_shows_the_live_microphone_and_a_press_stops_it() -> None:
    # Defect: a press during dictation opens the menu instead of stopping.
    view = island(observed(State.LISTENING))[0]
    assert view.slots == ((Glyph("mic.fill", Tone.MICROPHONE), Marker.WAVE),) and view.action is Action.STOP_DICTATION
    hovered = island(observed(State.LISTENING), hovered=Key.ISLAND)[0]
    assert hovered.slots[0][-1] == Control("stop", "Stop dictation", Action.STOP_DICTATION)


def test_a_waiting_question_tints_the_island_and_a_press_opens_it() -> None:
    # Defect: the question looks like the resting island, or pressing it opens the menu.
    view = island(observed(State.NEEDS_INPUT))[0]
    assert view.tint is Tint.ATTENTION and view.action is Action.OPEN_QUESTION
    assert view.slots == ((Text("Needs you", strong=True), Glyph("down")),)


def test_the_inbox_appears_only_while_items_wait_and_caps_its_badge() -> None:
    # Defect: an empty inbox keeps its capsule, or a large count overflows while the exact count is lost.
    assert all(view.key is not Key.INBOX for view in island(observed(inbox=0)))
    many = island(observed(inbox=120))[-1]
    assert many.key is Key.INBOX and many.slots == ((Glyph("bell"), Badge("99+")),)
    assert many.label.startswith("120 clarifications need your input")
    assert island(observed(inbox=1))[-1].label.startswith("1 clarification needs your input")


def test_only_a_temporary_layer_or_the_layout_switched_off_earns_a_lead_capsule() -> None:
    # Defect: the default layout occupies space, or Colemak isn't announced when the layout is off.
    assert keyboard(enabled=True, layer=None) is None
    assert keyboard(enabled=False, layer=None) == "Colemak"
    assert keyboard(enabled=True, layer="NAV · locked") == "NAV · locked"
    view = island(observed(keyboard="NAV"))[0]
    assert (view.key, view.zone, view.action) == (Key.LAYER, Zone.LEAD, Action.OPEN_KEYMAP)


def test_recording_phases_read_and_stop_as_the_capture_allows() -> None:
    # Defect: a finishing capture offers Stop again, an interrupted one doesn't ask for attention, or hours overflow.
    assert capture(RecordingState(phase="recording", seconds=3725)) == Capture("1:02:05", can_stop=True, attention=False)
    assert capture(RecordingState(phase="stopping")) == Capture("Stopping…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="finishing")) == Capture("Saving…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="paused")) == Capture("Check recording", can_stop=False, attention=True)
    assert capture(RecordingState(phase="saved", seconds=900)) is None
