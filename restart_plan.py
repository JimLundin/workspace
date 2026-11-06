"""Which programs an installed change restarts, from both versions' import closures.

The keeper decides this before replacing any file, for agent installs, deploys
and undos alike. A child restarts when a module it imports changed, directly or
through package initialization; the keeper itself relaunches when its own
closure changed. Protected and standard-library only, like the keeper.
"""

import ast
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from components import CATALOGUE, Component


class Relaunch(Enum):
    """Stop everything and start the keeper again from the new version."""

    KEEPER = auto()


@dataclass(frozen=True, slots=True)
class RestartChildren:
    """Restart only these children, in catalogue order; the keeper keeps running."""

    components: tuple[Component, ...]


type RestartPlan = RestartChildren | Relaunch

DOCUMENTATION = ("docs/", ".github/", "tests/", ".vscode/")
NOTES = frozenset({"AGENTS.md", "README.md", "GLOSSARY.md"})


@dataclass(frozen=True, slots=True)
class Tree:
    """One version's source files, as relative POSIX names below `root`."""

    root: Path
    files: frozenset[str]


def module_name(name: str) -> str:
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


def import_aliases(tree: ast.AST) -> dict[str, str]:
    """Local names bound by imports, mapped to the module or attribute they name."""
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=names):
                result.update({alias.asname or alias.name.split(".")[0]: alias.name if alias.asname else alias.name.split(".")[0] for alias in names})
            case ast.ImportFrom(module=module, level=0, names=names) if module:
                result.update({alias.asname or alias.name: module + "." + alias.name for alias in names})
            case _:
                pass
    return result


def imports(name: str, tree: ast.AST) -> frozenset[str]:
    """Every module `name` can load, including lazy imports and ancestor packages."""
    result: set[str] = set()
    aliases = import_aliases(tree)
    package = module_name(name).split(".") if name.endswith("/__init__.py") else module_name(name).split(".")[:-1]
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=names):
                result.update(alias.name for alias in names)
            case ast.ImportFrom(module=base, level=level, names=names):
                prefix = ".".join(package[: len(package) - level + 1]) if level else ""
                target = ".".join(value for value in (prefix, base) if value)
                result.add(target)
                result.update(".".join(value for value in (target, alias.name) if value) for alias in names if alias.name != "*")
            case ast.Call(func=function, args=[ast.Constant(value=str(value)), *_]) if call_name(function, aliases) in (
                "importlib.import_module",
                "__import__",
                "builtins.__import__",
            ):
                result.add(value)
            case _:
                pass
    # Importing a submodule executes its ancestor package initializers too.
    return frozenset(".".join(value.split(".")[:index]) for value in result for index in range(1, len(value.split(".")) + 1))


def closure(root: str, graph: Callable[[str], frozenset[str]]) -> frozenset[str]:
    reached = {root, root.split(".", maxsplit=1)[0]}
    pending = list(reached)
    while pending:
        for dependency in graph(pending.pop()):
            if dependency not in reached:
                reached.add(dependency)
                pending.append(dependency)
    return frozenset(reached)


def _graph(tree: Tree) -> Callable[[str], frozenset[str]]:
    """A module's imports, parsed on first use: only modules a supervised program reaches."""
    modules = {module_name(name): name for name in tree.files if name.endswith((".py", ".pyw"))}
    parsed: dict[str, frozenset[str]] = {}

    def graph(module: str) -> frozenset[str]:
        name = modules.get(module)
        if name is None:
            return frozenset()
        if module not in parsed:
            parsed[module] = imports(name, ast.parse((tree.root / name).read_bytes(), name))
        return parsed[module]

    return graph


def _digest(tree: Tree, name: str) -> str | None:
    return hashlib.sha256((tree.root / name).read_bytes()).hexdigest() if name in tree.files else None


def changed(before: Tree, after: Tree) -> frozenset[str]:
    return frozenset(name for name in before.files | after.files if _digest(before, name) != _digest(after, name))


def _packages(tree: Tree) -> frozenset[str]:
    """Top-level folders that are Python packages: their data files belong to their importers."""
    return frozenset(name.split("/")[0] for name in tree.files if name.count("/") == 1 and name.endswith("/__init__.py"))


def restart_plan(before: Tree, after: Tree, protected: frozenset[str]) -> RestartPlan:
    """Relaunch for protected files or the keeper's closure.

    Data files a child reloads itself (`Entry.live_assets`) restart nothing. A data
    file inside a package restarts the children that import that package; any other
    (the lock, `pyproject.toml`) restarts every child.
    """
    names = changed(before, after)
    if names & protected:
        return Relaunch.KEEPER
    graphs = (_graph(before), _graph(after))
    affected = {module_name(name) for name in names if name.endswith((".py", ".pyw"))}
    if any(affected & closure("keeper", graph) for graph in graphs):
        return Relaunch.KEEPER
    live = tuple(prefix for entry in CATALOGUE.values() for prefix in entry.live_assets)
    assets = tuple(
        name
        for name in names
        if not name.endswith((".py", ".pyw")) and not name.startswith(DOCUMENTATION) and name not in NOTES and not name.startswith(live)
    )
    packages = _packages(before) | _packages(after)
    if any(name.split("/")[0] not in packages for name in assets):
        return RestartChildren(tuple(CATALOGUE))
    affected.update(name.split("/")[0] for name in assets)
    return RestartChildren(
        tuple(name for name, entry in CATALOGUE.items() if any(affected & closure(entry.module + ".__main__", graph) for graph in graphs))
    )
