"""Whole-tree usage rules: unused definitions, duplicated function structure and Win32 functions declared twice."""

import ast
import copy
import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Final, override

from pydantic import TypeAdapter

from scripts.policy import Finding
from scripts.source_analysis import Cache, Source, parse, qualified, targets

REFERENCES = TypeAdapter[frozenset[str]](frozenset[str])


@dataclass(frozen=True, slots=True)
class Definition:
    """A named definition, unused until a reference outside its own body names it."""

    finding: Finding
    own: int
    """How often the definition names itself, as a recursive function or a class's own annotations do."""


@dataclass(frozen=True, slots=True)
class Shape:
    """A function's structure with its names, attributes and constants erased, which a copy shares."""

    finding: Finding
    digest: str


UNUSED: Final = "Delete it: no production code refers to it."
TESTS_ONLY: Final = "Only tests refer to it. Delete it with the tests that serve it, or move a test tool into tests/."
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
        yield Definition(Finding("unused-definition", module, qualified(owner, name), name, node.lineno, UNUSED), own)


def definitions(body: Iterable[ast.stmt], module: str, owner: str = "") -> Iterator[Definition]:
    """Named definitions in a module and its classes: functions, classes, and module-level values and type aliases."""
    for node in body:
        match node:
            case ast.ClassDef(name=name, body=inner):
                yield from _defined(module, owner, name, node)
                yield from definitions(inner, module, qualified(owner, name))
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) if not _overrides(node):
                yield from _defined(module, owner, name, node)
            case ast.TypeAlias(name=ast.Name(id=name)) if not owner:
                yield from _defined(module, owner, name, node)
            case ast.Assign() | ast.AnnAssign() if not owner:
                for target in targets(node):
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


def unused_definitions(found: Iterable[Definition], production: Mapping[str, int], tests: frozenset[str]) -> Iterator[Finding]:
    """Definitions production never names outside their own bodies; those only tests name say so."""
    for definition in found:
        finding = definition.finding
        if production.get(finding.expression, 0) <= definition.own:
            yield replace(finding, detail=TESTS_ONLY) if finding.expression in tests else finding


SHAPE_NODES: Final = 40
"""The smallest function body, in syntax nodes, whose copy the review reports; below it, shapes recur by chance."""


class _Erased(ast.NodeTransformer):
    """Erase what a copy renames: identifiers, attributes, arguments, annotations and constant values."""

    @override
    def visit_Name(self, node: ast.Name) -> ast.Name:
        return ast.Name(id="_", ctx=node.ctx)

    @override
    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:
        return ast.Attribute(value=self.visit(node.value), attr="_", ctx=node.ctx)

    @override
    def visit_arg(self, node: ast.arg) -> ast.arg:
        return ast.arg(arg="_")

    @override
    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        return ast.Constant(value=type(node.value).__name__)


def _digest(function: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    body = ast.Module(body=[_Erased().visit(copy.deepcopy(statement)) for statement in function.body], type_ignores=[])
    return hashlib.sha256((type(function).__name__ + ast.dump(_Erased().visit(copy.deepcopy(function.args))) + ast.dump(body)).encode()).hexdigest()


def shapes(tree: ast.AST, module: str, declaration: str = "") -> Iterator[Shape]:
    """Every function of at least SHAPE_NODES nodes, with its erased structure."""
    for child in ast.iter_child_nodes(tree):
        match child:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                inner = qualified(declaration, name)
                if sum(1 for statement in child.body for _ in ast.walk(statement)) >= SHAPE_NODES:
                    detail = "Same structure as another function; keep one and give it the parameters the copies differ by."
                    yield Shape(Finding("duplicate-code", module, inner, name, child.lineno, detail), _digest(child))
                yield from shapes(child, module, inner)
            case ast.ClassDef(name=name):
                yield from shapes(child, module, qualified(declaration, name))
            case _:
                yield from shapes(child, module, declaration)


def duplicates(found: Iterable[Shape]) -> Iterator[Finding]:
    """Each function whose erased structure another function shares, naming the first of its copies."""
    shaped = tuple(found)
    copies = Counter(shape.digest for shape in shaped)
    first = {shape.digest: shape.finding for shape in reversed(shaped)}
    for shape in shaped:
        if copies[shape.digest] > 1 and (original := first[shape.digest]) != shape.finding:
            yield replace(shape.finding, detail=f"{shape.finding.detail} First copy: {original.module}.{original.declaration}.")


DECLARES: Final = frozenset({"fn"})
"""winapi._core's foreign-function declarations: `fn(user32, "GetForegroundWindow", HWND)`."""


def natives(tree: ast.AST, module: str) -> Iterator[Finding]:
    for node in ast.walk(tree):
        match node:
            case ast.Call(func=ast.Name(id=name), args=[_, ast.Constant(value=str() as export), *_]) if name in DECLARES:
                detail = "Declare a Win32 function once, in winapi._core when more than one module calls it."
                yield Finding("native-redeclaration", module, export, export, node.lineno, detail)
            case _:
                pass


def redeclarations(declared: Iterable[Finding]) -> Iterator[Finding]:
    """Each declaration of an export that another module declares as well."""
    exports = tuple(declared)
    modules = Counter(export for export, _ in frozenset((finding.expression, finding.module) for finding in exports))
    return (finding for finding in exports if modules[finding.expression] > 1)
