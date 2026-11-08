"""The desktop views' decisions, as values: what a late-built bar replays."""

from desktop_ui.ui_control import BarBuilt, BarOverlay, OverlayPublished, UiState, transition


def test_a_bar_built_late_replays_the_overlay_it_missed() -> None:
    # Defect: the bar built after the overlay's publication shows the old overlay state.
    state, _ = transition(UiState(), OverlayPublished(enabled=True))
    _, replayed = transition(state, BarBuilt())
    assert tuple(replayed) == (BarOverlay(enabled=True),)
