"""Springs for interface motion, in Apple's terms: a damping ratio and a response.

A response is roughly the time a spring takes to reach its target; it isn't a
duration, because a spring settles when its motion falls below what anyone can
see. Values advance in closed form, so a frame of any length lands exactly where
the spring would be, and retargeting keeps the value and velocity on screen.
"""

import math
from dataclasses import dataclass
from typing import Final

REST: Final = 0.005  # Below this distance and speed (per second, in the value's units) a value rests.


@dataclass(frozen=True, slots=True)
class Spring:
    damping: float
    response: float

    def __post_init__(self) -> None:
        if not 0 < self.damping <= 1 or not self.response > 0:
            raise ValueError("A spring needs a damping ratio in (0, 1] and a positive response.")


MORPH: Final = Spring(0.86, 0.42)  # A capsule changing shape.
APPEAR: Final = Spring(0.78, 0.42)  # A capsule arriving, with a little overshoot.
LEAVE: Final = Spring(1.0, 0.3)  # A capsule leaving: critically damped, never past zero.
FADE: Final = Spring(1.0, 0.2)  # Content crossing over at its measured size.


@dataclass(frozen=True, slots=True)
class Motion:
    """A value in flight toward its target."""

    value: float
    target: float
    spring: Spring
    velocity: float = 0.0


def still(value: float, spring: Spring) -> Motion:
    return Motion(value, value, spring)


def toward(motion: Motion, target: float, spring: Spring) -> Motion:
    """A new target, continuing from the current value and velocity."""
    if (motion.target, motion.spring) == (target, spring):
        return motion
    return Motion(motion.value, target, spring, motion.velocity)


def jump(motion: Motion, target: float) -> Motion:
    """Reduced motion: arrive at once."""
    return Motion(target, target, motion.spring)


def resting(motion: Motion) -> bool:
    return motion.value == motion.target and motion.velocity == 0


def settle(motion: Motion, seconds: float) -> Motion:
    """Where the spring is after `seconds`, as a damped harmonic oscillator."""
    if resting(motion) or seconds <= 0:
        return motion
    omega = 2 * math.pi / motion.spring.response
    zeta = motion.spring.damping
    offset, velocity = motion.value - motion.target, motion.velocity
    decay = math.exp(-zeta * omega * seconds)
    if zeta < 1:
        damped = omega * math.sqrt(1 - zeta * zeta)
        cos, sin = math.cos(damped * seconds), math.sin(damped * seconds)
        rate = (velocity + zeta * omega * offset) / damped
        position = decay * (offset * cos + rate * sin)
        speed = decay * (velocity * cos - (zeta * omega * rate + damped * offset) * sin)
    else:
        rate = velocity + omega * offset
        position = decay * (offset + rate * seconds)
        speed = decay * (rate - omega * (offset + rate * seconds))
    if abs(position) < REST and abs(speed) < REST * omega:
        return Motion(motion.target, motion.target, motion.spring)
    return Motion(motion.target + position, motion.target, motion.spring, speed)
