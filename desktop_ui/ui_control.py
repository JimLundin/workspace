"""The desktop views' decisions: what a view built later must replay.

`desktop_ui.ui` turns each request from the desktop's owner into an `Event` on
the Qt thread's queue and folds it through `transition`, which returns the next
`UiState` and the `Effect`s for the views. Views that don't exist yet ignore an
effect; when the bar is built it reports `BarBuilt`, and the fold replays what
it missed.
"""

from collections.abc import Iterator
from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class UiState:
    """What a view built later needs."""

    overlay_enabled: bool = False


# ---- facts --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OverlayPublished:
    enabled: bool


@dataclass(frozen=True, slots=True)
class BarBuilt:
    """The bar exists now and shows nothing yet."""


type Fact = OverlayPublished | BarBuilt

# ---- effects ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarOverlay:
    enabled: bool


type Effect = BarOverlay


def transition(state: UiState, fact: Fact) -> tuple[UiState, Iterator[Effect]]:
    """The state after `fact` and the view effects it calls for, in order, produced lazily."""
    match fact:
        case OverlayPublished(enabled):
            return replace(state, overlay_enabled=enabled), iter((BarOverlay(enabled),))
        case BarBuilt():
            return state, iter((BarOverlay(state.overlay_enabled),))
