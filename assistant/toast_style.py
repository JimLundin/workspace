"""Quiet blue and lilac glass, with opaque ink and a dark solid fallback."""

from dataclasses import dataclass
from typing import Final, assert_never

from assistant.feed_origin import App
from assistant.notifications import Tone

INK: Final = "#f6f3ff"
SECONDARY: Final = "#e0dced"
USER: Final = "#c7dcff"
SURFACE: Final = "#262337"
EDGE: Final = "#716a87"


@dataclass(frozen=True, slots=True)
class Ink:
    foreground: str = INK
    secondary: str = SECONDARY
    link: str = USER
    error: str = "#ffb7b2"


@dataclass(frozen=True, slots=True)
class Palette:
    surface: str
    edge: str
    accent: str
    tint: str


def palette(tone: Tone, app: App | None = None) -> Palette:
    match app:
        case App.TEAMS:
            return Palette("#292540", "#8076b2", "#d8d1ff", "#6655a0")
        case App.OUTLOOK:
            return Palette("#1d2c40", "#587fa7", "#c2e4ff", "#2869a2")
        case App.CODEX:
            return Palette("#222e31", "#68878b", "#d0eaeb", "#416f74")
        case App.CLAUDE:
            return Palette("#372922", "#a47c69", "#f4d2be", "#9c6049")
        case App.EDGE:
            return Palette("#203332", "#5e9690", "#c4f1e9", "#267e76")
        case App.WINDOWS:
            return Palette("#252c3a", "#6e83a5", "#d4e3ff", "#486a9c")
        case App.WORKSPACE | None:
            pass
        case _:
            assert_never(app)
    match tone:
        case Tone.USER | Tone.RECORDING:
            return Palette("#222c42", "#62738e", "#d3e3ff", "#335ba5")
        case Tone.THINKING | Tone.ACTION | Tone.REPLY:
            return Palette(SURFACE, EDGE, "#e8e1ff", "#4e4173")
        case Tone.QUESTION:
            return Palette(SURFACE, EDGE, "#f2ddb9", "#4e4173")
        case Tone.ERROR:
            return Palette(SURFACE, EDGE, "#ffb7b2", "#4e4173")
        case _:
            assert_never(tone)
