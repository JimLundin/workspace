"""Declaration rules: frozen, slotted records without kind fields or mutable fields, immutable parameters, no reflection."""

import ast
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from functools import reduce
from typing import Final

from scripts.policy import Finding, parameters, qualified
from scripts.source_analysis import call_name

REFLECTION = frozenset({"getattr", "hasattr", "setattr", "delattr"})
REFLECTION_CALLS = REFLECTION | {"builtins." + name for name in REFLECTION}
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
class Scope:
    """Where a node sits: its module, the declaration that holds it, and the names its scope imports."""

    module: str
    declaration: str
    aliases: frozendict[str, str]

    def finding(self, rule: str, expression: str, line: int, detail: str) -> Finding:
        return Finding(rule, self.module, self.declaration, expression, line, detail)

    def member(self, name: str) -> Scope:
        """The scope of one of the declaration's fields or parameters, named after it as `Record.field`."""
        return replace(self, declaration=self.declaration + "." + name)


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


def _mutable(annotation: ast.expr, aliases: Mapping[str, str]) -> bool:
    """An annotation that names a concrete mutable collection anywhere inside it."""
    return any(call_name(node, aliases) in MUTABLE_TYPES for node in ast.walk(annotation))


def _true(flag: ast.expr | None) -> bool:
    match flag:
        case ast.Constant(value=True):
            return True
        case _:
            return False


def _annotated(body: Iterable[ast.stmt]) -> Iterator[ast.AnnAssign]:
    """The fields a class body annotates under a plain name."""
    return (statement for statement in body if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name))


def _decorator_call(decorator: ast.expr) -> tuple[ast.expr, frozendict[str | None, ast.expr]]:
    """The function a decorator names, and the keywords it is called with, if it is called."""
    match decorator:
        case ast.Call(func=function, keywords=keywords):
            return function, frozendict({keyword.arg: keyword.value for keyword in keywords})
        case _:
            return decorator, frozendict()


def _kind_fields(fields: Iterable[ast.stmt], scope: Scope) -> Iterator[Finding]:
    detail = "Give each kind its own type and tag it with one constant Literal, or name the attribute for what it is."
    return (
        scope.member("kind").finding("kind-field", ast.unparse(field.annotation), field.lineno, detail)
        for field in _annotated(fields)
        if ast.unparse(field.target) == "kind" and not _constant_tag(field.annotation, scope.aliases)
    )


def _mutable_fields(fields: Iterable[ast.stmt], scope: Scope) -> Iterator[Finding]:
    """A frozen record's concrete mutable fields: each needs its own declared exception, where a mutable owner has one state exception."""
    detail = "Frozen records must not contain concrete mutable collections without an exact necessity."
    return (
        scope.member(ast.unparse(field.target)).finding("mutable-field", ast.unparse(field.annotation), field.lineno, detail)
        for field in _annotated(fields)
        if _mutable(field.annotation, scope.aliases)
    )


def _dataclass(node: ast.ClassDef, scope: Scope) -> Iterator[Finding]:
    """Each dataclass decorator's record: no kind field, frozen and slotted, and no mutable field once frozen."""
    for decorator in node.decorator_list:
        function, flags = _decorator_call(decorator)
        if call_name(function, scope.aliases) != "dataclasses.dataclass":
            continue
        yield from _kind_fields(node.body, scope)
        frozen = _true(flags.get("frozen"))
        if not (frozen and _true(flags.get("slots"))):
            detail = "Data records require frozen=True and slots=True, or an exact necessary-mutation exception."
            yield scope.finding("immutable-data", node.name, node.lineno, detail)
        if frozen:
            yield from _mutable_fields(node.body, scope)


def _mutable_parameters(arguments: ast.arguments, scope: Scope) -> Iterator[Finding]:
    detail = (
        "Take an immutable type (a tuple, frozendict, frozen record, or Sequence, Mapping, Set or Iterable), "
        "or declare the exact signature a dependency dictates."
    )
    return (
        scope.member(parameter.arg).finding("mutable-parameter", ast.unparse(parameter.annotation), parameter.lineno, detail)
        for parameter in parameters(arguments)
        if parameter.annotation is not None and _mutable(parameter.annotation, scope.aliases)
    )


def _overridden(function: ast.FunctionDef | ast.AsyncFunctionDef, aliases: Mapping[str, str]) -> bool:
    return any(call_name(decorator, aliases) in OVERRIDES for decorator in function.decorator_list)


def _findings(tree: ast.AST, scope: Scope) -> Iterator[Finding]:
    match tree:
        case ast.ClassDef():
            yield from _dataclass(tree, scope)
        case ast.FunctionDef() | ast.AsyncFunctionDef() if not _overridden(tree, scope.aliases):
            yield from _mutable_parameters(tree.args, scope)
        case ast.Call(func=function) if call_name(function, scope.aliases) in REFLECTION_CALLS:
            detail = "Use typed direct attributes, or declare an exact native/inspection exception."
            yield scope.finding("explicit-attributes", ast.unparse(tree), tree.lineno, detail)
        case _:
            pass


def _entered(tree: ast.AST, outer: Scope) -> Scope:
    """The scope inside tree: a class or function names a declaration, and each lexical scope binds its own imports.

    Aliases are copied once per lexical scope, not for every expression; imports
    inside conditional statements still belong to their enclosing scope."""
    match tree:
        case ast.ClassDef(name=name) | ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
            return Scope(outer.module, qualified(outer.declaration, name), _scope_aliases(tree, outer.aliases))
        case ast.Module():
            return Scope(outer.module, outer.declaration, _scope_aliases(tree, outer.aliases))
        case _:
            return outer


def _walk(tree: ast.AST, outer: Scope) -> Iterator[Finding]:
    scope = _entered(tree, outer)
    yield from _findings(tree, scope)
    for child in ast.iter_child_nodes(tree):
        yield from _walk(child, scope)


def declarations(tree: ast.Module, module: str) -> Iterator[Finding]:
    """Every declaration finding in a module, in source order of the nodes that make them."""
    return _walk(tree, Scope(module, "", frozendict()))
