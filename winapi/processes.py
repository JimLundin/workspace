"""How Workspace starts a program that outlives it."""

from typing import Final

DETACHED: Final = 0x0000_0008 | 0x0800_0000
"""DETACHED_PROCESS | CREATE_NO_WINDOW: a child that outlives its parent, without a console."""
