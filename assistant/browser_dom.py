"""Page scripts, each in its `.js` file beside the module that runs it, and the DOM operations run in a separate JavaScript world."""

from pathlib import Path
from typing import Final


def script(name: str) -> str:
    """The page script `assistant/<name>.js`, such as `web_apps.kanban`."""
    return Path(__file__).with_name(name + ".js").read_text(encoding="utf-8")


SNAPSHOT: Final = script("browser_dom.snapshot")

ACTION: Final = script("browser_dom.action")
