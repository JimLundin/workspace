"""How capsules move between views: arriving, morphing, cross-fading and leaving."""

from desktop_ui.island_layout import Content, Spot
from desktop_ui.island_model import Action, CapsuleView, Glyph, Key, Text, Zone
from desktop_ui.island_motion import IslandMotion, Shown, Springs, Timing, advance, finish, placed, retarget, settled
from desktop_ui.motion import Spring


def shown(key: Key, zone: Zone, width: float, *parts: Text | Glyph) -> Shown:
    return Shown(CapsuleView(key, zone, (parts,), key.name, Action.OPEN_MENU), Content(width, tuple(Spot(part, 12, 10) for part in parts), 34))


SPRINGS = Springs(morph=Spring(0.86, 0.42), appear=Spring(0.78, 0.42), leave=Spring(1.0, 0.3), fade=Spring(1.0, 0.2))
"""The test's own springs; each settles well within a second."""
TIMING = Timing(pulse=2.0, lag=0.25, opaque_at=0.5, wave_sample=0.04)

ISLAND = shown(Key.ISLAND, Zone.ISLAND, 112, Text("10:22"))
RECORDING = shown(Key.RECORDING, Zone.TRAIL, 36, Text("02:05"))


def run(motion: IslandMotion, seconds: float) -> IslandMotion:
    for _ in range(round(seconds * 60)):
        motion = advance(motion, 1 / 60)
    return motion


def test_a_new_capsule_grows_from_nothing_beside_a_resting_island() -> None:
    # Defects: an arriving capsule appears at full size, or the island restarts its own arrival.
    resting = retarget(IslandMotion(), (ISLAND,), SPRINGS, animate=False)
    arriving = retarget(resting, (ISLAND, RECORDING), SPRINGS, animate=True)
    island, recording = placed(arriving, 34)
    assert (island.presence, recording.presence) == (1, 0) and recording.width == 36
    halfway = placed(run(arriving, 0.1), 34)
    assert 0 < halfway[1].presence < 1 and halfway[0].presence == 1
    assert settled(run(arriving, 2)) and placed(run(arriving, 2), 34)[1].presence == 1


def test_a_leaving_capsule_keeps_its_last_content_until_it_has_collapsed() -> None:
    # Defects: the capsule vanishes at once, or empties before it has collapsed.
    both = retarget(IslandMotion(), (ISLAND, RECORDING), SPRINGS, animate=False)
    leaving = run(retarget(both, (ISLAND,), SPRINGS, animate=True), 0.1)
    assert [moving.key for moving in leaving.capsules] == [Key.ISLAND, Key.RECORDING]
    assert leaving.capsules[1].content == RECORDING.content and 0 < leaving.capsules[1].presence.value < 1
    assert [moving.key for moving in run(leaving, 2).capsules] == [Key.ISLAND]


def test_returning_mid_departure_reverses_from_the_current_presence() -> None:
    # Defect: a capsule called back while leaving restarts from zero and flickers.
    both = retarget(IslandMotion(), (ISLAND, RECORDING), SPRINGS, animate=False)
    leaving = run(retarget(both, (ISLAND,), SPRINGS, animate=True), 0.08)
    returning = retarget(leaving, (ISLAND, RECORDING), SPRINGS, animate=True)
    assert returning.capsules[1].presence.value == leaving.capsules[1].presence.value


def test_new_parts_fade_over_the_old_but_a_changing_reading_updates_in_place() -> None:
    # Defects: content swaps with no crossing, or a ticking timer blinks every second.
    resting = retarget(IslandMotion(), (ISLAND,), SPRINGS, animate=False)
    ticked = retarget(resting, (shown(Key.ISLAND, Zone.ISLAND, 112, Text("10:23")),), SPRINGS, animate=True)
    assert ticked.capsules[0].previous is None and ticked.capsules[0].fade.value == 1
    alerted = retarget(resting, (shown(Key.ISLAND, Zone.ISLAND, 140, Glyph("wifi-off"), Text("10:22")),), SPRINGS, animate=True)
    assert alerted.capsules[0].previous == ISLAND.content and alerted.capsules[0].fade.value == 0
    assert run(alerted, 1).capsules[0].previous is None


def test_reduced_motion_finishes_every_capsule_at_once() -> None:
    # Defects: turning motion off mid-flight leaves capsules half-shown with the
    # loop running, or the menu opens collapsed.
    both = retarget(IslandMotion(), (ISLAND, RECORDING), SPRINGS, animate=False)
    flight = run(retarget(both, (shown(Key.ISLAND, Zone.ISLAND, 160, Glyph("wifi-off"), Text("10:22")),), SPRINGS, animate=True), 0.05)
    done = finish(flight)
    assert settled(done) and [(each.key, each.width, each.presence) for each in placed(done, 34)] == [(Key.ISLAND, 160, 1)]
    menu = Shown(ISLAND.view, Content(272, (), 300))
    assert [(each.width, each.height) for each in placed(retarget(both, (menu,), SPRINGS, animate=False), 34)] == [(272, 300)]
