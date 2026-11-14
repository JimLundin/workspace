"""The finding every architecture rule reports, and the module containment its policies are written in."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Annotated

from pydantic import StrictStr, StringConstraints

type Text = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
"""A configured name: present, and trimmed."""


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    module: str
    declaration: str
    expression: str
    line: int
    detail: str

    def describe(self) -> str:
        location = self.module + ("." + self.declaration if self.declaration else "")
        return f"{self.rule}: {location}:{self.line}: {self.detail}"


def within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def within_any(module: str, packages: Iterable[str]) -> bool:
    return any(within(module, package) for package in packages)
