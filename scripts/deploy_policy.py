"""Choose child restarts from both versions' complete local import closures.

Reuse Workspace's source dependency adapter. Unknown implicit application assets
and changes to the supervisor require a full stop. No code is imported from the
running application to make this decision.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from components import CATALOGUE, Component
from keeper import PROTECTED
from scripts.architecture import dependencies, module_name


class FullRestart(Enum):
    ALL = auto()


@dataclass(frozen=True, slots=True)
class ComponentRestart:
    components: tuple[Component, ...]


type RestartPlan = FullRestart | ComponentRestart


def closure(root: str, imports: Mapping[str, frozenset[str]]) -> frozenset[str]:
    # This source-analysis owner retains a traversal worklist locally; only an
    # immutable module observation leaves it.
    reached = {root, root.split(".", maxsplit=1)[0]}
    pending = list(reached)
    while pending:
        for dependency in imports.get(pending.pop(), frozenset()):
            if dependency not in reached:
                reached.add(dependency)
                pending.append(dependency)
    return frozenset(reached)


def source_imports(root: Path, names: Mapping[str, str]) -> frozendict[str, frozenset[str]]:
    return frozendict(
        (module_name(name), dependencies(name, (root / name).read_text(encoding="utf-8"))) for name in names if name.endswith((".py", ".pyw"))
    )


def restart_plan(before: Path, after: Path, manifests: tuple[Mapping[str, str], Mapping[str, str]]) -> RestartPlan:
    old, new = manifests
    changed = frozenset(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
    implicit = any(
        not name.endswith((".py", ".pyw"))
        and not name.startswith(("docs/", ".github/", "tests/", ".vscode/"))
        and name not in ("AGENTS.md", "README.md", "GLOSSARY.md")
        for name in changed
    )
    if implicit:
        return FullRestart.ALL
    if changed & PROTECTED:
        return FullRestart.ALL
    graphs = source_imports(before, old), source_imports(after, new)
    affected = frozenset(module_name(name) for name in changed if name.endswith((".py", ".pyw")))
    if any(affected & closure("keeper", graph) for graph in graphs):
        return FullRestart.ALL
    selected: tuple[Component, ...] = tuple(
        name for name, entry in CATALOGUE.items() if any(affected & closure(entry.module + ".__main__", graph) for graph in graphs)
    )
    return ComponentRestart(selected)
