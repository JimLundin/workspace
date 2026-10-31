"""A card action survives its link: reserved characters never change which target or request a click names."""

from hypothesis import strategies

from assistant.card_actions import AnswerApproval, CardAction, OpenCanvas, encode, parse
from automation.task import ApprovalDecision
from tests.properties.generation import cases, property_test


def card_actions(draw: strategies.DrawFn) -> CardAction:
    # Identities are non-empty; reserved query characters are the likely collisions.
    identity = draw(
        strategies.one_of(strategies.text(min_size=1, max_size=48), strategies.sampled_from(("a&target=b", "x=y", "#top", "50%+1", "?q")))
    )
    if draw(strategies.booleans()):
        return OpenCanvas(identity)
    return AnswerApproval(identity, draw(strategies.sampled_from(tuple(ApprovalDecision))))


@property_test(cases(card_actions))
def test_every_card_action_parses_back_from_its_link(action: CardAction) -> None:
    assert parse(encode(action)) == action
