"""Choose child restarts from both versions' complete local import closures.

Reuse Workspace's source dependency adapter. Unknown implicit application assets
and changes to the supervisor require a full stop. No code is imported from the
running application to make this decision.
"""

from collections.abc import Callable
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


@dataclass(frozen=True, slots=True)
class Version:
    """One source version: `changed` names are read below `overlay`, every other name below `base`.

    A release extracts only the files it replaces, so the new version overlays
    those on the installed tree, which still holds every unchanged file.
    """

    manifest: frozendict[str, str]
    base: Path
    overlay: Path
    changed: frozenset[str]

    def path(self, name: str) -> Path:
        return (self.overlay if name in self.changed else self.base) / name


def closure(root: str, imports: Callable[[str], frozenset[str]]) -> frozenset[str]:
    # This source-analysis owner retains a traversal worklist locally; only an
    # immutable module observation leaves it.
    reached = {root, root.split(".", maxsplit=1)[0]}
    pending = list(reached)
    while pending:
        for dependency in imports(pending.pop()):
            if dependency not in reached:
                reached.add(dependency)
                pending.append(dependency)
    return frozenset(reached)


def source_imports(version: Version, parsed: dict[tuple[str, str], frozenset[str]]) -> Callable[[str], frozenset[str]]:
    """A module's imports, parsed on first use: only modules a supervised process reaches.

    `parsed` is restart_plan's local memo keyed by file name and content hash, so a
    file unchanged between versions is parsed once. Parsing every file of both
    trees took 6-8 s per tree on Windows, inside the deployment outage path.
    """
    files = frozendict((module_name(name), name) for name in version.manifest if name.endswith((".py", ".pyw")))

    def imports(module: str) -> frozenset[str]:
        name = files.get(module)
        if name is None:
            return frozenset()
        key = (name, version.manifest[name])
        if key not in parsed:
            parsed[key] = dependencies(name, version.path(name).read_text(encoding="utf-8"))
        return parsed[key]

    return imports


def restart_plan(versions: tuple[Version, Version]) -> RestartPlan:
    old, new = (version.manifest for version in versions)
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
    parsed: dict[tuple[str, str], frozenset[str]] = {}
    graphs = tuple(source_imports(version, parsed) for version in versions)
    affected = frozenset(module_name(name) for name in changed if name.endswith((".py", ".pyw")))
    if any(affected & closure("keeper", graph) for graph in graphs):
        return FullRestart.ALL
    selected: tuple[Component, ...] = tuple(
        name for name, entry in CATALOGUE.items() if any(affected & closure(entry.module + ".__main__", graph) for graph in graphs)
    )
    return ComponentRestart(selected)
