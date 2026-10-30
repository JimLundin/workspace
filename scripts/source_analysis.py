"""Content-bound observations shared by the source inspection adapters.

ASTs belong to these adapters and are never mutated after parsing or given to
application code. Bounded parser retention avoids three copies of the same work.
Only validated immutable observations are persisted; full selfcheck does not use
the disk cache. Cache loss/corruption falls back to ordinary analysis.
"""

import ast
import contextlib
import hashlib
import importlib.metadata
import os
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from scripts.development_paths import PROFILE


@dataclass(frozen=True, slots=True)
class Source:
    name: str
    text: str


@lru_cache(maxsize=512)
def parse(source: Source) -> ast.Module:
    return ast.parse(source.text, filename=source.name)


class Cache:
    """Optional storage of immutable observations, bound to the analysis engine."""

    __slots__ = ("folder",)

    def __init__(self, root: Path, *, folder: Path = PROFILE / "development" / "analysis") -> None:
        engine = Path(__file__).resolve().parent
        digest = hashlib.sha256(sys.version.encode())
        digest.update(importlib.metadata.version("pydantic").encode())
        digest.update(str(root.resolve()).encode())
        for name in ("source_analysis.py", "architecture.py", "quality.py", "check.py"):
            digest.update((engine / name).read_bytes())
        digest.update((root / "pyproject.toml").read_bytes())
        self.folder = folder / digest.hexdigest()

    def key(self, namespace: str, source: Source, *, extra: bytes = b"") -> str:
        digest = hashlib.sha256(namespace.encode() + b"\0" + source.name.encode() + b"\0" + source.text.encode())
        digest.update(extra)
        return digest.hexdigest()

    def read[T](self, key: str, adapter: TypeAdapter[T]) -> T | None:
        try:
            return adapter.validate_json((self.folder / (key + ".json")).read_bytes(), strict=True)
        except OSError, ValidationError:
            return None

    def write[T](self, key: str, value: T, adapter: TypeAdapter[T]) -> None:
        # Each writer owns a unique temporary file. Concurrent editing commands
        # may publish the same immutable observation without sharing partial JSON.
        temporary: Path | None = None
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.folder, delete=False) as output:
                temporary = Path(output.name)
                output.write(adapter.dump_json(value))
            os.replace(temporary, self.folder / (key + ".json"))
        except OSError:
            pass
        finally:
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink(missing_ok=True)
