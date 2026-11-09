"""Translate an enum's members, or a Literal alias's values, with a mapping that names every one.

A `match` with `assert_never` lets the type checker prove a translation is exhaustive; a
mapping can't, so `every_member` checks it when the defining module imports.
"""

from collections.abc import Mapping
from enum import Enum
from typing import TypeAliasType, get_args


def every_member[E: Enum, V](members: type[E], values: Mapping[E, V]) -> frozendict[E, V]:
    """`values` as a frozendict, or ValueError naming the members it leaves out."""
    missing = tuple(member.name for member in members if member not in values)
    if missing:
        raise ValueError(f"{members.__name__} has no value for: {', '.join(missing)}")
    return frozendict(values)


def every_literal[K, V](alias: TypeAliasType, values: Mapping[K, V]) -> frozendict[K, V]:
    """`values` as a frozendict keyed by every value of a `Literal` alias, or ValueError naming the values it leaves out."""
    missing = tuple(repr(value) for value in get_args(alias.__value__) if value not in values)
    if missing:
        raise ValueError(f"{alias.__name__} has no value for: {', '.join(missing)}")
    return frozendict(values)
