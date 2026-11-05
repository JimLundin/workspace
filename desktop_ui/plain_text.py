"""Agent text as the bar reads it: plain words, with Markdown's marks removed.

The bar is small; full replies stay on the canvas. A canvas link is a control,
not prose, so its label leaves the text and its target is returned instead.
"""

import re
from dataclasses import dataclass
from typing import Final

from assistant.card_actions import parse

_LINK: Final = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
_HEADING: Final = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BULLET: Final = re.compile(r"^[ \t]*[-*+][ \t]+", re.MULTILINE)
_MARKS: Final = re.compile(r"\*\*|__|`")


@dataclass(frozen=True, slots=True)
class Plain:
    text: str
    canvas: str | None  # The first canvas link's target.


def plain(markdown: str) -> Plain:
    targets = tuple(action.target for match in _LINK.finditer(markdown) if (action := parse(match.group(2))) is not None)
    text = _LINK.sub(lambda match: "" if parse(match.group(2)) is not None else match.group(1), markdown)
    text = _MARKS.sub("", _BULLET.sub("• ", _HEADING.sub("", text)))
    text = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", text)).strip()
    return Plain(text, targets[0] if targets else None)
