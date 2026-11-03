"""The island bar's view: what each combination of activities puts on screen, and what a press does."""

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
ASKING = Agent("Which sheet should the reply cover?", waiting=True)
RECORDING = RecordingState(phase="recording", seconds=125)


def keys(views: tuple[CapsuleView, ...]) -> list[Key]:
    return [view.key for view in views]


def test_rest_shows_time_and_battery_with_labelled_canvas_navigation() -> None:
    # Defect: Canvas is missing, loses its visible label, or opens the controls instead of the canvas.
    assert island(RESTING) == (
        CapsuleView(Key.ISLAND, Zone.ISLAND, ((Text("10:22"), Text("73%")),), "10:22  ·  73% · Open Workspace controls", Action.OPEN_MENU),
        CapsuleView(Key.CANVAS, Zone.TRAIL, ((Glyph("canvas"), Text("Canvas")),), "Canvas · Open your work canvas", Action.OPEN_CANVAS),
    )


def test_canvas_stays_beside_dictation_questions_and_the_expanded_island() -> None:
    # Defect: a moment or menu expansion hides the persistent canvas navigation.
    canvas = island(RESTING)[-1]
    for observed in (RESTING, replace(RESTING, dictating=True), replace(RESTING, agent=ASKING)):
        for expanded in (False, True):
            assert tuple(view for view in island(observed, expanded=expanded) if view.key is Key.CANVAS) == (canvas,)


def test_alerts_charger_and_low_battery_read_in_the_resting_facts() -> None:
    # Defect: system alerts disappear, the charger is lost, or a low battery looks like any other.
    alert = replace(
        RESTING, system=SystemStatus(Speakers.AUDIBLE, Wifi.DISCONNECTED), ambient=Ambient("09:41", Battery(15, powered=False, charging=False))
    )
    assert island(alert)[0].slots == ((Glyph("speaker-on"), Glyph("wifi-off"), Text("09:41"), Text("15%", Tone.LOW)),)
    full = replace(RESTING, ambient=Ambient("09:41", Battery(99, powered=True, charging=False)))
    assert island(full)[0].slots == ((Text("09:41"), Glyph("charger")),)


def test_agent_work_keeps_stop_visible_and_its_slots_stable_under_the_pointer() -> None:
    # Defects: hover inserts Stop and shifts the bar, or a long phase overflows.
    view = island(replace(RESTING, agent=WORKING))[0]
    assert view.slots[0] == (
        Spinner("Agent: Comparing both sheets"),
        Text("Comparing both sheets"),
        Control("stop", "Stop agent work", Action.STOP_AGENT),
    )
    assert "Agent: Comparing both sheets" in view.label
    long = island(replace(RESTING, agent=Agent("Reading every attachment in the budget thread", waiting=False)))[0]
    assert long.slots[0][1] == Text("Reading every attachment in…")
    hovered = island(replace(RESTING, agent=WORKING), hovered=Key.ISLAND)[0]
    assert hovered == view


def test_concurrent_activities_share_the_island_at_rest_each_with_its_own_indicator() -> None:
    # Defects: one activity hides another, transcription borrows the agent's spinner, or a quick job offers Stop.
    busy = replace(RESTING, agent=WORKING, job=Job.TRANSCRIBING, recording=RECORDING)
    views = island(busy, hovered=Key.ISLAND)
    assert keys(views) == [Key.ISLAND, Key.CANVAS]
    agent, job, facts, recording = views[0].slots
    assert type(agent[0]) is Spinner and job == (Marker.DOTS,)
    assert facts == (Text("10:22"), Text("73%")) and recording[:2] == (Marker.DOT, Text("02:05"))
    assert "Transcribing" in views[0].label


def test_dictation_takes_the_island_and_detaches_every_activity_beside_it() -> None:
    # Defects: dictation hides running work, or detached work loses its phase.
    views = island(replace(RESTING, dictating=True, agent=WORKING, job=Job.ANSWERING, recording=RECORDING, inbox=2))
    assert [(view.key, view.zone) for view in views] == [
        (Key.AGENT, Zone.LEAD),
        (Key.JOB, Zone.LEAD),
        (Key.ISLAND, Zone.ISLAND),
        (Key.RECORDING, Zone.TRAIL),
        (Key.CANVAS, Zone.TRAIL),
        (Key.INBOX, Zone.TRAIL),
    ]
    agent, job, voice = views[:3]
    assert agent.slots == ((Spinner("Agent: Comparing both sheets"), Control("stop", "Stop agent work", Action.STOP_AGENT)),)
    assert "Comparing both sheets" in agent.label
    assert job.slots == ((Marker.DOTS,),) and job.label == "Answering"
    assert voice.slots == ((Glyph("mic.fill", Tone.MICROPHONE), Marker.WAVE),) and voice.action is Action.STOP_DICTATION


def test_a_waiting_question_takes_the_island_or_waits_beside_dictation_in_attention() -> None:
    # Defects: the question looks like the resting island, opens the menu, or vanishes while you dictate.
    view = island(replace(RESTING, agent=ASKING))[0]
    assert (view.tint, view.action) == (Tint.ATTENTION, Action.OPEN_QUESTION)
    assert view.slots == ((Text("Needs you", strong=True), Glyph("down")),) and ASKING.phase in view.label
    beside = island(replace(RESTING, agent=ASKING, dictating=True))[0]
    assert (beside.key, beside.tint, beside.action) == (Key.AGENT, Tint.ATTENTION, Action.OPEN_QUESTION)


def test_the_inbox_appears_only_while_items_wait_and_caps_its_badge() -> None:
    # Defect: an empty inbox keeps its capsule, or a large count overflows while the exact count is lost.
    assert Key.INBOX not in keys(island(RESTING))
    many = island(replace(RESTING, inbox=120))[-1]
    assert many.key is Key.INBOX and many.slots == ((Glyph("bell"), Badge("99+")),)
    assert many.label.startswith("120 clarifications need your input")
    assert island(replace(RESTING, inbox=1))[-1].label.startswith("1 clarification needs your input")


def test_only_a_temporary_layer_or_the_layout_switched_off_earns_a_lead_capsule() -> None:
    # Defect: the default layout occupies space, or Colemak isn't announced when the layout is off.
    assert keyboard(enabled=True, layer=None) is None
    assert keyboard(enabled=False, layer=None) == "Colemak"
    assert keyboard(enabled=True, layer="NAV · locked") == "NAV · locked"
    view = island(replace(RESTING, keyboard="NAV"))[0]
    assert (view.key, view.zone, view.action) == (Key.LAYER, Zone.LEAD, Action.OPEN_KEYMAP)


def test_recording_phases_read_and_stop_as_the_capture_allows() -> None:
    # Defect: a finishing capture offers Stop again, an interrupted one doesn't ask for attention, or hours overflow.
    assert capture(RecordingState(phase="recording", seconds=3725)) == Capture("1:02:05", can_stop=True, attention=False)
    assert capture(RecordingState(phase="stopping")) == Capture("Stopping…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="finishing")) == Capture("Saving…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="paused")) == Capture("Check recording", can_stop=False, attention=True)
    assert capture(RecordingState(phase="saved", seconds=900)) is None
