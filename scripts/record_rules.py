"""Plain classes that only hold their inputs, which a frozen, slotted dataclass would model."""

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from scripts.policy import Finding
from scripts.source_analysis import qualified, targets


@dataclass(frozen=True, slots=True)
class Candidate:
    """A plain class whose `__init__` only stores its inputs, and the attributes it stores."""

    finding: Finding
    attributes: frozenset[str]


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


def _rebinds(methods: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...], init: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether a method besides `__init__` assigns or deletes an attribute of `self`."""
    return any(
        next(_self_attributes(target), None) is not None
        for method in methods
        if method is not init
        for child in ast.walk(method)
        for target in targets(child)
    )


def _held(init: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str] | None:
    """The attributes an `__init__` stores, if all it does is store its inputs."""
    stored = tuple(_stored(statement) for statement in init.body)
    if any(item is None for item in stored):
        return None
    return frozenset[str]().union(*(item for item in stored if item is not None))


def _record(node: ast.ClassDef) -> frozenset[str] | None:
    """The attributes of a class that could be a frozen dataclass: no base or decorator,
    an `__init__` that only stores its inputs, and no other method rebinding an attribute."""
    if any((node.bases, node.keywords, node.decorator_list)):
        return None
    methods = tuple(item for item in node.body if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef))
    init = next((method for method in methods if method.name == "__init__"), None)
    if init is None or _rebinds(methods, init):
        return None
    return _held(init)


def records(tree: ast.AST, module: str, declaration: str = "") -> Iterator[Candidate]:
    """Plain classes that only hold their inputs, which a frozen, slotted dataclass would model."""
    for child in ast.iter_child_nodes(tree):
        match child:
            case ast.ClassDef(name=name):
                inner = qualified(declaration, name)
                if (attributes := _record(child)) is not None:
                    detail = "A class that only holds its inputs is a frozen, slotted dataclass, unless a protocol needs writable attributes."
                    yield Candidate(Finding("plain-record", module, inner, name, child.lineno, detail), attributes)
                yield from records(child, module, inner)
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                yield from records(child, module, qualified(declaration, name))
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
