"""A card link acts only when it is exactly one card action; anything else does nothing."""

from assistant.card_actions import ItemAction, Verb, encode, parse
from assistant.feed_sources import SourceKey, SourceKind


def test_partial_or_altered_links_are_refused_instead_of_acting_on_defaults() -> None:
    # Defect: a missing field falls back to an empty identity or answer, or an
    # unknown verb or source still reaches a feed item's owner.
    done = encode(ItemAction(Verb.DONE, SourceKey(SourceKind.WINDOWS, "notice")))
    assert parse(done) == ItemAction(Verb.DONE, SourceKey(SourceKind.WINDOWS, "notice"))
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
        "workspace://console-option?message=one&question=-1&answer=Yes",
        "workspace://console-option?message=one&question=x&answer=Yes",
        "workspace://console-option?message=one&answer=Yes",
        "workspace://done?source=unknown&item=notice",
        "workspace://finish?source=windows&item=notice",
        "workspace://done?source=windows&item=",
        "workspace://done?source=windows",
        done + "&source=chat",
        "not a link",
    )
    assert [link for link in refused if parse(link) is not None] == []
