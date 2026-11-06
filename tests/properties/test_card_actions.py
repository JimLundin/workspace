"""A card action survives its link: reserved characters never change which target a click names."""

from hypothesis import strategies

from contracts.card_actions import OpenCanvas, encode, parse
from tests.properties.generation import cases, property_test


def card_actions(draw: strategies.DrawFn) -> OpenCanvas:
    # Identities are non-empty; reserved query characters are the likely collisions.
    identity = draw(
        strategies.one_of(strategies.text(min_size=1, max_size=48), strategies.sampled_from(("a&target=b", "x=y", "#top", "50%+1", "?q")))
    )
    return OpenCanvas(identity)


@property_test(cases(card_actions))
def test_every_card_action_parses_back_from_its_link(action: OpenCanvas) -> None:
    assert parse(encode(action)) == action
