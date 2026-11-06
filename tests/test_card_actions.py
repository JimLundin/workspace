"""A card link acts only when it is exactly one card action; anything else does nothing."""

from contracts.card_actions import OpenCanvas, encode, parse


def test_partial_or_altered_links_are_refused_instead_of_acting_on_defaults() -> None:
    # Defect: a missing field falls back to an empty target, or an unknown
    # action still opens the canvas.
    canvas = encode(OpenCanvas("request"))
    assert parse(canvas) == OpenCanvas("request")
    refused = (
        "workspace://canvas",
        "workspace://canvas?target=",
        "workspace://canvas?target=one&target=two",
        "workspace://canvas?target=one&extra=1",
        "workspace://canvas?target=one#more",
        "workspace://canvas/path?target=one",
        "https://canvas?target=one",
        "workspace://install?target=one",
        "workspace://done?source=chat&item=one",
        canvas + "&target=other",
        "not a link",
    )
    assert [link for link in refused if parse(link) is not None] == []
