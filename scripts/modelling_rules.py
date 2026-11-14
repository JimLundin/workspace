"""Modelling rules: enum translations as tables, named types for numeric tuples, scripts in .js files."""

import ast
import re
from collections.abc import Iterable, Iterator
from typing import Final

from scripts.policy import Finding
from scripts.scope_rules import loop_accumulations, state_writes
from scripts.source_analysis import parameters, qualified


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
    """A case that names only values: enum members or literals."""
    match pattern:
        case ast.MatchValue(value=ast.Attribute() | ast.Constant()):
            return True
        case ast.MatchOr(patterns=patterns):
            return all(_members(item) for item in patterns)
        case _:
            return False


def _wildcard(case: ast.match_case) -> bool:
    return isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None


def _gives_constant(case: ast.match_case, bound: frozenset[str]) -> bool:
    """A case whose whole body returns or assigns one constant."""
    match case.body:
        case [ast.Return(value=ast.expr() as value)] | [ast.Assign(value=value)]:
            return _constant(value, bound)
        case _:
            return False


def _bound(function: ast.FunctionDef | ast.AsyncFunctionDef | None) -> frozenset[str]:
    """The function's parameters and every name it assigns: values that vary between calls."""
    if function is None:
        return frozenset()
    stored = (node.id for node in ast.walk(function) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store))
    return frozenset((*(item.arg for item in parameters(function.args)), *stored))


def _numeric(items: Iterable[ast.expr]) -> bool:
    return all(isinstance(item, ast.Name) and item.id in ("int", "float") for item in items)


def _translation(cases: Iterable[ast.match_case], function: ast.FunctionDef | ast.AsyncFunctionDef | None) -> bool:
    """A `match` that only maps enum members to constants: at least two cases besides a wildcard, each naming members, unguarded, giving one constant.

    The function's assigned names are collected only once every pattern names members, the rare case that needs them."""
    named = tuple(case for case in cases if not _wildcard(case))
    if len(named) < 2 or not all(_members(case.pattern) and case.guard is None for case in named):
        return False
    bound = _bound(function)
    return all(_gives_constant(case, bound) for case in named)


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
                inner = qualified(declaration, name)
                yield from loop_accumulations(child, module, inner)
                yield from state_writes(child, module, inner)
                yield from value_shapes(child, module, inner, child)
                continue
            case ast.ClassDef(name=name):
                yield from value_shapes(child, module, qualified(declaration, name), function)
                continue
            case ast.Match(subject=subject, cases=cases) if _translation(cases, function):
                detail = "Translate enum members or Literal values with an every_member or every_literal table, or a frozendict for a partial one."
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
