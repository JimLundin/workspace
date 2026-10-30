"""Atomic encrypted IO over the caller's typed storage contract."""

from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter

lazy from winapi import protection


class StateProtection(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


class SavedState[T]:
    __slots__ = ("adapter", "cipher", "path")

    def __init__(self, path: Path, adapter: TypeAdapter[T], *, cipher: StateProtection) -> None:
        self.path, self.adapter, self.cipher = path, adapter, cipher

    def read(self) -> T:
        if not self.path.exists():
            empty: dict[str, object] = {}
            return self.adapter.validate_python(empty)
        return self.adapter.validate_json(self.cipher.unprotect(self.path.read_bytes()))

    def write(self, state: T) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        candidate = self.path.with_suffix(".tmp")
        try:
            candidate.write_bytes(self.cipher.protect(self.adapter.dump_json(state)))
            candidate.replace(self.path)
        finally:
            candidate.unlink(missing_ok=True)


def windows_store[T](path: Path, adapter: TypeAdapter[T]) -> SavedState[T]:
    return SavedState(path, adapter, cipher=protection)
