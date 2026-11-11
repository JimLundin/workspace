"""Activity owns the island; fixed navigation and truthful readings own the right.

The spec here is the test's own, and expectations come from `reading`, so each
test checks how the model composes readings, never which glyphs or words they use.
"""

from dataclasses import replace

from contracts.recording_state import RecordingState
from contracts.status import TRANSCRIBING
from desktop_ui import ambient
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.components.meaning import Tone
from desktop_ui.island_menu import Panel
from desktop_ui.island_model import (
    ELAPSED,
    Action,
    ActivitiesSpec,
    Activity,
    CapsuleView,
    Capture,
    Charge,
    Control,
    IslandSpec,
    Key,
    Marker,
    Observed,
    Part,
    Phased,
    Phases,
    Reading,
    StatusSpec,
    Symbols,
    Text,
    Words,
    Zone,
    capture,
    island,
    order,
    reading,
    tip,
)
from winapi.machine_status import Battery, Memory, PowerUnavailable, Speakers, Wifi

SPEAKERS = frozendict((state, ambient.Reading(f"speaker {state.name}", f"speakers {state.name}")) for state in Speakers)
WIFI = frozendict((state, ambient.Reading(f"wifi {state.name}", f"wifi {state.name}")) for state in Wifi)
SYMBOLS = Symbols(workspace="home", keyboard="keys", charger="plug", cpu="chip", memory="ram")
PHASES: Phases = frozendict(
    {
        "idle": None,
        "starting": Phased("Warming", can_stop=True, attention=False),
        "recording": Phased(ELAPSED, can_stop=True, attention=False),
        "stopping": Phased("Halting", can_stop=False, attention=False),
        "finishing": Phased("Filing", can_stop=False, attention=False),
        "paused": Phased("Look", can_stop=False, attention=True),
        "interrupted": Phased("Look", can_stop=False, attention=True),
        "saved": None,
    }
)
WORDS = Words(
    jobs=frozendict({TRANSCRIBING: "Working"}),
    phases=PHASES,
    stop="halt",
    microphone="mic",
    stop_recording="Halt recording",
    stop_dictation="Halt dictation",
    listening="Hearing",
    open_controls="Open",
    close_controls="Close",
    keyboard="Plain keys",
    battery="Cell",
    charger="Plugged in",
    cpu="Chip",
    memory="Ram",
    of="out of",
    unavailable="unread",
)
SPEC = IslandSpec(
    StatusSpec(
        (Reading.KEYBOARD, Reading.SPEAKER, Reading.WIFI, Reading.BATTERY, Reading.CPU, Reading.MEMORY, Reading.CLOCK),
        SPEAKERS,
        WIFI,
        SYMBOLS,
        frozendict((reading, Panel.SOUND if reading is Reading.SPEAKER else Panel.WORKSPACE) for reading in Reading),
        low_battery=20,
        unread="?",
        mains="Mains",
        widest_percent="100%",
        gigabytes="gig",
        widest_memory="00.0 gig",
        widest_clock="00:00",
        clock="%H:%M",
    ),
    ActivitiesSpec(lead=(Activity.JOB,), trail=(Activity.RECORDING,)),
    WORDS,
)
RESTING = Observed(None, RecordingState(), Ambient("10:22", Battery(73, powered=False, charging=False)), SystemStatus(), dictating=False)
RECORDING = RecordingState(phase="recording", seconds=125)


def view(observed: Observed, key: Key, *, spec: IslandSpec = SPEC, expanded: bool = False, hovered: Key | None = None) -> CapsuleView:
    """Read one identity without depending on other capsules' inventory positions."""
    return next(each for each in island(observed, spec, expanded=expanded, hovered=hovered) if each.key is key)


def parts(observed: Observed, *readings: Reading) -> tuple[Part, ...]:
    return tuple(part for each in readings for part in reading(each, observed, SPEC.status))


def test_at_rest_the_status_capsule_shows_each_reading_in_order_in_its_own_slot() -> None:
    # Defects: idle readings reappear as activity, the fixed capsule gains or drops
    # a reading, two readings share a slot and so their spacing, or the readings
    # leave the order the spec gives.
    views = island(RESTING, SPEC)
    assert tuple((each.key, each.zone) for each in views) == ((Key.STATUS, Zone.RIGHT),)
    expected = tuple(reading(each, RESTING, SPEC.status) for each in SPEC.status.readings if each is not Reading.KEYBOARD)
    assert views[0].slots == expected and views[0].action is Action.OPEN_MENU


def test_a_plain_keyboard_takes_its_place_and_a_reading_with_nothing_to_show_takes_no_slot() -> None:
    # Defects: the keyboard shows while the layout remaps, it shows out of its
    # place, or a reading with nothing to show leaves an empty slot.
    plain = replace(RESTING, plain_keyboard=True)
    assert reading(Reading.KEYBOARD, RESTING, SPEC.status) == () and reading(Reading.KEYBOARD, plain, SPEC.status) != ()
    assert view(plain, Key.STATUS).slots[:2] == (parts(plain, Reading.KEYBOARD), parts(plain, Reading.SPEAKER))
    alone = replace(SPEC, status=replace(SPEC.status, readings=(Reading.KEYBOARD, Reading.CLOCK)))
    assert view(RESTING, Key.STATUS, spec=alone).slots == (parts(RESTING, Reading.CLOCK),)
    assert view(plain, Key.STATUS, spec=alone).slots == (parts(plain, Reading.KEYBOARD), parts(plain, Reading.CLOCK))


def test_resource_readings_keep_one_reserve_and_never_show_an_unread_value_as_zero() -> None:
    # Defects: a changing value resizes the fixed capsule because its reserve
    # follows the value, memory shows in bytes, decimal gigabytes or as a share
    # rather than the gigabytes Windows reports, a reading becomes a control, or an
    # unread value reads as 0.
    def texts(cpu: int | None, memory: Memory | None) -> tuple[Text, ...]:
        observed = replace(RESTING, system=SystemStatus(cpu=cpu, memory=memory))
        return tuple(part for part in parts(observed, Reading.CPU, Reading.MEMORY) if isinstance(part, Text))

    gib = 1 << 30
    busy, idle = Memory(gib * 25 // 2, 32 * gib), Memory(gib // 10, 8 * gib)
    assert tuple(text.text for text in texts(23, busy)) == ("23%", "12.5 gig")
    assert tuple(text.text for text in texts(100, idle)) == ("100%", "0.1 gig")
    shown = tuple(texts(cpu, memory) for cpu, memory in ((23, busy), (100, idle), (None, None)))
    assert len({text.reserve for each in shown for text in each[:1]}) == 1
    assert len({text.reserve for each in shown for text in each[1:]}) == 1
    assert texts(None, None) != texts(0, Memory(0, gib))
    status = view(replace(RESTING, system=SystemStatus(cpu=5, memory=busy)), Key.STATUS)
    assert not any(isinstance(part, Control) for slot in status.slots for part in slot)


def test_fixed_controls_survive_all_activity_menu_and_device_states() -> None:
    # Defect: moments hide status, or status becomes a central activity.
    for speakers in Speakers:
        for wifi in Wifi:
            baseline = replace(RESTING, system=SystemStatus(speakers, wifi))
            for observed in (
                baseline,
                replace(baseline, dictating=True),
                replace(baseline, job=TRANSCRIBING, recording=RECORDING),
            ):
                for expanded in (False, True):
                    # The open menu is the status capsule itself; its row stays.
                    fixed = view(observed, Key.STATUS, expanded=expanded)
                    assert fixed.slots == view(baseline, Key.STATUS).slots
                    assert expanded or fixed == view(baseline, Key.STATUS)
                    activity = (each for each in island(observed, SPEC, expanded=expanded) if each.zone is not Zone.RIGHT)
                    assert all(Text("10:22") not in slot for each in activity for slot in each.slots)


def test_the_battery_fills_to_its_charge_follows_the_charger_and_warns_when_low() -> None:
    # Defects: the battery symbol shows a stale or wrong charge, ignores the
    # charger, an unread battery looks empty-but-read, or a low battery on its own
    # power warns in its text but not its symbol (or not at all).
    def power(percent: int, *, powered: bool) -> tuple[Part, ...]:
        return parts(replace(RESTING, ambient=Ambient("09:41", Battery(percent, powered=powered, charging=False))), Reading.BATTERY)

    assert power(64, powered=False)[-1] == Charge(64, powered=False)
    assert power(64, powered=True)[-1] == Charge(64, powered=True)
    unread = parts(replace(RESTING, ambient=Ambient("09:41", PowerUnavailable.UNKNOWN)), Reading.BATTERY)
    assert unread[-1] == Charge(None, powered=False)

    def tone(percent: int, *, powered: bool) -> Tone:
        text, symbol = power(percent, powered=powered)
        assert isinstance(symbol, Charge) and isinstance(text, Text) and symbol.tone == text.tone
        return text.tone

    assert tone(15, powered=False) != tone(99, powered=False) == tone(15, powered=True)


def test_concurrent_activity_has_distinct_indicators_and_recording_stop_under_the_pointer() -> None:
    # Defects: transcription and recording share one indicator, or Stop shows at rest.
    busy = replace(RESTING, job=TRANSCRIBING, recording=RECORDING)
    job, recording = view(busy, Key.ISLAND).slots
    assert job != recording

    def stops(hovered: Key | None) -> list[Action]:
        return [part.action for slot in view(busy, Key.ISLAND, hovered=hovered).slots for part in slot if isinstance(part, Control)]

    assert stops(None) == [] and stops(Key.ISLAND) == [Action.STOP_RECORDING]


def test_dictation_takes_the_island_and_detaches_every_other_activity_beside_it() -> None:
    # Defect: dictation shares the island with other activity, or loses its stop press.
    observed = replace(RESTING, dictating=True, job=TRANSCRIBING, recording=RECORDING)
    dynamic = tuple(each for each in island(observed, SPEC) if each.zone is not Zone.RIGHT)
    assert tuple(each.key for each in dynamic) == tuple(key for key in order(SPEC) if key not in (Key.STATUS, Key.PANEL))
    centre = next(each for each in dynamic if each.key is Key.ISLAND)
    assert centre.action is Action.STOP_DICTATION
    shown = {part for slot in centre.slots for part in slot}
    assert Marker.WAVE in shown and not shown & {Marker.DOTS, Marker.DOT}
    moved = replace(SPEC, activities=ActivitiesSpec(lead=(Activity.RECORDING, Activity.JOB), trail=()))
    assert [each.key for each in island(observed, moved)][:3] == [Key.RECORDING, Key.JOB, Key.ISLAND]


def test_an_open_panel_hangs_below_the_status_capsule_which_keeps_its_readings() -> None:
    # Defects: the panel opens as the island instead of below the readings, the status
    # capsule loses its readings while open, or activity stays in the bar while the
    # panel lists it.
    busy = replace(RESTING, job=TRANSCRIBING, recording=RECORDING)
    readings, panel = island(busy, SPEC, expanded=True)
    assert (readings.key, readings.slots, readings.action) == (Key.STATUS, view(busy, Key.STATUS).slots, Action.CLOSE_MENU)
    assert (panel.key, panel.zone) == (Key.PANEL, Zone.PANEL)
    assert all(each.key is not Key.PANEL for each in island(busy, SPEC))


def test_a_recording_reads_as_its_phase_says_and_its_elapsed_time_keeps_its_hours() -> None:
    # Defects: an hour-long recording loses its hours, a phase's title or flags are
    # lost on the way to the bar, or a phase that doesn't show lingers.
    assert capture(RecordingState(phase="recording", seconds=3725), PHASES) == Capture("1:02:05", can_stop=True, attention=False)
    assert capture(RecordingState(phase="recording", seconds=65), PHASES) == Capture("01:05", can_stop=True, attention=False)
    assert capture(RecordingState(phase="paused", seconds=65), PHASES) == Capture("Look", can_stop=False, attention=True)
    assert capture(RecordingState(phase="saved", seconds=900), PHASES) is None


def test_each_reading_has_its_own_tip_slot_for_slot() -> None:
    # Defects: the capsule tips every reading with one combined description, a hidden
    # reading keeps its tip so every later reading shows its neighbour's, or a tip
    # misses the value its reading shows.
    for observed in (RESTING, replace(RESTING, plain_keyboard=True)):
        status = view(observed, Key.STATUS)
        shown = tuple(each for each in SPEC.status.readings if reading(each, observed, SPEC.status))
        assert status.tips == tuple(tip(each, observed, SPEC) for each in shown)
        assert len(set(status.tips)) == len(status.slots)
        assert "10:22" in status.tips[shown.index(Reading.CLOCK)] and "73" in status.tips[shown.index(Reading.BATTERY)]
