"""What each bar frame draws and whether the frame loop keeps running."""

from dataclasses import replace

from contracts.status import Job
from desktop_ui import ui_spec
from desktop_ui.bar_events import BarModel, menu, next_frame
from desktop_ui.island_model import island
from desktop_ui.spec.island import ISLAND
from tests.test_island_model import RESTING


def model() -> BarModel:
    return BarModel(ui_spec.bar_specs(reload=False))


def working() -> BarModel:
    """A settled bar whose island shows a quick job running."""
    return replace(model(), job=Job.TRANSCRIBING, views=island(replace(RESTING, job=Job.TRANSCRIBING), ISLAND))


def test_a_settled_idle_bar_stops_its_frame_loop() -> None:
    # Defect: the frame timer keeps running once nothing moves.
    drawn = next_frame(model(), 10.0, animate=True)
    assert not drawn.running and not drawn.indicators
    assert (drawn.spin_angle, drawn.wave_progress) == (90.0, 1.0)


def test_running_work_spins_only_while_motion_is_allowed() -> None:
    # Defects: the job's dots paint frozen, keep the frame loop
    # running after work ends, or ignores Windows' reduced-motion setting.
    first, later = next_frame(working(), 10.0, animate=True), next_frame(working(), 10.3, animate=True)
    assert first.running and first.indicators and first.spin_angle != later.spin_angle
    still = next_frame(working(), 10.3, animate=False)
    assert still.spin_angle == 90.0 and not still.running and still.indicators
    assert not next_frame(model(), 10.3, animate=True).running


def test_dictation_moves_the_wave_between_samples_and_rests_behind_an_open_island() -> None:
    # Defect: the waveform jumps sample to sample, keeps animating under an open
    # island, or stops the frame loop mid-dictation.
    dictating = replace(model(), dictating=True, sampled_at=10.0)
    halfway = next_frame(dictating, 10.025, animate=True)
    assert halfway.running and halfway.indicators and abs(halfway.wave_progress - 0.5) < 1e-9
    assert next_frame(dictating, 10.2, animate=True).wave_progress == 1.0
    behind = next_frame(replace(dictating, opened=menu(model())), 10.025, animate=True)
    assert behind.wave_progress == 1.0
