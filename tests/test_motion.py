"""Springs: interruptible, exact over any frame length, and still once they arrive."""

from desktop_ui.motion import APPEAR, LEAVE, MORPH, Motion, Spring, resting, settle, still, toward


def frames(motion: Motion, seconds: float, step: float = 1 / 60) -> tuple[Motion, ...]:
    trail: tuple[Motion, ...] = (motion,)
    for _ in range(round(seconds / step)):
        trail = (*trail, settle(trail[-1], step))
    return trail


def test_retargeting_mid_flight_continues_from_the_value_and_velocity_on_screen() -> None:
    # Defect: an interrupted capsule jumps back to its start, or stops dead before reversing.
    flight = frames(toward(still(0, MORPH), 100, MORPH), 0.1)[-1]
    reversed_ = toward(flight, 0, MORPH)
    assert (reversed_.value, reversed_.velocity) == (flight.value, flight.velocity) and flight.velocity > 0
    assert settle(reversed_, 1 / 60).value > flight.value, "Reversal ignored the motion already under way."


def test_a_spring_arrives_exactly_and_then_rests() -> None:
    # Defect: a value hovers a hair from its target, so the frame loop never stops.
    final = frames(toward(still(34, MORPH), 120, MORPH), 2)[-1]
    assert resting(final) and final.value == 120


def test_one_long_frame_lands_where_many_short_frames_would() -> None:
    # Defect: a stalled UI thread integrates one huge step and the capsule overshoots wildly.
    start = toward(still(0, APPEAR), 1, APPEAR)
    stalled, smooth = settle(start, 0.25), frames(start, 0.25, 1 / 240)[-1]
    assert abs(stalled.value - smooth.value) < 1e-9 and abs(stalled.velocity - smooth.velocity) < 1e-6


def test_leaving_never_passes_zero_while_arriving_overshoots_a_little() -> None:
    # Defects: a leaving capsule bounces back into view, or arrival has no life to it.
    assert min(motion.value for motion in frames(toward(still(1, LEAVE), 0, LEAVE), 1)) >= 0
    peak = max(motion.value for motion in frames(toward(still(0, APPEAR), 1, APPEAR), 1))
    assert 1 < peak < 1.1


def test_a_spring_needs_a_damping_ratio_up_to_critical_and_a_response() -> None:
    # Defect: an overdamped or zero-response spring reaches the closed form and divides by zero.
    for damping, response in ((0, 0.4), (1.2, 0.4), (0.8, 0)):
        try:
            Spring(damping, response)
        except ValueError:
            continue
        raise AssertionError(f"Spring({damping}, {response}) was accepted")
