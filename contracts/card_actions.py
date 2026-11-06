"""Card actions: what a bubble's link does, with one `workspace://` encoding.

Bubbles direct the person to the canvas; app arrivals never become cards. A
link that is not exactly this encoding parses to None and does nothing.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

_SCHEME = "workspace"


@dataclass(frozen=True, slots=True)
class OpenCanvas:
    target: str


def encode(action: OpenCanvas) -> str:
    return _link("canvas", {"target": action.target})


def _link(action: str, values: Mapping[str, str]) -> str:
    return _SCHEME + "://" + action + "?" + urlencode(values)


def parse(link: str) -> OpenCanvas | None:
    try:
        url = urlsplit(link)
    except ValueError:
        return None
    fields = parse_qs(url.query)
    if url.scheme != _SCHEME or url.path or url.fragment or any(len(values) != 1 for values in fields.values()):
        return None
    values = {name: value for name, (value,) in fields.items()}
    match url.netloc, values:
        case "canvas", {"target": str(target)} if len(values) == 1 and target:
            return OpenCanvas(target)
        case _:
            return None
