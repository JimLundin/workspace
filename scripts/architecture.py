"""Process isolation and coding policies, without importing application modules.

The same inventory works in a Git checkout and a deployed source copy. Callers
may supply Git-listed names to bind the review to their checked source snapshot.

Parsing uses private mutable ASTs. Traversals are generators over immutable
breadth-first levels: each level is one tuple and the visited set grows by one
union per level, not per module, so the walks stay linear in the graph. Only
immutable policy reports leave this owner.
"""

import ast
import os
import re
import sys
import tomllib
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from functools import reduce
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import StrictStr, StringConstraints, TypeAdapter

from scripts.source_analysis import Cache, Source, call_name, import_aliases, imports, module_name, parse

type Text = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]

REFLECTION = frozenset({"getattr", "hasattr", "setattr", "delattr"})
REFLECTION_CALLS = REFLECTION | {"builtins." + name for name in REFLECTION}
DYNAMIC_IMPORTS = frozenset({"importlib.import_module", "__import__", "builtins.__import__"})
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
        "collections.defaultdict",
        "collections.Counter",
        "collections.OrderedDict",
        "typing.DefaultDict",
        "typing.Deque",
        "typing.Counter",
        "typing.OrderedDict",
    }
)
OVERRIDES: Final = frozenset({"typing.override", "typing_extensions.override"})
"""Decorators marking a method whose signature its base class dictates."""


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
    rule: Literal["explicit-attributes", "immutable-data", "mutable-field", "mutable-parameter", "plain-record", "unused-definition"]
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
class Candidate:
    """A plain class whose `__init__` only stores its inputs, and the attributes it stores."""

    finding: Finding
    attributes: frozenset[str]


@dataclass(frozen=True, slots=True)
class Definition:
    """A named definition, unused until a reference outside its own body names it."""

    finding: Finding
    own: int
    """How often the definition names itself, as a recursive function or a class's own annotations do."""


@dataclass(frozen=True, slots=True)
class Observation:
    declarations: tuple[Finding, ...]
    dynamic_imports: tuple[Finding, ...]
    records: tuple[Candidate, ...]
    assigned: frozenset[str]
    """Attribute names the module assigns through a receiver other than `self`."""
    definitions: tuple[Definition, ...]
    referenced: frozendict[str, int]
    """How often the module names each name."""


CONFIGURATION = TypeAdapter[Configuration](Configuration)
OBSERVATION = TypeAdapter[Observation](Observation)
DEPENDENCIES = TypeAdapter[frozenset[str]](frozenset[str])
REFERENCES = TypeAdapter[frozenset[str]](frozenset[str])
FINDINGS = TypeAdapter[tuple[Finding, ...]](tuple[Finding, ...])


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


def _keyboard(module: str) -> bool:
    """Whether the keyboard process may load module: anything outside the application layers."""
    return not any(_within(module, layer) for layer in (*APPLICATION_LAYERS, "automation"))


def _onward(_: str) -> bool:
    return True


def _routes(graph: Mapping[str, frozenset[str]], entries: Iterable[str], onward: Callable[[str], bool] = _onward) -> Iterator[tuple[str, ...]]:
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


CONTRACT_IMPORTS: Final = frozenset({"protocol", "winapi", "winapi.shapes", "winapi.pcm", "winapi.system_notices"})
"""Beyond the standard library, pydantic, `cell` and each other, all a contract may import:
the wire protocol and the plain-Python winapi value modules."""


def contract_isolation(imported_by: Mapping[str, frozenset[str]]) -> Iterator[Finding]:
    """Contracts are values both sides import, so none may reach an effect owner, Qt or a service."""
    for module in sorted(name for name in imported_by if _within(name, "contracts")):
        for target in sorted(imported_by[module]):
            top = target.split(".")[0]
            # The graph also names imported attributes (`protocol.Tool`), so allowed modules match as prefixes.
            if (
                top in sys.stdlib_module_names
                or top in ("pydantic", "contracts", "cell")
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


def process_isolation(imported_by: Mapping[str, frozenset[str]]) -> Iterator[Finding]:
    graph = imported_by
    for packages, forbidden in PROCESSES.items():
        for entry in sorted(module for module in graph if any(_within(module, package) for package in packages)):
            for route in _routes(graph, (entry,)):
                if any(_within(route[-1], package) for package in forbidden):
                    yield Finding("process-isolation", entry, "", "", 0, " → ".join(route))
                    break


def _scope_nodes(tree: ast.AST) -> Iterator[ast.AST]:
    """The nodes of tree's own scope, depth first from its last child, skipping nested classes and functions."""
    for node in reversed(tuple(ast.iter_child_nodes(tree))):
        match node:
            case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
                pass
            case _:
                yield node
                yield from _scope_nodes(node)


def _bound_alias(local: frozendict[str, str], node: ast.AST) -> frozendict[str, str]:
    """The aliases after node: imports bind names, and so does assigning a reflection builtin."""
    match node:
        case ast.Import(names=names):
            return local | {alias.asname or alias.name.split(".")[0]: alias.name if alias.asname else alias.name.split(".")[0] for alias in names}
        case ast.ImportFrom(module=base, level=0, names=names) if base:
            return local | {alias.asname or alias.name: base + "." + alias.name for alias in names}
        case ast.Assign(targets=[ast.Name(id=name)], value=value) if (resolved := call_name(value, local)) in REFLECTION_CALLS:
            return local | {name: resolved}
        case _:
            return local


def _scope_aliases(tree: ast.AST, inherited: Mapping[str, str]) -> frozendict[str, str]:
    # Only an import statement or a reflection alias makes a new map; other nodes pass it on.
    return reduce(_bound_alias, _scope_nodes(tree), frozendict(inherited))


def _constant_tag(annotation: ast.expr, aliases: Mapping[str, str]) -> bool:
    """`Literal[x]` with one value: the JSON tag of a union member, which decides nothing."""
    match annotation:
        case ast.Subscript(value=value, slice=ast.Constant() | ast.Attribute()):
            return call_name(value, aliases) == "typing.Literal"
        case _:
            return False


def _declarations(tree: ast.AST, module: str, declaration: str = "", aliases: Mapping[str, str] | None = None) -> Iterator[Finding]:
    # Copy aliases once per lexical scope, not for every expression. Imports
    # inside conditional statements still belong to their enclosing scope.
    local = aliases or frozendict()
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
                yield from (
                    Finding(
                        "kind-field",
                        module,
                        declaration + ".kind",
                        ast.unparse(field.annotation),
                        field.lineno,
                        "Give each kind its own type and tag it with one constant Literal, or name the attribute for what it is.",
                    )
                    for field in fields
                    if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name) and field.target.id == "kind"
                    if not _constant_tag(field.annotation, local)
                )
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
        case ast.FunctionDef(args=arguments, decorator_list=decorators) | ast.AsyncFunctionDef(args=arguments, decorator_list=decorators) if not any(
            call_name(decorator, local) in OVERRIDES for decorator in decorators
        ):
            yield from (
                Finding(
                    "mutable-parameter",
                    module,
                    declaration + "." + parameter.arg,
                    ast.unparse(parameter.annotation),
                    parameter.lineno,
                    "Take an immutable type (a tuple, frozendict, frozen record, or Sequence, Mapping, Set or Iterable), "
                    "or declare the exact signature a dependency dictates.",
                )
                for parameter in (
                    *arguments.posonlyargs,
                    *arguments.args,
                    *arguments.kwonlyargs,
                    *(item for item in (arguments.vararg, arguments.kwarg) if item),
                )
                if parameter.annotation is not None and any(call_name(node, local) in MUTABLE_TYPES for node in ast.walk(parameter.annotation))
            )
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


def _bound(function: ast.FunctionDef | ast.AsyncFunctionDef | None) -> frozenset[str]:
    """The function's parameters and every name it assigns: values that vary between calls."""
    if function is None:
        return frozenset()
    arguments = function.args
    parameters = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *(item for item in (arguments.vararg, arguments.kwarg) if item))
    stored = (node.id for node in ast.walk(function) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store))
    return frozenset((*(item.arg for item in parameters), *stored))


def _numeric(items: Iterable[ast.expr]) -> bool:
    return all(isinstance(item, ast.Name) and item.id in ("int", "float") for item in items)


def value_shapes(
    tree: ast.AST, module: str, declaration: str = "", function: ast.FunctionDef | ast.AsyncFunctionDef | None = None
) -> Iterator[Finding]:
    """One pass for the modelling rules.

    A `match` that only maps enum members to constants belongs in an `every_member`
    table; a fixed `tuple` of only ints and floats is a point, size or span that
    needs its own type; a function doesn't fill a local container in a loop. A
    function's assigned names are collected only for a `match` whose patterns all
    name members, the rare case that needs them.
    """
    for child in ast.iter_child_nodes(tree):
        match child:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                inner = ".".join(part for part in (declaration, name) if part)
                yield from loop_accumulations(child, module, inner)
                yield from value_shapes(child, module, inner, child)
                continue
            case ast.ClassDef(name=name):
                yield from value_shapes(child, module, ".".join(part for part in (declaration, name) if part), function)
                continue
            case ast.Match(subject=subject, cases=cases) if all(
                _members(case.pattern) or (isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None) for case in cases
            ) and _translates(cases, _bound(function)):
                detail = "Translate enum members with a contracts.members.every_member table, or a frozendict for a partial one."
                yield Finding("enum-translation", module, declaration, ast.unparse(subject), child.lineno, detail)
            case ast.Subscript(value=ast.Name(id="tuple"), slice=ast.Tuple(elts=[_, _, *_] as items)) if _numeric(items):
                detail = "Name the values with a frozen domain type and its bounds, such as winapi.shapes.Point or Size."
                yield Finding("bare-tuple", module, declaration, ast.unparse(child), child.lineno, detail)
            case ast.Constant(value=str() as text) if _script(text):
                detail = "Put a page script in a .js file beside the module that runs it, and pass values as its arguments."
                yield Finding("inline-script", module, declaration, text.strip().partition("\n")[0], child.lineno, detail)
            case _:
                pass
        yield from value_shapes(child, module, declaration, function)


_SCRIPT_MARKS: Final = re.compile(r"=>|\bfunction\s*\w*\(|\bdocument\.[a-z]|querySelector")


def _script(text: str) -> bool:
    """A string that reads as JavaScript: script syntax or DOM calls, over at least two lines that end as code does."""
    return _SCRIPT_MARKS.search(text) is not None and sum(1 for line in text.splitlines() if line.rstrip().endswith((";", "{", "}"))) >= 2


CONTAINERS: Final = frozenset({"list", "dict", "set", "bytearray", "deque", "defaultdict", "Counter", "OrderedDict"})
"""Constructors of the mutable containers a function might fill in a loop."""
FILLING: Final = frozenset({"append", "extend", "add", "update", "insert", "setdefault", "appendleft", "extendleft"})
"""Methods that grow a container in place."""


SCOPES: Final = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _scope_levels(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    """A function's own nodes, one breadth-first level at a time, never entering a nested scope."""
    frontier = tuple(node for node in ast.iter_child_nodes(function) if not isinstance(node, SCOPES))
    while frontier:
        yield from frontier
        frontier = tuple(child for node in frontier for child in ast.iter_child_nodes(node) if not isinstance(child, SCOPES))


def _own_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.AST, ...]:
    """The nodes of a function's own scope; nested functions and classes are checked as their own scopes."""
    return tuple(_scope_levels(function))


def _creates_container(value: ast.expr) -> bool:
    match value:
        case ast.List() | ast.Dict() | ast.Set() | ast.ListComp() | ast.DictComp() | ast.SetComp():
            return True
        case ast.Call(func=ast.Name(id=name) | ast.Attribute(attr=name)):
            return name in CONTAINERS
        case _:
            return False


def _filled(node: ast.AST) -> str | None:
    """The local name a statement or call grows in place, if it grows one."""
    match node:
        case ast.Call(func=ast.Attribute(value=ast.Name(id=name), attr=method)) if method in FILLING:
            return name
        case ast.Assign(targets=[ast.Subscript(value=ast.Name(id=name)), *_]) | ast.AugAssign(target=ast.Subscript(value=ast.Name(id=name))):
            return name
        case ast.AugAssign(target=ast.Name(id=name), value=ast.List() | ast.ListComp() | ast.Tuple()):
            return name
        case _:
            return None


def _fills(loop: ast.AST, own: frozenset[int]) -> Iterator[str]:
    """The names a loop grows in place within its own function."""
    return (name for node in ast.walk(loop) if id(node) in own and (name := _filled(node)) is not None)


def loop_accumulations(function: ast.FunctionDef | ast.AsyncFunctionDef, module: str, declaration: str) -> Iterator[Finding]:
    """A local container created in the function and filled inside one of its loops."""
    nodes = _own_nodes(function)
    grown = frozenset(name for node in nodes if (name := _filled(node)) is not None)
    if not grown:
        return
    created = grown & frozenset(
        target.id
        for node in nodes
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None and _creates_container(node.value)
        for target in (node.targets if isinstance(node, ast.Assign) else (node.target,))
        if isinstance(target, ast.Name)
    )
    if not created:
        return
    own = frozenset(map(id, nodes))
    filled = frozendict(
        (name, loop.lineno)
        for loop in reversed(tuple(node for node in nodes if isinstance(node, ast.For | ast.AsyncFor | ast.While)))
        for name in _fills(loop, own)
        if name in created
    )
    detail = "Build the collection with a comprehension, generator or generator function; a loop is for a side effect."
    yield from (Finding("loop-accumulation", module, declaration, name, line, detail) for name, line in sorted(filled.items(), key=_finding_line))


def _finding_line(entry: tuple[str, int]) -> int:
    _, line = entry
    return line


def _self_attributes(target: ast.expr) -> Iterator[str]:
    """The `self` attributes an assignment target binds or deletes, at any depth."""
    return (
        node.attr
        for node in ast.walk(target)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Store | ast.Del)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _targets(node: ast.AST) -> tuple[ast.expr, ...]:
    match node:
        case ast.Assign(targets=targets) | ast.Delete(targets=targets):
            return tuple(targets)
        case ast.AugAssign(target=target) | ast.AnnAssign(target=target):
            return (target,)
        case _:
            return ()


COMPUTED: Final = (
    ast.Call,
    ast.Await,
    ast.Lambda,
    ast.NamedExpr,
    ast.List,
    ast.Dict,
    ast.Set,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
    ast.GeneratorExp,
)
"""Expressions that build something new: an `__init__` holding one makes or owns state, not just inputs."""


def _stored(statement: ast.stmt) -> frozenset[str] | None:
    """The attributes a statement stores from its inputs, or None if it does anything else."""
    match statement:
        case ast.Expr(value=ast.Constant(value=str())):
            return frozenset()
        case ast.Assign(targets=[target], value=value) | ast.AnnAssign(target=target, value=ast.expr() as value):
            pass
        case _:
            return None
    names = target.elts if isinstance(target, ast.Tuple) else (target,)
    stored = tuple(name.attr for name in names if isinstance(name, ast.Attribute) and isinstance(name.value, ast.Name) and name.value.id == "self")
    built = any(isinstance(node, COMPUTED) or (isinstance(node, ast.Name) and node.id == "self") for node in ast.walk(value))
    return frozenset(stored) if len(stored) == len(names) and not built else None


def _record(node: ast.ClassDef) -> frozenset[str] | None:
    """The attributes of a class that could be a frozen dataclass: no base or decorator,
    an `__init__` that only stores its inputs, and no other method rebinding an attribute."""
    if node.bases or node.keywords or node.decorator_list:
        return None
    methods = tuple(item for item in node.body if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef))
    init = next((method for method in methods if method.name == "__init__"), None)
    if init is None or any(
        next(_self_attributes(target), None) is not None
        for method in methods
        if method is not init
        for child in ast.walk(method)
        for target in _targets(child)
    ):
        return None
    stored = tuple(_stored(statement) for statement in init.body)
    return frozenset[str]().union(*(item for item in stored if item is not None)) if all(item is not None for item in stored) else None


def records(tree: ast.AST, module: str, declaration: str = "") -> Iterator[Candidate]:
    """Plain classes that only hold their inputs, which a frozen, slotted dataclass would model."""
    for child in ast.iter_child_nodes(tree):
        match child:
            case ast.ClassDef(name=name):
                inner = ".".join(part for part in (declaration, name) if part)
                if (attributes := _record(child)) is not None:
                    detail = "A class that only holds its inputs is a frozen, slotted dataclass, unless a protocol needs writable attributes."
                    yield Candidate(Finding("plain-record", module, inner, name, child.lineno, detail), attributes)
                yield from records(child, module, inner)
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                yield from records(child, module, ".".join(part for part in (declaration, name) if part))
            case _:
                yield from records(child, module, declaration)


def assigned(tree: ast.AST) -> frozenset[str]:
    """Attribute names assigned or deleted through any receiver but `self`: writes from outside an owner."""
    return frozenset(
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Store | ast.Del)
        and not (isinstance(node.value, ast.Name) and node.value.id == "self")
    )


def _static_import(call: ast.Call) -> bool:
    """A dynamic import of a literal absolute module name, which the keyboard graph can follow."""
    match call.args:
        case [ast.Constant(value=str() as target), *_]:
            return not target.startswith(".") and not any(keyword.arg == "level" for keyword in call.keywords)
        case _:
            return False


def observation(source: Source, cache: Cache | None) -> Observation:
    key = cache.key("architecture", source) if cache is not None else ""
    if cache is not None and (saved := cache.read(key, OBSERVATION)) is not None:
        return saved
    tree = parse(source)
    module = module_name(source.name)
    aliases = import_aliases(tree)
    dynamic = tuple(
        Finding(
            "keyboard-import",
            module,
            "",
            ast.unparse(node),
            node.lineno,
            "Keyboard dependencies require statically resolvable absolute import targets.",
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and call_name(node.func, aliases) in DYNAMIC_IMPORTS and not _static_import(node)
    )
    result = Observation(
        (*_declarations(tree, module), *value_shapes(tree, module)),
        dynamic,
        tuple(records(tree, module)),
        assigned(tree),
        tuple(definitions(tree.body, module)),
        references(tree),
    )
    if cache is not None:
        cache.write(key, result, OBSERVATION)
    return result


UNUSED: Final = "Delete it: no production code refers to it."
TESTS_ONLY: Final = "Only tests refer to it. Delete it with the tests that serve it, or move a test tool into tests/."
TEXT_REFERENCES: Final = (".cmd", ".ps1", ".js")
"""Tracked text that can name a Python definition: launch scripts and page scripts."""
_ANNOTATION: Final = re.compile(r"[\w.\[\]]+(?:(?:, | \| )[\w.\[\]]+)*")
"""A string that could be a forward reference or a dotted name, as opposed to prose."""


def _overrides(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A method whose caller is the base class it overrides, such as Qt or the SDK."""
    return any(
        isinstance(decorator, ast.Name | ast.Attribute) and ast.unparse(decorator).endswith("override") for decorator in function.decorator_list
    )


def _defined(module: str, owner: str, name: str, node: ast.stmt) -> Iterator[Definition]:
    if not (name.startswith("__") and name.endswith("__")):
        own = sum(1 for reference in _referenced(node) if reference == name)
        yield Definition(Finding("unused-definition", module, ".".join(part for part in (owner, name) if part), name, node.lineno, UNUSED), own)


def definitions(body: Iterable[ast.stmt], module: str, owner: str = "") -> Iterator[Definition]:
    """Named definitions in a module and its classes: functions, classes, and module-level values and type aliases."""
    for node in body:
        match node:
            case ast.ClassDef(name=name, body=inner):
                yield from _defined(module, owner, name, node)
                yield from definitions(inner, module, ".".join(part for part in (owner, name) if part))
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) if not _overrides(node):
                yield from _defined(module, owner, name, node)
            case ast.TypeAlias(name=ast.Name(id=name)) if not owner:
                yield from _defined(module, owner, name, node)
            case ast.Assign() | ast.AnnAssign() if not owner:
                for target in _targets(node):
                    if isinstance(target, ast.Name):
                        yield from _defined(module, owner, target.id, node)
            case ast.If(body=inner, orelse=other) | ast.Try(body=inner, orelse=other):
                yield from definitions((*inner, *other), module, owner)
            case _:
                pass


def references(tree: ast.AST) -> frozendict[str, int]:
    """How often a module names each name: loads, attributes, imports, keywords, match attributes and annotation strings."""
    return frozendict(Counter(_referenced(tree)))


def _referenced(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        match node:
            case ast.Name(id=name, ctx=ast.Load() | ast.Del()) | ast.Attribute(attr=name, ctx=ast.Load()) | ast.keyword(arg=str() as name):
                yield name
            case ast.alias(name=name):
                yield from name.split(".")
            case ast.MatchClass(kwd_attrs=names):
                yield from names
            case ast.Constant(value=str() as text) if _ANNOTATION.fullmatch(text):
                yield from re.findall(r"\w+", text)
            case _:
                pass


def cached_references(source: Source, cache: Cache | None) -> frozenset[str]:
    key = cache.key("references", source) if cache is not None else ""
    if cache is not None and (saved := cache.read(key, REFERENCES)) is not None:
        return saved
    result = frozenset(references(parse(source)))
    if cache is not None:
        cache.write(key, result, REFERENCES)
    return result


def unused_definitions(observations: Iterable[Observation], production: Mapping[str, int], tests: frozenset[str]) -> Iterator[Finding]:
    """Definitions production never names outside their own bodies; those only tests name say so."""
    for observed in observations:
        for definition in observed.definitions:
            finding = definition.finding
            if production.get(finding.expression, 0) <= definition.own:
                yield replace(finding, detail=TESTS_ONLY) if finding.expression in tests else finding


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
    listed = tuple(_walked(root) if names is None else names)
    sources = python_sources(root, listed)
    configuration = _configuration(root)
    exceptions = configuration.exceptions
    all_source = tuple(Source(name, (root / name).read_text(encoding="utf-8")) for name in sources)
    loaded = tuple(source for source in all_source if not source.name.startswith("tests/"))
    observations = {module_name(source.name): observation(source, cache) for source in loaded}
    imported_by = {module_name(source.name): dependencies(source.name, source.text, cache=cache) for source in loaded}
    graph = {module: imported & observations.keys() for module, imported in imported_by.items()}
    texts = (name for name in listed if name.endswith(TEXT_REFERENCES) and not name.startswith("tests/") and (root / name).is_file())
    production = sum(
        (Counter(observed.referenced) for observed in observations.values()),
        Counter(word for name in texts for word in re.findall(r"[A-Za-z_]\w*", (root / name).read_text(encoding="utf-8"))),
    )
    tested = frozenset[str]().union(*(cached_references(source, cache) for source in all_source if source.name.startswith("tests/")))
    # Keyboard routes stop at the first application module they reach.
    keyboard_routes = _routes(graph, (module for module in sorted(graph) if _within(module, "miryoku")), _keyboard)
    # A class whose attribute another owner assigns (`calls.current = ...`) holds changing state.
    written = frozenset[str]().union(*(observed.assigned for observed in observations.values()))
    findings = (
        *(finding for observed in observations.values() for finding in observed.declarations),
        *(record.finding for observed in observations.values() for record in observed.records if record.attributes.isdisjoint(written)),
        *(finding for source in all_source for finding in cached_testing_dependencies(source, cache)),
        *(
            finding
            for route in keyboard_routes
            for finding in (
                observations[route[-1]].dynamic_imports
                if _keyboard(route[-1])
                else (Finding("keyboard-isolation", route[0], "", "", 0, " → ".join(route)),)
            )
        ),
        *contract_isolation(imported_by),
        *process_isolation(imported_by),
        *unused_definitions(observations.values(), production, tested),
    )
    accepted = tuple(exception for exception in exceptions if any(exception.matches(finding) for finding in findings))
    failures = (
        *(finding for finding in findings if not any(exception.matches(finding) for exception in accepted)),
        *(
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
        ),
    )
    return Report(sources, failures, accepted)
