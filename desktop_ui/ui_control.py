"""The desktop views' decisions: what the assistant published, folded into what each view shows.

`desktop_ui.ui` turns each publication and each request from the desktop's owner
into an `Event` on the Qt thread's queue and folds it through `transition`, which
returns the next `UiState` and the `Effect`s for the views. Views that don't exist
yet ignore an effect; when the bar is built it reports `BarBuilt`, and the fold
replays what it missed.
"""

from collections.abc import Iterator
from dataclasses import dataclass, replace

from contracts.desktop_link import JobChanged, MicLevel, Notify, RecordingChanged, ToDesktop, VoiceChanged
from contracts.status import State


@dataclass(frozen=True, slots=True)
class UiState:
    """What the assistant last published that a view built later needs."""

    overlay_enabled: bool = False


# ---- facts --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Published:
    """The assistant published `message`; the tray's notices and the level belong to the desktop's owner."""

    message: ToDesktop


@dataclass(frozen=True, slots=True)
class OverlayPublished:
    enabled: bool


@dataclass(frozen=True, slots=True)
class BarBuilt:
    """The bar exists now and shows nothing yet."""


type Fact = Published | OverlayPublished | BarBuilt

# ---- effects ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarDictation:
    active: bool


@dataclass(frozen=True, slots=True)
class BarOverlay:
    enabled: bool


@dataclass(frozen=True, slots=True)
class ToView:
    """A publication only the bar shows, delivered as it is if the bar exists."""

    message: JobChanged | RecordingChanged


type Effect = BarDictation | BarOverlay | ToView


def _published(message: ToDesktop) -> Iterator[Effect]:
    match message:
        case VoiceChanged(state=voice):
            yield BarDictation(active=voice is State.LISTENING)
        case JobChanged() | RecordingChanged():
            yield ToView(message)
        case MicLevel() | Notify():
            pass


def transition(state: UiState, fact: Fact) -> tuple[UiState, Iterator[Effect]]:
    """The state after `fact` and the view effects it calls for, in order, produced lazily."""
    match fact:
        case Published(message):
            return state, _published(message)
        case OverlayPublished(enabled):
            return replace(state, overlay_enabled=enabled), iter((BarOverlay(enabled),))
        case BarBuilt():
            return state, iter((BarOverlay(state.overlay_enabled),))
