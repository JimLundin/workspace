"""Validated observations for the toolbar's quiet resting presentation."""

from dataclasses import dataclass
from typing import assert_never

from winapi.machine_status import Battery, Power, PowerUnavailable


@dataclass(frozen=True, slots=True)
class Ambient:
    clock: str
    power: Power

    @property
    def battery_text(self) -> str:
        match self.power:
            case Battery(percent=percent):
                return f"{percent}%"
            case PowerUnavailable.NO_BATTERY:
                return "AC"
            case PowerUnavailable.UNKNOWN:
                return "—"
            case _:
                assert_never(self.power)

    @property
    def text(self) -> str:
        facts = (self.clock, self.battery_text)
        return "  ·  ".join(value for value in facts if value)
