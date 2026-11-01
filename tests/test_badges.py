"""App identity remains distinct in both card and canvas badges."""

from typing import assert_never

from assistant.feed_origin import App
from assistant.ui_components.bubble import Letter, Symbol, glyph


def test_brand_badges_have_distinct_letters() -> None:
    # Defect: using an app's initial makes Codex and Claude Code share a badge.
    letters: tuple[str, ...] = ()
    for app in App:
        value = glyph(app)
        match value:
            case Letter(text=letter):
                letters = (*letters, letter)
            case Symbol():
                pass
            case _:
                assert_never(value)
    assert len(letters) == len(frozenset(letters))
