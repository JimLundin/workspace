"""The finding every architecture rule reports, and the syntax helpers the rules share."""

import ast
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


def qualified(declaration: str, name: str) -> str:
    """A name inside a declaration, dotted after it; at a module's top level, the name alone."""
    return ".".join(part for part in (declaration, name) if part)


def targets(node: ast.AST) -> tuple[ast.expr, ...]:
    match node:
        case ast.Assign(targets=targets) | ast.Delete(targets=targets):
            return tuple(targets)
        case ast.AugAssign(target=target) | ast.AnnAssign(target=target):
            return (target,)
        case _:
            return ()


def parameters(arguments: ast.arguments) -> tuple[ast.arg, ...]:
    """Every parameter a signature declares, positional ones first, then the starred ones."""
    return (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *(item for item in (arguments.vararg, arguments.kwarg) if item))
