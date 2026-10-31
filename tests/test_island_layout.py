"""Where the island bar's capsules sit, and where parts sit inside them."""

from assistant.island_layout import Box, Framed, Metrics, Placed, Spot, arrange, frame, snap
from assistant.island_model import Action, Badge, Control, Glyph, Key, Marker, Spinner, Text, Zone


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


def width_of(text: Text) -> float:
    return len(text.text) * 7


def test_text_content_pads_twelve_and_separates_slots_and_readings_further_than_parts() -> None:
    # Defects: readings crowd the capsule edge, two slots read as one, or two
    # readings run together while a symbol drifts from the text it labels.
    content = arrange(((Spinner("Transcribing"),), (Text("10:22"), Text("73%"))), width_of)
    assert [spot.x for spot in content.spots] == [12, 38, 85]
    assert content.width == 12 + 14 + 12 + 35 + 12 + 21 + 12
    assert [spot.x for spot in arrange(((Text("Needs you"), Glyph("down")),), width_of).spots] == [12, 81]


def test_a_control_at_the_edge_sits_concentric_and_a_badge_takes_no_width() -> None:
    # Defects: Stop keeps the text padding and breaks the 3 px concentric inset,
    # or the count badge widens the inbox capsule.
    stop = Control("stop", "Stop agent work", Action.STOP_AGENT)
    content = arrange(((Spinner("Agent working"), stop),), width_of)
    assert content.spots[-1] == Spot(stop, 30, 28) and content.width == 61
    assert arrange(((Glyph("bell"), Badge("99+")),), width_of).width == arrange(((Glyph("bell"),),), width_of).width == 36


def test_content_narrower_than_a_circle_centres_in_one() -> None:
    # Defect: a lone marker collapses the capsule below its height, losing its round shape.
    content = arrange(((Marker.DOT,),), width_of)
    assert content.width == 34 and content.spots == (Spot(Marker.DOT, 13, 8),)
