"""Validated observations for the toolbar's quiet resting presentation."""

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Literal, assert_never


class PowerUnavailable(Enum):
    UNKNOWN = auto()
    NO_BATTERY = auto()


class Speakers(Enum):
    UNKNOWN = auto()
    AUDIBLE = auto()
    MUTED = auto()


class Wifi(Enum):
    UNKNOWN = auto()
    CONNECTED = auto()
    DISCONNECTED = auto()
    NO_ADAPTER = auto()


@dataclass(frozen=True, slots=True)
class SystemStatus:
    speakers: Speakers = Speakers.UNKNOWN
    wifi: Wifi = Wifi.UNKNOWN

    @property
    def alerts(self) -> tuple[str, ...]:
        return (*(("speaker-on",) if self.speakers is Speakers.AUDIBLE else ()), *(("wifi-off",) if self.wifi is Wifi.DISCONNECTED else ()))

    @property
    def description(self) -> str:
        observations = (
            "Speakers unmuted" if self.speakers is Speakers.AUDIBLE else "",
            "Wi-Fi disconnected" if self.wifi is Wifi.DISCONNECTED else "",
        )
        return ". ".join(value for value in observations if value)


@dataclass(frozen=True, slots=True)
class Battery:
    percent: int
    powered: bool = field(kw_only=True)
    charging: bool = field(kw_only=True)

    def __post_init__(self) -> None:
        if not 0 <= self.percent <= 100:
            raise ValueError("Battery percentage must be between 0 and 100.")


type Power = Battery | PowerUnavailable
type WeatherIcon = Literal["sun", "moon", "cloud", "rain", "snow", "storm"]


@dataclass(frozen=True, slots=True)
class Weather:
    celsius: float
    code: int
    daytime: bool = field(kw_only=True)

    def __post_init__(self) -> None:
        if not math.isfinite(self.celsius) or not -100 <= self.celsius <= 70 or not 0 <= self.code <= 99:
            raise ValueError("Invalid weather observation.")

    @property
    def icon(self) -> WeatherIcon:
        if self.code == 0:
            return "sun" if self.daytime else "moon"
        if self.code >= 95:
            return "storm"
        if self.code in (71, 73, 75, 77, 85, 86):
            return "snow"
        if self.code >= 51:
            return "rain"
        return "cloud"

    @property
    def text(self) -> str:
        return f"{round(self.celsius)}°"


@dataclass(frozen=True, slots=True)
class Ambient:
    clock: str
    power: Power
    weather: Weather | None = None

    @property
    def battery_text(self) -> str:
        match self.power:
            case Battery(percent=percent, powered=True) if percent > 95:
                return ""
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
        facts = (self.clock, self.battery_text, self.weather.text if self.weather is not None else "")
        return "  ·  ".join(value for value in facts if value)
