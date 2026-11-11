"""What each bar frame draws and whether the frame loop keeps running."""

from dataclasses import replace

from contracts.status import TRANSCRIBING
from desktop_ui.bar_events import BarModel, menu, next_frame
from desktop_ui.island_menu import Panel
from desktop_ui.island_model import island
from tests import test_bar_specs
from tests.test_island_model import RESTING, SPEC


def model() -> BarModel:
    return BarModel(test_bar_specs.SPEC)


def working() -> BarModel:
    """A settled bar whose island shows a quick job running."""
    return replace(model(), job=TRANSCRIBING, views=island(replace(RESTING, job=TRANSCRIBING), SPEC))


def test_a_settled_idle_bar_stops_its_frame_loop() -> None:
    # Defect: the frame timer keeps running once nothing moves.
    drawn = next_frame(model(), 10.0, animate=True)
    assert not drawn.running and not drawn.indicators and drawn.wave_progress == 1.0
    assert drawn.pulse == next_frame(model(), 10.3, animate=True).pulse


def test_running_work_spins_only_while_motion_is_allowed() -> None:
    # Defects: the job's dots paint frozen, keep the frame loop
    # running after work ends, or ignores Windows' reduced-motion setting.
    first, later = next_frame(working(), 10.0, animate=True), next_frame(working(), 10.3, animate=True)
    assert first.running and first.indicators and first.pulse != later.pulse
    still = next_frame(working(), 10.3, animate=False)
    assert still.pulse == next_frame(working(), 10.0, animate=False).pulse and not still.running and still.indicators
    assert not next_frame(model(), 10.3, animate=True).running


def test_dictation_moves_the_wave_between_samples_and_rests_behind_an_open_island() -> None:
    # Defect: the waveform jumps sample to sample, keeps animating under an open
    # island, or stops the frame loop mid-dictation.
    dictating = replace(model(), dictating=True, sampled_at=10.0)
    soon, later = next_frame(dictating, 10.001, animate=True), next_frame(dictating, 10.002, animate=True)
    assert soon.running and soon.indicators and 0 < soon.wave_progress < later.wave_progress < 1
    assert next_frame(dictating, 20.0, animate=True).wave_progress == 1.0
    behind = next_frame(replace(dictating, opened=menu(model(), Panel.WORKSPACE)), 10.001, animate=True)
    assert behind.wave_progress == 1.0
