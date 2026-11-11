"""Activity owns the island; fixed navigation and truthful readings own the right.

The spec here is the test's own, and expectations come from `reading`, so each
test checks how the model composes readings, never which glyphs or words they use.
"""

from dataclasses import replace

from contracts.recording_state import RecordingState
from contracts.status import TRANSCRIBING
from desktop_ui import ambient
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.island_model import (
    ELAPSED,
    Action,
    ActivitiesSpec,
    Activity,
    CapsuleView,
    Capture,
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
)
from winapi.machine_status import Battery, Speakers, Wifi

SPEAKERS = frozendict((state, ambient.Reading(f"speaker {state.name}", f"speakers {state.name}")) for state in Speakers)
WIFI = frozendict((state, ambient.Reading(f"wifi {state.name}", f"wifi {state.name}")) for state in Wifi)
SYMBOLS = Symbols(keyboard="keys", clock="time", charger="plug", battery="cell", cpu="chip", memory="ram")
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
    charger="Plugged in",
    cpu="Chip",
    memory="Ram",
    unavailable="unread",
)
SPEC = IslandSpec(
    StatusSpec(
        ((Reading.KEYBOARD, Reading.SPEAKER, Reading.WIFI), (Reading.POWER, Reading.BATTERY, Reading.CPU, Reading.MEMORY), (Reading.CLOCK,)),
        SPEAKERS,
        WIFI,
        SYMBOLS,
        low_battery=20,
        unread="?",
        mains="Mains",
        widest_percent="100%",
        widest_clock="00:00",
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


def test_at_rest_the_status_capsule_shows_each_group_of_readings_in_order_with_a_rule_between() -> None:
    # Defects: idle readings reappear as activity, the fixed capsule gains or drops
    # a reading, a group's readings leave the order the spec gives, or groups run
    # together without their rule.
    views = island(RESTING, SPEC)
    assert tuple((each.key, each.zone) for each in views) == ((Key.STATUS, Zone.RIGHT),)
    rule = (Marker.RULE,)
    devices, machine, clock = (parts(RESTING, *group) for group in SPEC.status.groups)
    assert views[0].slots == (devices, rule, machine, rule, clock) and views[0].action is Action.OPEN_MENU


def test_a_plain_keyboard_joins_its_group_and_an_empty_group_takes_no_slot() -> None:
    # Defects: the keyboard shows while the layout remaps, it opens its own slot
    # beside its group, or a group with nothing to show leaves an empty slot or a
    # rule with nothing on one side.
    plain = replace(RESTING, plain_keyboard=True)
    assert reading(Reading.KEYBOARD, RESTING, SPEC.status) == () and reading(Reading.KEYBOARD, plain, SPEC.status) != ()
    assert view(plain, Key.STATUS).slots[0] == parts(plain, Reading.KEYBOARD, Reading.SPEAKER, Reading.WIFI)
    assert view(RESTING, Key.STATUS).slots[0] == parts(RESTING, Reading.SPEAKER, Reading.WIFI)
    alone = replace(SPEC, status=replace(SPEC.status, groups=((Reading.KEYBOARD,), (Reading.CLOCK,))))
    assert view(RESTING, Key.STATUS, spec=alone).slots == (parts(RESTING, Reading.CLOCK),)
    assert view(plain, Key.STATUS, spec=alone).slots == (parts(plain, Reading.KEYBOARD), (Marker.RULE,), parts(plain, Reading.CLOCK))


def test_resource_readings_keep_one_reserve_and_never_show_an_unread_value_as_zero() -> None:
    # Defects: a value from 9% to 100% resizes the fixed capsule because its reserve
    # follows the value, a reading becomes a control, or an unread value reads as 0%.
    def texts(cpu: int | None, memory: int | None) -> tuple[Text, ...]:
        observed = replace(RESTING, system=SystemStatus(cpu=cpu, memory=memory))
        return tuple(part for part in parts(observed, Reading.CPU, Reading.MEMORY) if isinstance(part, Text))

    for cpu, memory in ((23, 61), (100, 9)):
        shown = texts(cpu, memory)
        assert f"{cpu}" in shown[0].text and f"{memory}" in shown[1].text
    assert len({text.reserve for values in ((23, 61), (100, 9), (None, None)) for text in texts(*values)}) == 1
    assert texts(None, None) != texts(0, 0)
    status = view(replace(RESTING, system=SystemStatus(cpu=5, memory=5)), Key.STATUS)
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


def test_power_follows_the_charger_and_a_low_battery_takes_a_warning_tone() -> None:
    # Defects: the power reading ignores the charger, or a low battery on its own
    # power reads like a healthy one.
    def power(percent: int, *, powered: bool) -> tuple[Part, ...]:
        return parts(replace(RESTING, ambient=Ambient("09:41", Battery(percent, powered=powered, charging=False))), Reading.POWER, Reading.BATTERY)

    assert power(99, powered=True)[0] != power(99, powered=False)[0]
    low, high = power(15, powered=False)[-1], power(99, powered=False)[-1]
    assert isinstance(low, Text) and isinstance(high, Text) and low.tone != high.tone
    plugged = power(15, powered=True)[-1]
    assert isinstance(plugged, Text) and plugged.tone == high.tone


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
    assert tuple(each.key for each in dynamic) == tuple(key for key in order(SPEC) if key is not Key.STATUS)
    centre = next(each for each in dynamic if each.key is Key.ISLAND)
    assert centre.action is Action.STOP_DICTATION
    shown = {part for slot in centre.slots for part in slot}
    assert Marker.WAVE in shown and not shown & {Marker.DOTS, Marker.DOT}
    moved = replace(SPEC, activities=ActivitiesSpec(lead=(Activity.RECORDING, Activity.JOB), trail=()))
    assert [each.key for each in island(observed, moved)][:3] == [Key.RECORDING, Key.JOB, Key.ISLAND]


def test_the_status_capsule_expands_into_the_menu() -> None:
    # Defects: the menu opens as the island instead of the capsule that opened it,
    # that capsule loses its readings while open, or activity stays in the bar while
    # the menu lists it.
    busy = replace(RESTING, job=TRANSCRIBING, recording=RECORDING)
    (opened,) = island(busy, SPEC, expanded=True)
    assert (opened.key, opened.zone, opened.slots, opened.action) == (Key.STATUS, Zone.RIGHT, view(busy, Key.STATUS).slots, Action.CLOSE_MENU)


def test_a_recording_reads_as_its_phase_says_and_its_elapsed_time_keeps_its_hours() -> None:
    # Defects: an hour-long recording loses its hours, a phase's title or flags are
    # lost on the way to the bar, or a phase that doesn't show lingers.
    assert capture(RecordingState(phase="recording", seconds=3725), PHASES) == Capture("1:02:05", can_stop=True, attention=False)
    assert capture(RecordingState(phase="recording", seconds=65), PHASES) == Capture("01:05", can_stop=True, attention=False)
    assert capture(RecordingState(phase="paused", seconds=65), PHASES) == Capture("Look", can_stop=False, attention=True)
    assert capture(RecordingState(phase="saved", seconds=900), PHASES) is None
