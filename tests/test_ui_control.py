"""The desktop views' decisions, as values: what a late-built bar replays and what each publication shows."""

from contracts.desktop_link import JobChanged, VoiceChanged
from contracts.status import State
from desktop_ui.ui_control import BarBuilt, BarDictation, BarOverlay, OverlayPublished, Published, ToView, UiState, transition


def test_a_bar_built_late_replays_the_overlay_it_missed() -> None:
    # Defect: the bar built after the overlay's publication shows the old overlay state.
    state, _ = transition(UiState(), OverlayPublished(enabled=True))
    _, replayed = transition(state, BarBuilt())
    assert tuple(replayed) == (BarOverlay(enabled=True),)


def test_voice_state_shows_dictation_on_the_bar_only_while_listening() -> None:
    # Defect: transcription keeps the bar's dictation lit, or listening doesn't light it.
    _, listening = transition(UiState(), Published(VoiceChanged(State.LISTENING)))
    assert tuple(listening) == (BarDictation(active=True),)
    _, working = transition(UiState(), Published(VoiceChanged(State.WORKING)))
    assert tuple(working) == (BarDictation(active=False),)


def test_a_publication_for_one_view_reaches_it_unchanged() -> None:
    # Defect: a job change is lost on its way to the bar.
    _, effects = transition(UiState(), Published(JobChanged(None)))
    assert tuple(effects) == (ToView(JobChanged(None)),)
