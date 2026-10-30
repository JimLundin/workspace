"""A card link acts only when it is exactly one card action; anything else does nothing."""

from assistant.card_actions import AnswerApproval, Decision, encode, parse


def test_partial_or_altered_links_are_refused_instead_of_acting_on_defaults() -> None:
    # Defect: a missing field falls back to an empty target or answer, or an
    # unknown action or decision still reaches the agent.
    decline = encode(AnswerApproval("request", Decision.DECLINE))
    assert parse(decline) == AnswerApproval("request", Decision.DECLINE)
    refused = (
        "workspace://canvas",
        "workspace://canvas?target=",
        "workspace://canvas?target=one&target=two",
        "workspace://canvas?target=one&extra=1",
        "workspace://canvas?target=one#more",
        "workspace://canvas/path?target=one",
        "https://canvas?target=one",
        "workspace://install?target=one",
        "workspace://agent-option?request=one&answer=maybe",
        "workspace://agent-option?answer=approve",
        "workspace://done?source=chat&item=one",
        decline + "&request=other",
        "not a link",
    )
    assert [link for link in refused if parse(link) is not None] == []
