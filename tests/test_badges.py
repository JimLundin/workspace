"""App identity remains distinct in both card and canvas badges."""

from typing import assert_never

from contracts.feed_origin import App
from desktop_ui.components.bubble import BADGES, Letter, Symbol


def test_brand_badges_have_distinct_letters() -> None:
    # Defect: using an app's initial makes Codex and Claude Code share a badge.
    letters: tuple[str, ...] = ()
    for app in App:
        value = BADGES[app].glyph
        match value:
            case Letter(text=letter):
                letters = (*letters, letter)
            case Symbol():
                pass
            case _:
                assert_never(value)
    assert len(letters) == len(frozenset(letters))
