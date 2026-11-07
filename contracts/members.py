"""Translate an enum's members to values with a mapping that names every member.

A `match` with `assert_never` lets Pyright prove a translation is exhaustive; a
mapping can't, so `every_member` checks it when the defining module imports.
"""

from collections.abc import Mapping
from enum import Enum


def every_member[E: Enum, V](members: type[E], values: Mapping[E, V]) -> frozendict[E, V]:
    """`values` as a frozendict, or ValueError naming the members it leaves out."""
    missing = tuple(member.name for member in members if member not in values)
    if missing:
        raise ValueError(f"{members.__name__} has no value for: {', '.join(missing)}")
    return frozendict(values)
