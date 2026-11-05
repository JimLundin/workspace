"""Where the island bar's capsules sit, and where parts sit inside them."""

from desktop_ui.island_layout import LINE, LINES_BOTTOM, LINES_TOP, Box, Content, Framed, Metrics, Placed, Spot, arrange, frame, snap, wrap
from desktop_ui.island_model import Action, Badge, Control, Detail, Glyph, Key, Marker, Spinner, Text, Zone


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


def test_fixed_right_order_survives_activity_changes() -> None:
    # Defect: activity shifts fixed controls or overlaps the cluster.
    fixed = (
        Placed(Key.CANVAS, Zone.LEFT, 36, 34),
        Placed(Key.LAYER, Zone.RIGHT, 36, 34),
        Placed(Key.STATUS, Zone.RIGHT, 180, 34),
    )
    for screen in (480, 1000):
        baseline = frame(fixed, Metrics(screen))
        assert tuple(each.key for each in baseline) == (Key.CANVAS, Key.LAYER, Key.STATUS)
        assert baseline[-1].box.x + baseline[-1].box.width == screen - 12
        framed = frame((Placed(Key.ISLAND, Zone.ISLAND, 272, 320), *fixed), Metrics(screen))
        assert tuple(each for each in framed if each.key is not Key.ISLAND) == baseline
        assert baseline[0].box.x == 12
        assert all(0 <= each.box.x <= each.box.x + each.box.width <= screen for each in framed)
        activity = next((each for each in framed if each.key is Key.ISLAND), None)
        if activity is not None:
            assert activity.box.x >= baseline[0].box.x + baseline[0].box.width + 6
            assert activity.box.x + activity.box.width <= baseline[1].box.x - 6


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


def test_reserved_readings_keep_following_parts_and_capsule_width_stable() -> None:
    # Defect: a shorter reading moves the power glyph or resizes fixed controls;
    # an unexpected wider reading must not clip to its representative reserve.
    def measured(clock: str, battery: str) -> Content:
        return arrange(((Text(clock, reserve="00:00"), Glyph("battery"), Text(battery, reserve="100%")),), width_of)

    baseline = measured("00:00", "100%")
    for clock, battery in (("11:11", "9%"), ("23:59", "—"), ("09:41", "AC")):
        content = measured(clock, battery)
        assert content.width == baseline.width
        assert tuple((spot.x, spot.width) for spot in content.spots) == tuple((spot.x, spot.width) for spot in baseline.spots)
    assert measured("00:00:00", "100%").width > baseline.width


def test_content_narrower_than_a_circle_centres_in_one() -> None:
    # Defect: a lone marker collapses the capsule below its height, losing its round shape.
    content = arrange(((Marker.DOT,),), width_of)
    assert content.width == 34 and content.spots == (Spot(Marker.DOT, 13, 8),)


def test_wrapping_fills_lines_and_ends_overflow_with_an_ellipsis() -> None:
    # Defects: a line overflows the capsule, words go missing between lines, or
    # text that doesn't fit is cut without a sign that more is on the canvas.
    assert wrap("Revenue is up four percent", 12, 2, len) == ("Revenue is", "up four…")
    assert wrap("Revenue is up", 12, 2, len) == ("Revenue is", "up")
    assert wrap("Unbreakablewordhere", 8, 1, len) == ("Unbreak…",)
    assert wrap("   ", 12, 2, len) == ()


def test_detail_lines_sit_under_the_row_and_a_wider_detail_keeps_dismiss_at_the_far_edge() -> None:
    # Defects: detail changes the row's own layout, grows the capsule without its
    # lines, or leaves Dismiss beside the title instead of at the trailing edge.
    dismiss = Control("close", "Dismiss", Action.DISMISS_NOTICE)
    row = ((Glyph("agent"), Text("Budget")), (dismiss,))
    content = arrange(row, width_of, Detail(("Approved totals match",), 2, 200))
    assert content.width == 200 and content.lines == ("Approved totals match",)
    assert content.height == LINES_TOP + LINE + LINES_BOTTOM
    assert [spot.x for spot in content.spots] == [12, 34, 200 - 31]
    steps = arrange(((Spinner("Agent"), Text("Reading budget")),), width_of, Detail(("PowerShell", "Comparing both sheets in detail"), 1))
    assert steps.width == arrange(((Spinner("Agent"), Text("Reading budget")),), width_of).width
    assert len(steps.lines) == 2 and steps.lines[1].endswith("…")
