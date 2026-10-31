"""Where the island bar's capsules sit."""

from assistant.island_layout import Box, Framed, Metrics, Placed, frame, snap
from assistant.island_model import Key, Zone


def test_the_island_alone_is_centred_with_an_edge_strip_to_the_top() -> None:
    # Defect: the island drifts off centre, or the strip above it doesn't reach the screen edge.
    assert frame([Placed(Key.ISLAND, Zone.ISLAND, 112, 34)], Metrics(1000)) == (Framed(Key.ISLAND, Box(444, 8, 112, 34), Box(444, 0, 112, 8), 1.0),)


def test_neighbours_sit_one_gap_apart_and_grow_outward_in_order() -> None:
    # Defect: zones overlap the island, the gap differs between neighbours, or the order flips.
    placed = [
        Placed(Key.INBOX, Zone.TRAIL, 34, 34),
        Placed(Key.ISLAND, Zone.ISLAND, 112, 34),
        Placed(Key.LAYER, Zone.LEAD, 70, 34),
        Placed(Key.RECORDING, Zone.TRAIL, 86, 34),
        Placed(Key.AGENT, Zone.LEAD, 34, 34),
    ]
    assert [(f.key, f.box.x, f.box.width) for f in frame(placed, Metrics(1000))] == [
        (Key.LAYER, 328, 70),
        (Key.AGENT, 404, 34),
        (Key.ISLAND, 444, 112),
        (Key.RECORDING, 562, 86),
        (Key.INBOX, 654, 34),
    ]


def test_a_capsule_part_way_in_shares_a_gap_scaled_by_the_less_present_neighbour() -> None:
    # Defect: an entering capsule opens a full gap at once, or its neighbour keeps a stale gap.
    placed = [Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.RECORDING, Zone.TRAIL, 86, 34, 0.5), Placed(Key.INBOX, Zone.TRAIL, 34, 34)]
    assert [(f.key, f.box.x, f.box.width) for f in frame(placed, Metrics(1000))] == [
        (Key.ISLAND, 444, 112),
        (Key.RECORDING, 559, 43),
        (Key.INBOX, 605, 34),
    ]
    absent = [Placed(Key.ISLAND, Zone.ISLAND, 112, 34), Placed(Key.RECORDING, Zone.TRAIL, 86, 34, 0), Placed(Key.INBOX, Zone.TRAIL, 34, 34)]
    assert [(f.key, f.box.x) for f in frame(absent, Metrics(1000))] == [(Key.ISLAND, 444), (Key.INBOX, 562)]


def test_snapping_puts_every_edge_on_a_device_pixel() -> None:
    # Defect: Qt and composition round edges differently, so content and glass disagree by a pixel.
    framed = frame([Placed(Key.ISLAND, Zone.ISLAND, 111.3, 34)], Metrics(1001))
    (snapped,) = snap(framed, 1.25)
    edges = (snapped.box.x, snapped.box.x + snapped.box.width, snapped.box.y, snapped.box.y + snapped.box.height)
    assert all(abs(edge * 1.25 - round(edge * 1.25)) < 1e-9 for edge in edges)
