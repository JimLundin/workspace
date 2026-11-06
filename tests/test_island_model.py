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
    Detail,
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
)
from desktop_ui.island_moment import Notice
from winapi.machine_status import Battery, Speakers, Wifi

RESTING = Observed(None, None, RecordingState(), Ambient("10:22", Battery(73, powered=False, charging=False)), SystemStatus(), 0, dictating=False)
WORKING = Agent("Comparing both sheets", waiting=False)
ASKING = Agent("Which sheet should the reply cover?", waiting=True)
RECORDING = RecordingState(phase="recording", seconds=125)


def view(observed: Observed, key: Key, *, expanded: Expansion | None = None, hovered: Key | None = None) -> CapsuleView:
    """Read one identity without depending on other capsules' inventory positions."""
    return next(each for each in island(observed, expanded=expanded, hovered=hovered) if each.key is key)


def test_idle_has_only_device_status_and_clock_power_on_right() -> None:
    # Defect: idle readings reappear in the centre, or the fixed capsule gains a reading.
    views = island(RESTING)
    assert tuple(each.key for each in views) == (Key.STATUS,)
    assert tuple(each.zone for each in views) == (Zone.RIGHT,)
    assert views[-1].slots == (
        (
            Glyph("speaker-unknown"),
            Glyph("wifi-unknown"),
        ),
        (Text("10:22", reserve="00:00"), Glyph("battery"), Text("73%", reserve="100%")),
    )


def test_a_plain_keyboard_is_a_reading_beside_the_speaker_and_wifi() -> None:
    # Defects: the keyboard shows while the layout remaps, or it becomes a
    # control in its own slot, spaced apart from the speaker and Wi-Fi.
    plain = view(replace(RESTING, plain_keyboard=True), Key.STATUS)
    assert plain.slots[0] == (Glyph("keyboard"), Glyph("speaker-unknown"), Glyph("wifi-unknown"))
    assert len(plain.slots) == len(view(RESTING, Key.STATUS).slots)
    assert Glyph("keyboard") not in view(RESTING, Key.STATUS).slots[0]


def test_fixed_controls_survive_all_activity_menu_and_device_states() -> None:
    # Defect: moments hide status, or status becomes a central activity.
    for speakers in Speakers:
        for wifi in Wifi:
            baseline = replace(RESTING, system=SystemStatus(speakers, wifi))
            for observed in (
                baseline,
                replace(baseline, dictating=True),
                replace(baseline, agent=ASKING),
                replace(baseline, agent=WORKING, job=Job.TRANSCRIBING, recording=RECORDING),
            ):
                for expanded in (None, Expansion.MENU, Expansion.REQUEST):
                    # The open menu is the status capsule itself; its row stays.
                    fixed = view(observed, Key.STATUS, expanded=expanded)
                    assert fixed.slots == view(baseline, Key.STATUS).slots
                    assert expanded is Expansion.MENU or fixed == view(baseline, Key.STATUS)
                    activity = (each for each in island(observed, expanded=expanded) if each.zone is not Zone.RIGHT)
                    assert all(Text("10:22") not in slot for each in activity for slot in each.slots)
            status = view(baseline, Key.STATUS)
            assert status.slots[-2] == (Glyph(baseline.system.speaker_icon), Glyph(baseline.system.wifi_icon))
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
    observed = replace(RESTING, dictating=True, agent=WORKING, job=Job.TRANSCRIBING, recording=RECORDING, inbox=2)
    dynamic = tuple(each for each in island(observed) if each.zone is not Zone.RIGHT)
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
    busy = replace(RESTING, agent=WORKING, job=Job.TRANSCRIBING, recording=RECORDING, inbox=2)
    opened = island(busy, expanded=Expansion.MENU)
    assert tuple(each.key for each in opened) == (Key.INBOX, Key.STATUS)
    readings = view(busy, Key.STATUS).slots
    assert opened[-1] == CapsuleView(Key.STATUS, Zone.RIGHT, readings, "Workspace controls · Escape closes", Action.CLOSE_MENU)
    asking = replace(busy, agent=ASKING)
    assert tuple(each.key for each in island(asking, expanded=Expansion.REQUEST)) == (Key.ISLAND, Key.INBOX, Key.STATUS)
    assert view(asking, Key.STATUS, expanded=Expansion.REQUEST) == view(asking, Key.STATUS)


def test_inbox_only_exists_while_pending_and_keeps_exact_count_in_label() -> None:
    assert Key.INBOX not in tuple(each.key for each in island(RESTING))
    many = view(replace(RESTING, inbox=120), Key.INBOX)
    assert many.slots == ((Glyph("bell"), Badge("99+")),)
    assert many.label.startswith("120 clarifications need your input")
    assert view(replace(RESTING, inbox=1), Key.INBOX).label.startswith("1 clarification needs your input")


def test_recording_phases_read_and_stop_as_capture_allows() -> None:
    assert capture(RecordingState(phase="recording", seconds=3725)) == Capture("1:02:05", can_stop=True, attention=False)
    assert capture(RecordingState(phase="stopping")) == Capture("Stopping…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="finishing")) == Capture("Saving…", can_stop=False, attention=False)
    assert capture(RecordingState(phase="paused")) == Capture("Check recording", can_stop=False, attention=True)
    assert capture(RecordingState(phase="saved", seconds=900)) is None


FINDING = Notice("canvas:result:budget:5", "Budget checked", "Approved totals match the forecast.", "result:budget", 5)


def test_a_notice_takes_the_island_with_its_reply_and_detaches_running_work() -> None:
    # Defects: the notice loses its text, its press doesn't open the item, work
    # vanishes instead of detaching, or a question's notice isn't tinted.
    observed = replace(RESTING, agent=WORKING, recording=RECORDING, notice=FINDING)
    views = island(observed)
    assert [each.key for each in views if each.zone in (Zone.LEAD, Zone.ISLAND, Zone.TRAIL)] == [Key.AGENT, Key.ISLAND, Key.RECORDING]
    notice = view(observed, Key.ISLAND)
    assert notice.slots == ((Glyph("agent"), Text("Budget checked", strong=True)), ())
    assert notice.detail == Detail(("Approved totals match the forecast.",), 2, 340)
    assert (notice.action, notice.tint) == (Action.OPEN_NOTICE, Tint.NONE)
    assert view(observed, Key.ISLAND, hovered=Key.ISLAND).slots[-1] == (Control("close", "Dismiss", Action.DISMISS_NOTICE),)
    question = replace(FINDING, question=True)
    assert view(replace(RESTING, notice=question), Key.ISLAND).tint is Tint.ATTENTION


def test_agent_work_reveals_its_earlier_steps_only_under_the_pointer() -> None:
    # Defect: the steps show at rest, or hovering widens the capsule beside its neighbours.
    working = replace(RESTING, agent=replace(WORKING, steps=("PowerShell", "Reading budget.xlsx")))
    assert view(working, Key.ISLAND).detail is None
    hovered = view(working, Key.ISLAND, hovered=Key.ISLAND)
    assert hovered.detail == Detail(("PowerShell", "Reading budget.xlsx"), 1)
    assert hovered.slots == view(working, Key.ISLAND).slots


def test_the_bell_counts_questions_and_unread_notices_and_names_each() -> None:
    # Defects: unread notices don't reach the bell, or its label misstates what waits.
    bell = view(replace(RESTING, inbox=1, unread=2), Key.INBOX)
    assert bell.slots == ((Glyph("bell"), Badge("3")),)
    assert bell.label == "1 clarification needs your input · 2 new from the agent · Open inbox · Hold V + T"
    assert view(replace(RESTING, unread=1), Key.INBOX).label == "1 new from the agent · Open inbox · Hold V + T"
