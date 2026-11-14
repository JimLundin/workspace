"""Content-bound observations shared by the source inspection adapters, and the syntax helpers they read sources with.

ASTs belong to these adapters and are never mutated after parsing or given to
application code. Bounded parser retention avoids three copies of the same work.
Only validated immutable observations are persisted. Cache loss or corruption
falls back to ordinary analysis.
"""

import ast
import contextlib
import hashlib
import importlib.metadata
import os
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import TypeAdapter, ValidationError


@dataclass(frozen=True, slots=True)
class Source:
    name: str
    text: str


@lru_cache(maxsize=512)
def parse(source: Source) -> ast.Module:
    return ast.parse(source.text, filename=source.name)


ANALYSIS = Path(tempfile.gettempdir()) / "workspace-analysis"


@dataclass(frozen=True, slots=True)
class Cache:
    """Optional storage of immutable observations, bound to the analysis engine."""

    folder: Path

    @classmethod
    def bound(cls, root: Path, *, folder: Path = ANALYSIS) -> Cache:
        """The cache for root's sources under this interpreter, pydantic and analysis engine.

        Every script beside this one counts as the engine, so a new rule module
        invalidates the cache without being listed; hashing a script that is not
        part of the engine only costs a recomputation."""
        engine = Path(__file__).resolve().parent
        digest = hashlib.sha256(sys.version.encode())
        digest.update(importlib.metadata.version("pydantic").encode())
        digest.update(str(root.resolve()).encode())
        for script in sorted(engine.glob("*.py")):
            digest.update(script.name.encode() + b"\0" + script.read_bytes())
        digest.update((root / "pyproject.toml").read_bytes())
        return cls(folder / digest.hexdigest())

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


def memoized[T](cache: Cache | None, namespace: str, source: Source, adapter: TypeAdapter[T], compute: Callable[[Source], T]) -> T:
    """The observation compute makes of source, read from the cache when saved there and saved once computed."""
    if cache is None:
        return compute(source)
    key = cache.key(namespace, source)
    if (saved := cache.read(key, adapter)) is not None:
        return saved
    result = compute(source)
    cache.write(key, result, adapter)
    return result


DYNAMIC_IMPORTS = frozenset({"importlib.import_module", "__import__", "builtins.__import__"})
"""Calls that import a module named at run time."""


def module_name(name: str) -> str:
    """The dotted module a source file name defines; a package's `__init__` names the package."""
    parts = Path(name).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def call_name(node: ast.AST, aliases: Mapping[str, str]) -> str:
    """The dotted name a call's function resolves to through import aliases."""
    match node:
        case ast.Name(id=name):
            return aliases.get(name, name)
        case ast.Attribute(value=value, attr=attribute):
            return call_name(value, aliases) + "." + attribute
        case _:
            return ""


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


def _bound_names(node: ast.AST) -> Iterator[tuple[str, str]]:
    match node:
        case ast.Import(names=names):
            yield from ((alias.asname or alias.name.split(".")[0], alias.name if alias.asname else alias.name.split(".")[0]) for alias in names)
        case ast.ImportFrom(module=str() as module, level=0, names=names):
            yield from ((alias.asname or alias.name, module + "." + alias.name) for alias in names)
        case _:
            pass


def import_aliases(tree: ast.AST) -> frozendict[str, str]:
    """Local names bound by imports, mapped to the module or attribute they name."""
    return frozendict(pair for node in ast.walk(tree) for pair in _bound_names(node))


def _imported(node: ast.AST, package: Sequence[str], aliases: Mapping[str, str]) -> Iterator[str]:
    match node:
        case ast.Import(names=names):
            yield from (alias.name for alias in names)
        case ast.ImportFrom(module=base, level=level, names=names):
            prefix = ".".join(package[: len(package) - level + 1]) if level else ""
            target = ".".join(value for value in (prefix, base) if value)
            yield target
            yield from (".".join(value for value in (target, alias.name) if value) for alias in names if alias.name != "*")
        case ast.Call(func=function, args=[ast.Constant(value=str(value)), *_]) if call_name(function, aliases) in DYNAMIC_IMPORTS:
            yield value
        case _:
            pass


def imports(name: str, tree: ast.AST) -> frozenset[str]:
    """Every module `name` can load, including lazy imports and ancestor packages."""
    aliases = import_aliases(tree)
    module = module_name(name).split(".")
    package = module if name.endswith("/__init__.py") else module[:-1]
    found = (target for node in ast.walk(tree) for target in _imported(node, package, aliases))
    # Importing a submodule executes its ancestor package initializers too.
    return frozenset(".".join(parts[:index]) for target in found for parts in (target.split("."),) for index in range(1, len(parts) + 1))
