"""Plain observations of the machine's speakers, Wi-Fi and power. No ctypes: importable anywhere."""

from dataclasses import dataclass, field
from enum import Enum, auto


class Speakers(Enum):
    UNKNOWN = auto()
    AUDIBLE = auto()
    MUTED = auto()


class Wifi(Enum):
    UNKNOWN = auto()
    CONNECTED = auto()
    DISCONNECTED = auto()
    NO_ADAPTER = auto()


class PowerUnavailable(Enum):
    UNKNOWN = auto()
    NO_BATTERY = auto()


@dataclass(frozen=True, slots=True)
class Battery:
    percent: int
    powered: bool = field(kw_only=True)
    charging: bool = field(kw_only=True)

    def __post_init__(self) -> None:
        if not 0 <= self.percent <= 100:
            raise ValueError("Battery percentage must be between 0 and 100.")


type Power = Battery | PowerUnavailable
