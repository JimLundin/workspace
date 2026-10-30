"""A card action survives its link: reserved characters never change which item or answer a click names."""

from hypothesis import strategies

from assistant.card_actions import AnswerApproval, AnswerConsole, CardAction, Decision, ItemAction, OpenCanvas, Verb, encode, parse
from assistant.feed_sources import SourceKey, SourceKind
from tests.properties.generation import cases, property_test


def card_actions(draw: strategies.DrawFn) -> CardAction:
    # Identities are non-empty; reserved query characters are the likely collisions.
    identity = draw(strategies.one_of(strategies.text(min_size=1, max_size=48), strategies.sampled_from(("a&item=b", "x=y", "#top", "50%+1", "?q"))))
    text = draw(strategies.text(max_size=48))
    match draw(strategies.integers(0, 3)):
        case 0:
            return OpenCanvas(identity)
        case 1:
            return AnswerApproval(identity, draw(strategies.sampled_from(tuple(Decision))))
        case 2:
            return AnswerConsole(identity, draw(strategies.integers(0, 64)), text)
        case _:
            return ItemAction(draw(strategies.sampled_from(tuple(Verb))), SourceKey(draw(strategies.sampled_from(tuple(SourceKind))), identity))


@property_test(cases(card_actions))
def test_every_card_action_parses_back_from_its_link(action: CardAction) -> None:
    assert parse(encode(action)) == action
