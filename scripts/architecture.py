"""Process isolation and coding policies, without importing application modules.

The same inventory works in a Git checkout and a deployed source copy. Callers
may supply Git-listed names to bind the review to their checked source snapshot.

Parsing uses private mutable ASTs and traversal worklists: copying the growing
graph at every step would add substantial algorithmic overhead. Only immutable
policy reports leave this owner.
"""

import ast
import os
import sys
import tomllib
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import StrictStr, StringConstraints, TypeAdapter

from restart_plan import call_name, import_aliases, imports, module_name
from scripts.source_analysis import Cache, Source, parse

type Text = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]

REFLECTION = frozenset({"getattr", "hasattr", "setattr", "delattr"})
MUTABLE_TYPES = frozenset(
    {
        "list",
        "dict",
        "set",
        "bytearray",
        "collections.deque",
        "typing.List",
        "typing.Dict",
        "typing.Set",
        "typing.MutableMapping",
        "typing.MutableSequence",
        "typing.MutableSet",
        "collections.abc.MutableMapping",
        "collections.abc.MutableSequence",
        "collections.abc.MutableSet",
    }
)


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    module: str
    declaration: str
    expression: str
    line: int
    detail: str

    def describe(self) -> str:
        location = self.module + ("." + self.declaration if self.declaration else "")
        return f"{self.rule}: {location}:{self.line}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ExceptionSpec:
    rule: Literal["explicit-attributes", "immutable-data", "mutable-field"]
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


@dataclass(frozen=True, slots=True)
class Observation:
    declarations: tuple[Finding, ...]
    dynamic_imports: tuple[Finding, ...]


CONFIGURATION = TypeAdapter[Configuration](Configuration)
OBSERVATION = TypeAdapter[Observation](Observation)
DEPENDENCIES = TypeAdapter[frozenset[str]](frozenset[str])
FINDINGS = TypeAdapter[tuple[Finding, ...]](tuple[Finding, ...])


def python_sources(root: Path, names: Iterable[str] | None = None) -> tuple[str, ...]:
    if names is None:
        found: list[str] = []
        for folder, directories, files in os.walk(root):
            directories[:] = sorted(name for name in directories if not name.startswith((".", "__pycache__")))
            found.extend((Path(folder) / name).relative_to(root).as_posix() for name in files)
        names = found
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


def dependencies(name: str, text: str, *, cache: Cache | None = None) -> frozenset[str]:
    source = Source(name, text)
    key = cache.key("dependencies", source) if cache is not None else ""
    if cache is not None and (saved := cache.read(key, DEPENDENCIES)) is not None:
        return saved
    result = imports(name, parse(source))
    if cache is not None:
        cache.write(key, result, DEPENDENCIES)
    return result


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


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


APPLICATION_LAYERS: Final = ("assistant", "desktop_ui")


def _routes(graph: Mapping[str, frozenset[str]], entry: str) -> Iterator[tuple[str, ...]]:
    """One shortest static import route per module, including package initializers."""
    pending: deque[tuple[str, ...]] = deque([(entry,)])
    visited: set[str] = set()
    while pending:
        route = pending.popleft()
        module = route[-1]
        if module in visited:
            continue
        visited.add(module)
        yield route
        pending.extend((*route, target) for target in sorted(graph.get(module, frozenset())) if target not in visited)


CONTRACT_IMPORTS: Final = frozenset({"protocol", "winapi", "winapi.shapes", "winapi.pcm", "winapi.system_notices"})
"""Beyond the standard library, pydantic and each other, all a contract may import:
the wire protocol and the plain-Python winapi value modules."""


def contract_isolation(imported_by: Mapping[str, frozenset[str]]) -> Iterator[Finding]:
    """Contracts are values both sides import, so none may reach an effect owner, Qt or a service."""
    for module in sorted(name for name in imported_by if _within(name, "contracts")):
        for target in sorted(imported_by[module]):
            top = target.split(".")[0]
            # The graph also names imported attributes (`protocol.Tool`), so allowed modules match as prefixes.
            if (
                top in sys.stdlib_module_names
                or top in ("pydantic", "contracts")
                or target == "winapi"
                or any(_within(target, allowed) for allowed in CONTRACT_IMPORTS - {"winapi"})
            ):
                continue
            yield Finding("contract-isolation", module, "", "", 0, f"{module} → {target}")


PROCESSES: Final = frozendict(
    {
        ("desktop_ui", "desktop"): ("assistant", "automation"),
        ("assistant", "automation"): ("desktop_ui", "desktop", "PySide6", "PyQt6"),
    }
)
"""Each program's packages, and what none of them may reach even through others: the desktop
and the assistant run without each other and share only `contracts`."""


KEEPER_PROGRAM_EDGES: Final = frozenset({("keeper", "keeper_ui")})
"""Imports made only when that module runs as its own program: `keeper.main` opens the
keeper's dialog. The assistant uses the keeper's install helpers, never its program."""


def process_isolation(imported_by: Mapping[str, frozenset[str]]) -> Iterator[Finding]:
    graph = frozendict(
        (module, frozenset(target for target in targets if (module, target) not in KEEPER_PROGRAM_EDGES)) for module, targets in imported_by.items()
    )
    for packages, forbidden in PROCESSES.items():
        for entry in sorted(module for module in graph if any(_within(module, package) for package in packages)):
            for route in _routes(graph, entry):
                if any(_within(route[-1], package) for package in forbidden):
                    yield Finding("process-isolation", entry, "", "", 0, " → ".join(route))
                    break


def _scope_aliases(tree: ast.AST, inherited: Mapping[str, str]) -> dict[str, str]:
    local = dict(inherited)
    pending = list(ast.iter_child_nodes(tree))
    while pending:
        node = pending.pop()
        match node:
            case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
                continue
            case ast.Import(names=names):
                local.update({alias.asname or alias.name.split(".")[0]: alias.name if alias.asname else alias.name.split(".")[0] for alias in names})
            case ast.ImportFrom(module=base, level=0, names=names) if base:
                local.update({alias.asname or alias.name: base + "." + alias.name for alias in names})
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                resolved = call_name(value, local)
                if resolved in REFLECTION or resolved in {"builtins." + item for item in REFLECTION}:
                    local[name] = resolved
            case _:
                pass
        pending.extend(ast.iter_child_nodes(node))
    return local


def _declarations(tree: ast.AST, module: str, declaration: str = "", aliases: Mapping[str, str] | None = None) -> Iterator[Finding]:
    # Copy aliases once per lexical scope, not for every expression. Imports
    # inside conditional statements still belong to their enclosing scope.
    local = aliases or {}
    match tree:
        case ast.Module() | ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
            local = _scope_aliases(tree, local)
        case _:
            pass
    match tree:
        case ast.ClassDef(name=name) | ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
            declaration = ".".join(part for part in (declaration, name) if part)
        case _:
            pass
    match tree:
        case ast.ClassDef(name=name, decorator_list=decorators, body=fields):
            for decorator in decorators:
                flags: dict[str | None, ast.expr] = {}
                match decorator:
                    case ast.Call(func=function, keywords=keywords):
                        flags = {keyword.arg: keyword.value for keyword in keywords}
                    case _:
                        function = decorator
                if call_name(function, local) != "dataclasses.dataclass":
                    continue
                match flags.get("frozen"), flags.get("slots"):
                    case ast.Constant(value=True), ast.Constant(value=True):
                        pass
                    case _:
                        yield Finding(
                            "immutable-data",
                            module,
                            declaration,
                            name,
                            tree.lineno,
                            "Data records require frozen=True and slots=True, or an exact necessary-mutation exception.",
                        )
                # A mutable owner has one state exception. Frozen records need
                # a separate declaration for each concrete mutable field.
                match flags.get("frozen"):
                    case ast.Constant(value=True):
                        for field in fields:
                            match field:
                                case ast.AnnAssign(target=ast.Name(id=field_name), annotation=annotation):
                                    if any(call_name(node, local) in MUTABLE_TYPES for node in ast.walk(annotation)):
                                        yield Finding(
                                            "mutable-field",
                                            module,
                                            declaration + "." + field_name,
                                            ast.unparse(annotation),
                                            field.lineno,
                                            "Frozen records must not contain concrete mutable collections without an exact necessity.",
                                        )
                                case _:
                                    pass
                    case _:
                        pass
        case ast.Call(func=function) if call_name(function, local) in REFLECTION | {"builtins." + name for name in REFLECTION}:
            yield Finding(
                "explicit-attributes",
                module,
                declaration,
                ast.unparse(tree),
                tree.lineno,
                "Use typed direct attributes, or declare an exact native/inspection exception.",
            )
        case _:
            pass
    for child in ast.iter_child_nodes(tree):
        yield from _declarations(child, module, declaration, local)


def _constant(value: ast.expr, bound: frozenset[str]) -> bool:
    """A literal or a name from outside the function, or a call, tuple or attribute built only from those."""
    match value:
        case ast.Constant():
            return True
        case ast.Name(id=name):
            return name not in bound
        case ast.Attribute(value=base) | ast.UnaryOp(operand=base):
            return _constant(base, bound)
        case ast.Tuple(elts=items):
            return all(_constant(item, bound) for item in items)
        case ast.Call(func=function, args=arguments, keywords=keywords):
            return _constant(function, bound) and all(_constant(item, bound) for item in (*arguments, *(keyword.value for keyword in keywords)))
        case _:
            return False


def _members(pattern: ast.pattern) -> bool:
    match pattern:
        case ast.MatchValue(value=ast.Attribute()):
            return True
        case ast.MatchOr(patterns=patterns):
            return all(_members(item) for item in patterns)
        case _:
            return False


def _translates(cases: Iterable[ast.match_case], bound: frozenset[str]) -> bool:
    """Every case but a wildcard names enum members and only returns or assigns one constant."""

    def constant(case: ast.match_case) -> bool:
        match case.body:
            case [ast.Return(value=ast.expr() as value)] | [ast.Assign(value=value)]:
                return _constant(value, bound)
            case _:
                return False

    named = tuple(case for case in cases if not (isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None))
    return len(named) >= 2 and all(_members(case.pattern) and case.guard is None and constant(case) for case in named)


def _bound(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    """The function's parameters and every name it assigns: values that vary between calls."""
    arguments = function.args
    parameters = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *(item for item in (arguments.vararg, arguments.kwarg) if item))
    stored = (node.id for node in ast.walk(function) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store))
    return frozenset((*(item.arg for item in parameters), *stored))


def enum_translations(tree: ast.AST, module: str, declaration: str = "", bound: frozenset[str] = frozenset()) -> Iterator[Finding]:
    """A `match` that only maps enum members to constants belongs in an `every_member` table."""
    for child in ast.iter_child_nodes(tree):
        match child:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                yield from enum_translations(child, module, ".".join(part for part in (declaration, name) if part), _bound(child))
                continue
            case ast.ClassDef(name=name):
                yield from enum_translations(child, module, ".".join(part for part in (declaration, name) if part), bound)
                continue
            case ast.Match(subject=subject, cases=cases) if _translates(cases, bound):
                detail = "Translate enum members with a contracts.members.every_member table, or a frozendict for a partial one."
                yield Finding("enum-translation", module, declaration, ast.unparse(subject), child.lineno, detail)
            case _:
                pass
        yield from enum_translations(child, module, declaration, bound)


def observation(source: Source, cache: Cache | None) -> Observation:
    key = cache.key("architecture", source) if cache is not None else ""
    if cache is not None and (saved := cache.read(key, OBSERVATION)) is not None:
        return saved
    tree = parse(source)
    module = module_name(source.name)
    aliases = import_aliases(tree)
    dynamic: list[Finding] = []
    for node in ast.walk(tree):
        match node:
            case ast.Call(func=function, args=args, keywords=keywords) if call_name(function, aliases) in (
                "importlib.import_module",
                "__import__",
                "builtins.__import__",
            ):
                match args:
                    case [ast.Constant(value=str() as target), *_] if not target.startswith(".") and not any(
                        keyword.arg == "level" for keyword in keywords
                    ):
                        pass
                    case _:
                        dynamic.append(
                            Finding(
                                "keyboard-import",
                                module,
                                "",
                                ast.unparse(node),
                                node.lineno,
                                "Keyboard dependencies require statically resolvable absolute import targets.",
                            )
                        )
            case _:
                pass
    result = Observation((*_declarations(tree, module), *enum_translations(tree, module)), tuple(dynamic))
    if cache is not None:
        cache.write(key, result, OBSERVATION)
    return result


FORBIDDEN_TEST_TOOLS = frozenset({"unittest.mock", "mock", "pytest_mock", "mockito", "pytest.MonkeyPatch"})


def testing_dependencies(source: Source) -> Iterator[Finding]:
    """Reject framework replacement seams in production and test source alike."""
    tree = parse(source)
    aliases = import_aliases(tree)
    for node in ast.walk(tree):
        target = ""
        match node:
            case ast.Import(names=names):
                target = next(
                    (item.name for item in names if any(item.name == name or item.name.startswith(name + ".") for name in FORBIDDEN_TEST_TOOLS)), ""
                )
            case ast.ImportFrom(module=str() as module, names=names):
                imports = (module, *(module + "." + item.name for item in names))
                target = next((item for item in imports if any(item == name or item.startswith(name + ".") for name in FORBIDDEN_TEST_TOOLS)), "")
            case ast.Call(func=function, args=args):
                call = call_name(function, aliases)
                if call in ("importlib.import_module", "__import__", "builtins.__import__"):
                    match args:
                        case [ast.Constant(value=str() as module), *_] if module in FORBIDDEN_TEST_TOOLS:
                            target = module
                        case _:
                            pass
                elif any(call == name or call.startswith(name + ".") for name in FORBIDDEN_TEST_TOOLS) or call.split(".")[0] in (
                    "monkeypatch",
                    "mocker",
                ):
                    target = call
            case ast.arg(arg="monkeypatch" | "mocker" as name):
                target = name
            case _:
                pass
        if target:
            match node:
                case ast.stmt(lineno=line) | ast.expr(lineno=line) | ast.arg(lineno=line):
                    yield Finding(
                        "testing-dependencies",
                        module_name(source.name),
                        "",
                        ast.unparse(node),
                        line,
                        "Patches and mocks are disallowed; pass explicit dependencies or use real local resources: " + target,
                    )
                case _:
                    pass


def cached_testing_dependencies(source: Source, cache: Cache | None) -> tuple[Finding, ...]:
    key = cache.key("testing-dependencies", source) if cache is not None else ""
    if cache is not None and (saved := cache.read(key, FINDINGS)) is not None:
        return saved
    result = tuple(testing_dependencies(source))
    if cache is not None:
        cache.write(key, result, FINDINGS)
    return result


def review(root: Path, names: Iterable[str] | None = None, *, cache: Cache | None = None) -> Report:
    sources = python_sources(root, names)
    configuration = _configuration(root)
    exceptions = configuration.exceptions
    all_source = tuple(Source(name, (root / name).read_text(encoding="utf-8")) for name in sources)
    loaded = tuple(source for source in all_source if not source.name.startswith("tests/"))
    observations = {module_name(source.name): observation(source, cache) for source in loaded}
    imported_by = {module_name(source.name): dependencies(source.name, source.text, cache=cache) for source in loaded}
    graph = {module: imported & observations.keys() for module, imported in imported_by.items()}
    findings = [finding for observed in observations.values() for finding in observed.declarations]
    findings.extend(finding for source in all_source for finding in cached_testing_dependencies(source, cache))
    pending: deque[tuple[str, ...]] = deque((module,) for module in sorted(graph) if module == "miryoku" or module.startswith("miryoku."))
    visited: set[str] = set()
    while pending:
        route = pending.popleft()
        module = route[-1]
        if module in visited:
            continue
        visited.add(module)
        if any(_within(module, layer) for layer in (*APPLICATION_LAYERS, "automation")):
            findings.append(Finding("keyboard-isolation", route[0], "", "", 0, " → ".join(route)))
            continue
        findings.extend(observations[module].dynamic_imports)
        pending.extend((*route, target) for target in sorted(graph[module]) if target not in visited)
    findings.extend(contract_isolation(imported_by))
    findings.extend(process_isolation(imported_by))
    accepted = tuple(exception for exception in exceptions if any(exception.matches(finding) for finding in findings))
    failures = [finding for finding in findings if not any(exception.matches(finding) for exception in accepted)]
    failures.extend(
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
    return Report(sources, tuple(failures), accepted)
