import ast
from collections.abc import Iterator
from itertools import pairwise
from typing import Final

from scripts.policy import Finding
from scripts.source_analysis import targets

CONTAINERS: Final = frozenset(
    {
        "list",
        "dict",
        "set",
        "bytearray",
        "deque",
        "defaultdict",
        "Counter",
        "OrderedDict",
    }
)
"""Constructors of the mutable containers a function might fill in a loop."""
FILLING: Final = frozenset(
    {
        "append",
        "extend",
        "add",
        "update",
        "insert",
        "setdefault",
        "appendleft",
        "extendleft",
    }
)
"""Methods that grow a container in place."""


SCOPES: Final = (
    ast.ClassDef,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
)


def _scope_levels(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Iterator[ast.AST]:
    frontier = tuple(
        node
        for node in ast.iter_child_nodes(function)
        if not isinstance(node, SCOPES)
    )
    while frontier:
        yield from frontier
        frontier = tuple(
            child
            for node in frontier
            for child in ast.iter_child_nodes(node)
            if not isinstance(child, SCOPES)
        )


def _own_nodes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[ast.AST, ...]:
    return tuple(_scope_levels(function))


def _creates_container(value: ast.expr) -> bool:
    match value:
        case (
            ast.List()
            | ast.Dict()
            | ast.Set()
            | ast.ListComp()
            | ast.DictComp()
            | ast.SetComp()
        ):
            return True
        case ast.Call(func=ast.Name(id=name) | ast.Attribute(attr=name)):
            return name in CONTAINERS
        case _:
            return False


def _container_targets(node: ast.AST) -> tuple[ast.expr, ...]:
    match node:
        case (
            ast.Assign(value=value) | ast.AnnAssign(value=ast.expr() as value)
        ) if _creates_container(value):
            return targets(node)
        case _:
            return ()


def _created(nodes: tuple[ast.AST, ...]) -> frozenset[str]:
    return frozenset(
        target.id
        for node in nodes
        for target in _container_targets(node)
        if isinstance(target, ast.Name)
    )


def _filled(node: ast.AST) -> str | None:
    match node:
        case ast.Call(
            func=ast.Attribute(value=ast.Name(id=name), attr=method)
        ) if method in FILLING:
            return name
        case (
            ast.Assign(targets=[ast.Subscript(value=ast.Name(id=name)), *_])
            | ast.AugAssign(target=ast.Subscript(value=ast.Name(id=name)))
        ):
            return name
        case ast.AugAssign(
            target=ast.Name(id=name),
            value=ast.List() | ast.ListComp() | ast.Tuple(),
        ):
            return name
        case _:
            return None


def _fills(loop: ast.AST, own: frozenset[int]) -> Iterator[str]:
    return (
        name
        for node in ast.walk(loop)
        if id(node) in own and (name := _filled(node)) is not None
    )


def _loop_fills(
    nodes: tuple[ast.AST, ...], created: frozenset[str]
) -> frozendict[str, int]:
    own = frozenset(map(id, nodes))
    loops = tuple(
        node
        for node in nodes
        if isinstance(node, ast.For | ast.AsyncFor | ast.While)
    )
    return frozendict(
        (name, loop.lineno)
        for loop in reversed(loops)
        for name in _fills(loop, own)
        if name in created
    )


def _finding_line(entry: tuple[str, int]) -> int:
    _, line = entry
    return line


def loop_accumulations(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    module: str,
    declaration: str,
) -> Iterator[Finding]:
    nodes = _own_nodes(function)
    grown = frozenset(
        name for node in nodes if (name := _filled(node)) is not None
    )
    if not grown:
        return
    created = grown & _created(nodes)
    if not created:
        return
    detail = "Build the collection with a comprehension, generator or generator function; a loop is for a side effect."
    filled = _loop_fills(nodes, created)
    yield from (
        Finding("loop-accumulation", module, declaration, name, line, detail)
        for name, line in sorted(filled.items(), key=_finding_line)
    )


STATE_WRITES: Final = frozenset({"set", "update"})
"""A `Cell`'s two ways to replace its value."""


def _written(statement: ast.stmt) -> str | None:
    match statement:
        case ast.Expr(
            value=ast.Call(
                func=ast.Attribute(value=ast.Attribute() as cell, attr=method)
            )
        ) if method in STATE_WRITES:
            return ast.unparse(cell)
        case _:
            return None


def _blocks(node: ast.AST) -> Iterator[list[ast.stmt]]:
    match node:
        case (
            ast.FunctionDef(body=body)
            | ast.AsyncFunctionDef(body=body)
            | ast.With(body=body)
            | ast.AsyncWith(body=body)
        ):
            yield body
        case ast.ExceptHandler(body=body) | ast.match_case(body=body):
            yield body
        case (
            ast.If(body=body, orelse=orelse)
            | ast.For(body=body, orelse=orelse)
            | ast.AsyncFor(body=body, orelse=orelse)
            | ast.While(body=body, orelse=orelse)
        ):
            yield body
            yield orelse
        case (
            ast.Try(body=body, orelse=orelse, finalbody=finalbody)
            | ast.TryStar(body=body, orelse=orelse, finalbody=finalbody)
        ):
            yield body
            yield orelse
            yield finalbody
        case _:
            pass


def _field_read(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = [
        statement
        for statement in function.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
        )
    ]
    match body:
        case [
            ast.Return(
                value=ast.Attribute(
                    value=ast.Call(
                        func=ast.Attribute(value=ast.Attribute(), attr="get"),
                        args=[],
                    )
                )
            )
        ]:
            return True
        case _:
            return False


def _mirrors(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if not function.name.startswith("_"):
        return False
    decorated = any(
        isinstance(decorator, ast.Name) and decorator.id == "property"
        for decorator in function.decorator_list
    )
    return decorated and _field_read(function)


def _piecemeal(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    module: str,
    declaration: str,
) -> Iterator[Finding]:
    detail = "Change several fields in one replace(...), reading the state once; a frozen record is not a set of attributes."
    for statements in (
        block
        for node in (function, *_own_nodes(function))
        for block in _blocks(node)
    ):
        for first, second in pairwise(statements):
            if (
                written := _written(second)
            ) is not None and written == _written(first):
                yield Finding(
                    "piecemeal-state",
                    module,
                    declaration,
                    written,
                    second.lineno,
                    detail,
                )


def state_writes(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    module: str,
    declaration: str,
) -> Iterator[Finding]:
    yield from _piecemeal(function, module, declaration)
    if _mirrors(function):
        detail = "Read the state once (state = self._state.get()) where it is needed, rather than through a private property per field."
        yield Finding(
            "mirrored-state",
            module,
            declaration,
            function.name,
            function.lineno,
            detail,
        )
