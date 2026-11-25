from desktop_ui.motion import Motion, Spring, resting, settle, still, toward

BOUNCY = Spring(0.6, 0.3)
CRITICAL = Spring(1.0, 0.3)


def frames(
    motion: Motion, seconds: float, step: float = 1 / 60
) -> tuple[Motion, ...]:
    trail: tuple[Motion, ...] = (motion,)
    for _ in range(round(seconds / step)):
        trail = (*trail, settle(trail[-1], step))
    return trail


def test_retargeting_mid_flight_continues_from_the_value_and_velocity_on_screen() -> (
    None
):
    flight = frames(toward(still(0, BOUNCY), 100, BOUNCY), 0.1)[-1]
    reversed_ = toward(flight, 0, BOUNCY)
    assert (reversed_.value, reversed_.velocity) == (
        flight.value,
        flight.velocity,
    ) and flight.velocity > 0
    assert settle(reversed_, 1 / 60).value > flight.value, (
        "Reversal ignored the motion already under way."
    )


def test_a_spring_arrives_exactly_and_then_rests() -> None:
    final = frames(toward(still(34, BOUNCY), 120, BOUNCY), 2)[-1]
    assert resting(final) and final.value == 120


def test_one_long_frame_lands_where_many_short_frames_would() -> None:
    start = toward(still(0, BOUNCY), 1, BOUNCY)
    stalled, smooth = settle(start, 0.25), frames(start, 0.25, 1 / 240)[-1]
    assert (
        abs(stalled.value - smooth.value) < 1e-9
        and abs(stalled.velocity - smooth.velocity) < 1e-6
    )


def test_a_critically_damped_spring_never_passes_its_target_while_an_underdamped_one_overshoots() -> (
    None
):
    assert (
        min(
            motion.value
            for motion in frames(toward(still(1, CRITICAL), 0, CRITICAL), 1)
        )
        >= 0
    )
    assert (
        max(
            motion.value
            for motion in frames(toward(still(0, BOUNCY), 1, BOUNCY), 1)
        )
        > 1
    )


def test_a_spring_needs_a_damping_ratio_up_to_critical_and_a_response() -> None:
    for damping, response in ((0, 0.4), (1.2, 0.4), (0.8, 0)):
        try:
            Spring(damping, response)
        except ValueError:
            continue
        raise AssertionError(f"Spring({damping}, {response}) was accepted")
