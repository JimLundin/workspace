"""Where the island bar's capsules sit, and where parts sit inside them."""

from desktop_ui.island_layout import Box, Content, Framed, Metrics, Placed, Spot, arrange, frame, snap
from desktop_ui.island_model import Action, Control, Glyph, Key, Marker, Text, Zone, order
from desktop_ui.spec.island import ISLAND
from desktop_ui.spec.sizes import SIZES

ORDER = order(ISLAND)


def metrics(width: float) -> Metrics:
    return Metrics(width, SIZES.bar.top, SIZES.bar.gap, SIZES.bar.edge)


def test_the_island_alone_is_centred_with_an_edge_strip_to_the_top() -> None:
    # Defect: the island drifts off centre, or the strip above it doesn't reach the screen edge.
    assert frame([Placed(Key.ISLAND, Zone.ISLAND, 112, 34)], metrics(1000), ORDER) == (
        Framed(Key.ISLAND, Box(444, 8, 112, 34), Box(444, 0, 112, 8), 1.0),
    )


def test_neighbours_sit_one_gap_apart_and_grow_outward_in_order() -> None:
    # Defect: zones overlap the island, the gap differs between neighbours, or the order flips.
    placed = [Placed(Key.RECORDING, Zone.TRAIL, 86, 34), Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.JOB, Zone.LEAD, 70, 34)]
    assert [(f.key, f.box.x, f.box.width) for f in frame(placed, metrics(1000), ORDER)] == [
        (Key.JOB, 368, 70),
        (Key.ISLAND, 444, 112),
        (Key.RECORDING, 562, 86),
    ]


def test_a_capsule_part_way_in_opens_a_gap_scaled_by_its_presence() -> None:
    # Defect: an entering capsule opens a full gap at once, or an absent one still takes space.
    placed = [Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.RECORDING, Zone.TRAIL, 86, 34, 0.5)]
    assert [(f.key, f.box.x, f.box.width) for f in frame(placed, metrics(1000), ORDER)] == [(Key.ISLAND, 444, 112), (Key.RECORDING, 559, 43)]
    absent = [Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.RECORDING, Zone.TRAIL, 86, 34, 0)]
    assert [(f.key, f.box.x) for f in frame(absent, metrics(1000), ORDER)] == [(Key.ISLAND, 444)]


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
        assert baseline[-1].box.x + baseline[-1].box.width == screen - 12
        framed = frame((Placed(Key.ISLAND, Zone.ISLAND, 272, 320), *fixed), metrics(screen), ORDER)
        assert tuple(each for each in framed if each.key is not Key.ISLAND) == baseline
        assert all(0 <= each.box.x <= each.box.x + each.box.width <= screen for each in framed)
        activity = next((each for each in framed if each.key is Key.ISLAND), None)
        if activity is not None:
            assert activity.box.x + activity.box.width <= baseline[0].box.x - 6


def width_of(text: Text) -> float:
    return len(text.text) * 7


def test_text_content_pads_twelve_and_separates_slots_and_readings_further_than_parts() -> None:
    # Defects: readings crowd the capsule edge, two slots read as one, or two
    # readings run together while a symbol drifts from the text it labels.
    content = arrange(((Marker.DOTS,), (Text("10:22"), Text("73%"))), width_of, SIZES)
    assert [spot.x for spot in content.spots] == [12, 42, 89]
    assert content.width == 12 + 18 + 12 + 35 + 12 + 21 + 12
    assert [spot.x for spot in arrange(((Text("Recording"), Glyph("stop")),), width_of, SIZES).spots] == [12, 81]


def test_a_control_at_the_edge_sits_concentric() -> None:
    # Defect: Stop keeps the text padding and breaks the 3 px concentric inset.
    stop = Control("stop", "Stop recording", Action.STOP_RECORDING)
    content = arrange(((Marker.DOT, Text("02:05"), stop),), width_of, SIZES)
    assert content.spots[-1] == Spot(stop, 67, 28) and content.width == 98


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
    assert content.width == 34 and content.spots == (Spot(Marker.DOT, 13, 8),)
