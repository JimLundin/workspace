import math
from dataclasses import dataclass
from typing import Final

REST: Final = 0.005


@dataclass(frozen=True, slots=True)
class Spring:
    damping: float
    response: float

    def __post_init__(self) -> None:
        if not 0 < self.damping <= 1 or not self.response > 0:
            raise ValueError(
                "A spring needs a damping ratio in (0, 1] and a positive response."
            )


@dataclass(frozen=True, slots=True)
class Motion:
    value: float
    target: float
    spring: Spring
    velocity: float = 0.0


def still(value: float, spring: Spring) -> Motion:
    return Motion(value, value, spring)


def toward(motion: Motion, target: float, spring: Spring) -> Motion:
    if (motion.target, motion.spring) == (target, spring):
        return motion
    return Motion(motion.value, target, spring, motion.velocity)


def jump(motion: Motion, target: float) -> Motion:
    return Motion(target, target, motion.spring)


def resting(motion: Motion) -> bool:
    return motion.value == motion.target and motion.velocity == 0


def settle(motion: Motion, seconds: float) -> Motion:
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
        speed = decay * (
            velocity * cos - (zeta * omega * rate + damped * offset) * sin
        )
    else:
        rate = velocity + omega * offset
        position = decay * (offset + rate * seconds)
        speed = decay * (rate - omega * (offset + rate * seconds))
    if abs(position) < REST and abs(speed) < REST * omega:
        return Motion(motion.target, motion.target, motion.spring)
    return Motion(motion.target + position, motion.target, motion.spring, speed)
