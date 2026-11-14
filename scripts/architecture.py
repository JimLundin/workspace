"""Process isolation and coding policies, without importing application modules.

The same inventory works in a Git checkout and a deployed source copy. Callers
may supply Git-listed names to bind the review to their checked source snapshot.

Parsing uses private mutable ASTs. Traversals are generators over immutable
breadth-first levels: each level is one tuple and the visited set grows by one
union per level, not per module, so the walks stay linear in the graph. Only
immutable policy reports leave this owner. The rules live in the `*_rules`
modules beside this one; this module reads the checkout, observes each module once
and judges the findings against the declared exceptions.
"""

import ast
import os
import re
import tomllib
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Literal

from pydantic import TypeAdapter

from scripts.constant_rules import enum_shapes, shared_constants
from scripts.declaration_rules import declarations
from scripts.import_rules import Layer, contract_isolation, dependencies, dynamic_imports, entry_data, keyboard_isolation, layering
from scripts.modelling_rules import value_shapes
from scripts.policy import Finding, Text
from scripts.record_rules import Candidate, assigned, records
from scripts.source_analysis import Cache, Source, module_name, parse
from scripts.testing_rules import cached_testing_dependencies
from scripts.usage_rules import (
    Definition,
    Shape,
    cached_references,
    definitions,
    duplicates,
    natives,
    redeclarations,
    references,
    shapes,
    unused_definitions,
)


@dataclass(frozen=True, slots=True)
class ExceptionSpec:
    rule: Literal["explicit-attributes", "immutable-data", "member-table", "mutable-field", "mutable-parameter", "plain-record", "unused-definition"]
    module: Text
    declaration: Text
    expression: Text
    reason: Text

    def matches(self, finding: Finding) -> bool:
        return (self.rule, self.module, self.declaration, self.expression) == (finding.rule, finding.module, finding.declaration, finding.expression)


@dataclass(frozen=True, slots=True)
class Report:
    sources: tuple[str, ...]
    failures: tuple[Finding, ...]
    exceptions: tuple[ExceptionSpec, ...]


@dataclass(frozen=True, slots=True)
class Configuration:
    """The `[tool.workspace.architecture]` table: forbidden imports and exact exceptions."""

    exceptions: tuple[ExceptionSpec, ...] = ()
    constants: tuple[Text, ...] = ()
    """Packages whose modules read other modules' constants only as `module.NAME`, and only from declarations-only modules."""
    data: tuple[Text, ...] = ()
    """Packages of values that only entry points and each other import."""
    entries: tuple[Text, ...] = ()
    """Modules besides each program's `__main__` that may import `data`."""
    layers: tuple[Layer, ...] = ()
    """The big modules, bottom first: each imports only those below it, and only their APIs."""


@dataclass(frozen=True, slots=True)
class Observation:
    declarations: tuple[Finding, ...]
    dynamic_imports: tuple[Finding, ...]
    records: tuple[Candidate, ...]
    assigned: frozenset[str]
    """Attribute names the module assigns through a receiver other than `self`."""
    definitions: tuple[Definition, ...]
    shapes: tuple[Shape, ...]
    natives: tuple[Finding, ...]
    """Each Win32 export the module declares, as a `native-redeclaration` finding until another module declares it too."""
    referenced: frozendict[str, int]
    """How often the module names each name."""


CONFIGURATION = TypeAdapter[Configuration](Configuration)
OBSERVATION = TypeAdapter[Observation](Observation)


def _walked(root: Path) -> Iterator[str]:
    """Every file under root, pruning hidden and cache directories as os.walk descends."""
    for folder, directories, files in os.walk(root):
        directories[:] = sorted(name for name in directories if not name.startswith((".", "__pycache__")))
        yield from ((Path(folder) / name).relative_to(root).as_posix() for name in files)


def python_sources(root: Path, names: Iterable[str] | None = None) -> tuple[str, ...]:
    if names is None:
        names = _walked(root)
    return tuple(
        sorted(
            {
                name
                for name in names
                if name.endswith((".py", ".pyw"))
                and not any(part.startswith((".", "__pycache__")) for part in Path(name).parts)
                and (root / name).is_file()
            }
        )
    )


def _configuration(root: Path) -> Configuration:
    match tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")):
        case {"tool": {"workspace": {"architecture": object() as value}}}:
            configuration = CONFIGURATION.validate_python(value)
        case _:
            raise ValueError("Architecture configuration must contain its named table.")
    exceptions = tuple(replace(entry, expression=ast.unparse(ast.parse(entry.expression, mode="eval").body)) for entry in configuration.exceptions)
    keys = tuple((entry.rule, entry.module, entry.declaration, entry.expression) for entry in exceptions)
    if len(frozenset(keys)) != len(keys):
        raise ValueError("Duplicate architecture exception.")
    for entry in exceptions:
        if any("*" in value for value in (entry.module, entry.declaration)):
            raise ValueError("Architecture exceptions require a supported rule and an exact declaration.")
    return replace(configuration, exceptions=exceptions)


def observation(source: Source, cache: Cache | None) -> Observation:
    key = cache.key("architecture", source) if cache is not None else ""
    if cache is not None and (saved := cache.read(key, OBSERVATION)):
        return saved
    tree = parse(source)
    module = module_name(source.name)
    result = Observation(
        (*declarations(tree, module), *value_shapes(tree, module)),
        tuple(dynamic_imports(tree, module)),
        tuple(records(tree, module)),
        assigned(tree),
        tuple(definitions(tree.body, module)),
        tuple(shapes(tree, module)),
        tuple(natives(tree, module)),
        references(tree),
    )
    if cache is not None:
        cache.write(key, result, OBSERVATION)
    return result


TEXT_REFERENCES: Final = (".cmd", ".ps1", ".js")
"""Tracked text that can name a Python definition: launch scripts and page scripts."""


@dataclass(frozen=True, slots=True)
class Checkout:
    """The reviewed checkout: its root, every name listed in it, and every Python source read from it."""

    root: Path
    listed: tuple[str, ...]
    sources: tuple[Source, ...]

    def production(self) -> tuple[Source, ...]:
        return tuple(source for source in self.sources if not source.name.startswith("tests/"))

    def tested(self, cache: Cache | None) -> frozenset[str]:
        """Every name the tests refer to."""
        return frozenset[str]().union(*(cached_references(source, cache) for source in self.sources if source.name.startswith("tests/")))

    def text_words(self) -> Counter[str]:
        """The words in tracked launch and page scripts, which can name a Python definition."""
        texts = (name for name in self.listed if name.endswith(TEXT_REFERENCES) and not name.startswith("tests/") and (self.root / name).is_file())
        return Counter(word for name in texts for word in re.findall(r"[A-Za-z_]\w*", (self.root / name).read_text(encoding="utf-8")))


def _module_findings(observed: tuple[Observation, ...], checkout: Checkout, cache: Cache | None) -> Iterator[Finding]:
    """What each module shows on its own: its declarations, its plain records and its patches and mocks."""
    # A class whose attribute another owner assigns (`calls.current = ...`) holds changing state.
    written = frozenset[str]().union(*(item.assigned for item in observed))
    yield from (finding for item in observed for finding in item.declarations)
    yield from (record.finding for item in observed for record in item.records if record.attributes.isdisjoint(written))
    yield from (finding for source in checkout.sources for finding in cached_testing_dependencies(source, cache))


def _usage_findings(observed: tuple[Observation, ...], checkout: Checkout, cache: Cache | None) -> Iterator[Finding]:
    """What only every module together shows: unused definitions, copied functions and Win32 functions declared twice."""
    production = sum((Counter(item.referenced) for item in observed), checkout.text_words())
    yield from unused_definitions((definition for item in observed for definition in item.definitions), production, checkout.tested(cache))
    yield from duplicates(shape for item in observed for shape in item.shapes)
    yield from redeclarations(finding for item in observed for finding in item.natives)


def _findings(checkout: Checkout, configuration: Configuration, cache: Cache | None) -> Iterator[Finding]:
    loaded = checkout.production()
    observations = frozendict({module_name(source.name): observation(source, cache) for source in loaded})
    imported_by = frozendict({module_name(source.name): dependencies(source.name, source.text, cache=cache) for source in loaded})
    graph = frozendict({module: imported & frozenset(observations) for module, imported in imported_by.items()})
    observed = tuple(observations.values())
    yield from _module_findings(observed, checkout, cache)
    yield from keyboard_isolation(graph, frozendict({module: item.dynamic_imports for module, item in observations.items()}))
    yield from contract_isolation(imported_by)
    yield from _usage_findings(observed, checkout, cache)
    yield from shared_constants(loaded, configuration.constants)
    yield from entry_data(checkout.sources, configuration.data, configuration.entries, cache)
    yield from layering(loaded, configuration.layers, configuration.entries, cache)
    yield from enum_shapes(loaded)


def _judged(sources: tuple[str, ...], findings: tuple[Finding, ...], exceptions: tuple[ExceptionSpec, ...]) -> Report:
    """The findings no exception accepts, and each exception that accepts none: its expression no longer exists."""
    accepted = tuple(exception for exception in exceptions if any(exception.matches(finding) for finding in findings))
    stale = (
        Finding(
            "stale-exception",
            exception.module,
            exception.declaration,
            exception.expression,
            0,
            "Remove the exception: its exact expression no longer exists.",
        )
        for exception in exceptions
        if exception not in accepted
    )
    failures = (*(finding for finding in findings if not any(exception.matches(finding) for exception in accepted)), *stale)
    return Report(sources, failures, accepted)


def review(root: Path, names: Iterable[str] | None = None, *, cache: Cache | None = None) -> Report:
    listed = tuple(_walked(root) if names is None else names)
    sources = python_sources(root, listed)
    configuration = _configuration(root)
    checkout = Checkout(root, listed, tuple(Source(name, (root / name).read_text(encoding="utf-8")) for name in sources))
    return _judged(sources, tuple(_findings(checkout, configuration, cache)), configuration.exceptions)
