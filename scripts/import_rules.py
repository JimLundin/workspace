"""Import-graph rules: layer order and APIs, data imports, contract isolation and the keyboard's reach."""

import ast
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import TypeAdapter

from scripts.policy import Finding, Text, within, within_any
from scripts.source_analysis import DYNAMIC_IMPORTS, Cache, Source, call_name, import_aliases, imports, module_name, parse

DEPENDENCIES = TypeAdapter[frozenset[str]](frozenset[str])


@dataclass(frozen=True, slots=True)
class Layer:
    """One big module: its packages and, if it keeps insides, the modules others may import from it."""

    name: Text
    packages: tuple[Text, ...]
    api: tuple[Text, ...] = ()
    """The modules (or packages) others may import; empty: all of it."""


@dataclass(frozen=True, slots=True)
class Placed:
    """The layer a module belongs to, with the layer's place bottom first."""

    place: int
    layer: Layer


def dependencies(name: str, text: str, *, cache: Cache | None = None) -> frozenset[str]:
    source = Source(name, text)
    key = cache.key("dependencies", source) if cache is not None else ""
    if cache is not None and (saved := cache.read(key, DEPENDENCIES)) is not None:
        return saved
    result = imports(name, parse(source))
    if cache is not None:
        cache.write(key, result, DEPENDENCIES)
    return result


def _composes(module: str, entries: Sequence[str]) -> bool:
    """An entry point: each program's `__main__` and the declared entries, which compose the modules."""
    return module.endswith(".__main__") or module in entries


def _deepest(reached: frozenset[str]) -> Iterator[str]:
    """Importing a module also loads its packages; only the deepest names count."""
    return (target for target in reached if not any(other.startswith(target + ".") for other in reached))


def entry_data(sources: Iterable[Source], data: Sequence[str], entries: Sequence[str], cache: Cache | None) -> Iterator[Finding]:
    """Only entry points, and data modules themselves, import the data packages; everything else, tests included, is handed its values."""
    detail = "Take the values as inputs: only entry points and data modules import data."
    for source in sources:
        module = module_name(source.name)
        if _composes(module, entries) or within_any(module, data):
            continue
        reached = frozenset(target for target in dependencies(source.name, source.text, cache=cache) if within_any(target, data))
        yield from (Finding("entry-data", module, "", target, 0, detail) for target in sorted(_deepest(reached)))


def _owner(module: str, layers: Sequence[Layer]) -> Placed | None:
    """The declared module a source module belongs to, with its place bottom first: the one whose package holds it most closely."""
    held = ((len(package), Placed(place, layer)) for place, layer in enumerate(layers) for package in layer.packages if within(module, package))
    _, placed = max(held, key=lambda found: found[0], default=(0, None))
    return placed


def _crossing(module: str, mine: Placed, target: str, layers: Sequence[Layer]) -> Finding | None:
    """What is wrong with module, in mine, importing target: a layer above it, or another layer's insides."""
    theirs = _owner(target, layers)
    if theirs is None or theirs.layer is mine.layer:
        return None
    layer, other = mine.layer, theirs.layer
    if theirs.place > mine.place:
        detail = f"{layer.name} sits below {other.name}: move what both need down, or declare {layer.name} higher."
        return Finding("layer-order", module, "", target, 0, detail)
    if other.api and not within_any(target, other.api):
        detail = f"{target} is inside {other.name}: use its API ({', '.join(other.api)}), or add the module to it."
        return Finding("module-api", module, "", target, 0, detail)
    return None


def layering(sources: Iterable[Source], layers: Sequence[Layer], entries: Sequence[str], cache: Cache | None) -> Iterator[Finding]:
    """Each module imports only modules declared below its own, and from one that declares an API, only that API.

    Entry points (each `__main__`, and `entries`) compose the modules, so only they
    reach across; tests aren't sources here."""
    for source in sources:
        module = module_name(source.name)
        if _composes(module, entries) or (mine := _owner(module, layers)) is None:
            continue
        reached = frozenset(dependencies(source.name, source.text, cache=cache))
        crossings = (_crossing(module, mine, target, layers) for target in sorted(_deepest(reached)))
        yield from (finding for finding in crossings if finding is not None)


CONTRACT_IMPORTS: Final = frozenset({"protocol", "winapi", "winapi.shapes", "winapi.pcm"})
"""Beyond the standard library, pydantic, `cell` and each other, all a contract may import:
the wire protocol and the plain-Python winapi value modules."""


def _contract_may_import(target: str) -> bool:
    top, _, _ = target.partition(".")
    if top in sys.stdlib_module_names or top in ("pydantic", "contracts", "cell"):
        return True
    # The graph also names imported attributes (`protocol.Tool`), so allowed modules match as prefixes.
    return target == "winapi" or within_any(target, CONTRACT_IMPORTS - {"winapi"})


def contract_isolation(imported_by: Mapping[str, frozenset[str]]) -> Iterator[Finding]:
    """Contracts are values both sides import, so none may reach an effect owner, Qt or a service."""
    for module in sorted(name for name in imported_by if within(name, "contracts")):
        yield from (
            Finding("contract-isolation", module, "", "", 0, f"{module} → {target}")
            for target in sorted(imported_by[module])
            if not _contract_may_import(target)
        )


APPLICATION_LAYERS: Final = ("assistant", "desktop_ui")


def _keyboard(module: str) -> bool:
    """Whether the keyboard process may load module: anything outside the application layers."""
    return not within_any(module, APPLICATION_LAYERS)


def _routes(graph: Mapping[str, frozenset[str]], entries: Iterable[str], onward: Callable[[str], bool]) -> Iterator[tuple[str, ...]]:
    """One shortest static import route per module, including package initializers, in breadth-first order.

    A route continues past its last module only where `onward` holds. Each level keeps
    the first route to each module it reaches, in the order the routes were found.
    """
    frontier: tuple[tuple[str, ...], ...] = tuple((entry,) for entry in entries)
    visited: frozenset[str] = frozenset()
    while frontier:
        first = frozendict((route[-1], index) for index, route in reversed(tuple(enumerate(frontier))))
        level: tuple[tuple[str, ...], ...] = tuple(
            route for index, route in enumerate(frontier) if first[route[-1]] == index and route[-1] not in visited
        )
        yield from level
        visited = visited.union(first)
        frontier = tuple(
            (*route, target) for route in level if onward(route[-1]) for target in sorted(graph.get(route[-1], frozenset())) if target not in visited
        )


def keyboard_isolation(graph: Mapping[str, frozenset[str]], dynamic_imports: Mapping[str, tuple[Finding, ...]]) -> Iterator[Finding]:
    """The keyboard reaches no application module, and imports nothing it can't resolve statically on the way.

    Keyboard routes stop at the first application module they reach."""
    for route in _routes(graph, (module for module in sorted(graph) if within(module, "keyboard")), _keyboard):
        last = route[-1]
        if _keyboard(last):
            yield from dynamic_imports[last]
        else:
            yield Finding("keyboard-isolation", route[0], "", "", 0, " → ".join(route))


def _static_import(call: ast.Call) -> bool:
    """A dynamic import of a literal absolute module name, which the keyboard graph can follow."""
    match call.args:
        case [ast.Constant(value=str() as target), *_]:
            return not target.startswith(".") and not any(keyword.arg == "level" for keyword in call.keywords)
        case _:
            return False


def dynamic_imports(tree: ast.Module, module: str) -> Iterator[Finding]:
    """Each import a module makes at run time whose target the keyboard graph cannot follow."""
    aliases = import_aliases(tree)
    detail = "Keyboard dependencies require statically resolvable absolute import targets."
    return (
        Finding("keyboard-import", module, "", ast.unparse(node), node.lineno, detail)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and call_name(node.func, aliases) in DYNAMIC_IMPORTS and not _static_import(node)
    )
