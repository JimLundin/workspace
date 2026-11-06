"""A colour as the desktop draws it: three 8-bit channels, checked as the value is built."""

import re
from dataclasses import dataclass
from typing import Final

_HEX: Final = re.compile(r"#([0-9a-fA-F]{6})")


@dataclass(frozen=True, slots=True)
class Rgb:
    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        for name, value in (("red", self.red), ("green", self.green), ("blue", self.blue)):
            if isinstance(value, bool) or not 0 <= value <= 255:
                raise ValueError(f"A colour's {name} channel is a whole number from 0 to 255, not {value!r}.")

    @classmethod
    def parse(cls, text: str) -> Rgb:
        """`#rrggbb`, as stylesheets and design tokens write it."""
        match = _HEX.fullmatch(text)
        if match is None:
            raise ValueError(f"A colour is written #rrggbb, not {text!r}.")
        digits = match.group(1)
        return cls(int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))

    @property
    def hex(self) -> str:
        return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"
