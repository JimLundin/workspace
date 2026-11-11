"""Where the island bar's capsules sit, and where parts sit inside them.

The sizes here are the test's own, so each test checks how the layout places
capsules and parts relative to the sizes it is given, never the bar's real positions.
"""

from itertools import pairwise

from desktop_ui.island_layout import Content, Framed, Metrics, Placed, Spot, arrange, frame, snap
from desktop_ui.island_model import Action, Control, Glyph, Key, Marker, Text, Zone, order
from tests import test_bar_specs, test_island_model

ORDER = order(test_island_model.SPEC)

SIZES = test_bar_specs.BASE
BAR = SIZES.bar
CAPSULE = SIZES.capsule


def metrics(width: float) -> Metrics:
    return Metrics(width, BAR.top, BAR.gap, BAR.edge)


def end(framed: Framed) -> float:
    return framed.box.x + framed.box.width


def gaps(framed: tuple[Framed, ...]) -> list[float]:
    return [right.box.x - end(left) for left, right in pairwise(framed)]


def test_activity_sits_one_gap_left_of_the_right_capsule_in_order() -> None:
    # Defect: activity drifts away from the status capsule, touches it, flips its order,
    # or the gap differs between neighbours.
    status = Placed(Key.STATUS, Zone.RIGHT, 216, 34)
    placed = [Placed(Key.RECORDING, Zone.TRAIL, 86, 34), status, Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.JOB, Zone.LEAD, 70, 34)]
    framed = frame(placed, metrics(1000), ORDER)
    assert [(f.key, f.box.width) for f in framed] == [(Key.JOB, 70), (Key.ISLAND, 112), (Key.RECORDING, 86), (Key.STATUS, 216)]
    assert end(framed[-1]) == 1000 - BAR.edge
    assert gaps(framed) == [BAR.gap] * 3
    assert all(f.box.y == BAR.top for f in framed)
    alone = frame([Placed(Key.RECORDING, Zone.TRAIL, 86, 34), status], metrics(1000), ORDER)
    assert gaps(alone) == [BAR.gap]


def test_a_capsule_part_way_in_opens_a_gap_scaled_by_its_presence() -> None:
    # Defect: an entering capsule opens a full gap at once, or an absent one still takes space.
    status = Placed(Key.STATUS, Zone.RIGHT, 216, 34)
    entering = frame([Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.RECORDING, Zone.TRAIL, 86, 34, 0.5), status], metrics(1000), ORDER)
    assert [f.box.width for f in entering] == [112, 43, 216]
    assert gaps(entering) == [BAR.gap / 2, BAR.gap]
    absent = frame([Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.RECORDING, Zone.TRAIL, 86, 34, 0), status], metrics(1000), ORDER)
    assert [f.key for f in absent] == [Key.ISLAND, Key.STATUS]
    assert gaps(absent) == [BAR.gap]


def test_snapping_puts_every_edge_on_a_device_pixel() -> None:
    # Defect: Qt and composition round edges differently, so content and glass disagree by a pixel.
    framed = frame([Placed(Key.ISLAND, Zone.ISLAND, 111.3, 34)], metrics(1001), ORDER)
    (snapped,) = snap(framed, 1.25)
    edges = (snapped.box.x, snapped.box.x + snapped.box.width, snapped.box.y, snapped.box.y + snapped.box.height)
    assert all(abs(edge * 1.25 - round(edge * 1.25)) < 1e-9 for edge in edges)


def test_the_fixed_right_cluster_survives_activity_changes() -> None:
    # Defect: activity shifts the fixed cluster or overlaps it.
    fixed = (Placed(Key.STATUS, Zone.RIGHT, 216, 34),)
    for screen in (480, 1000):
        baseline = frame(fixed, metrics(screen), ORDER)
        assert tuple(each.key for each in baseline) == (Key.STATUS,)
        assert end(baseline[-1]) == screen - BAR.edge
        framed = frame((Placed(Key.ISLAND, Zone.ISLAND, 272, 320), *fixed), metrics(screen), ORDER)
        assert tuple(each for each in framed if each.key is not Key.ISLAND) == baseline
        assert all(0 <= each.box.x <= end(each) <= screen for each in framed)
        activity = next((each for each in framed if each.key is Key.ISLAND), None)
        if activity is not None:
            assert end(activity) <= baseline[0].box.x - BAR.gap


def width_of(text: Text) -> float:
    return len(text.text) * 7


def test_text_content_pads_its_ends_and_separates_slots_and_readings_further_than_parts() -> None:
    # Defects: readings crowd the capsule edge, two slots read as one, two
    # readings run together, a symbol sits as close to the reading before it as to
    # its own, or Stop drifts from the reading it stops.
    content = arrange(((Marker.DOTS,), (Text("10:22"), Text("73%"))), width_of, SIZES)
    pad, slot = CAPSULE.text_pad, CAPSULE.slot_gap
    assert [spot.x for spot in content.spots] == [pad, pad + CAPSULE.dots + slot, pad + CAPSULE.dots + slot + 35 + slot]
    assert content.width == content.spots[-1].x + 21 + pad
    stop = Control("stop", "Stop recording", Action.STOP_RECORDING)
    labelled = arrange(((Text("Recording"), stop),), width_of, SIZES)
    assert [spot.x for spot in labelled.spots] == [pad, pad + 63 + CAPSULE.part_gap]
    readings = arrange(((Glyph("cpu"), Text("5%"), Glyph("memory")),), width_of, SIZES)
    assert [spot.x for spot in readings.spots] == [pad, pad + CAPSULE.icon + CAPSULE.part_gap, pad + CAPSULE.icon + CAPSULE.part_gap + 14 + slot]


def test_a_control_at_the_edge_sits_concentric() -> None:
    # Defect: Stop keeps the text padding and breaks the concentric inset.
    stop = Control("stop", "Stop recording", Action.STOP_RECORDING)
    content = arrange(((Marker.DOT, Text("02:05"), stop),), width_of, SIZES)
    last = content.spots[-1]
    assert last.width == CAPSULE.control and content.width - (last.x + last.width) == CAPSULE.inset


def test_reserved_readings_keep_following_parts_and_capsule_width_stable() -> None:
    # Defect: a shorter reading moves the power glyph or resizes fixed controls;
    # an unexpected wider reading must not clip to its representative reserve.
    def measured(clock: str, battery: str) -> Content:
        return arrange(((Text(clock, reserve="00:00"), Glyph("battery"), Text(battery, reserve="100%")),), width_of, SIZES)

    baseline = measured("00:00", "100%")
    for clock, battery in (("11:11", "9%"), ("23:59", "—"), ("09:41", "AC")):
        content = measured(clock, battery)
        assert content.width == baseline.width
        assert tuple((spot.x, spot.width) for spot in content.spots) == tuple((spot.x, spot.width) for spot in baseline.spots)
    assert measured("00:00:00", "100%").width > baseline.width


def test_content_narrower_than_a_circle_centres_in_one() -> None:
    # Defect: a lone marker collapses the capsule below its height, losing its round shape.
    content = arrange(((Marker.DOT,),), width_of, SIZES)
    assert content.width == CAPSULE.height and content.spots == (Spot(Marker.DOT, (CAPSULE.height - CAPSULE.dot) / 2, CAPSULE.dot),)
