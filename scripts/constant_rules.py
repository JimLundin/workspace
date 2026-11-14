"""Constants and tables across modules: constants shared only out of data modules, and enums that hide another shape."""

import ast
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from scripts.policy import Finding, targets, within_any
from scripts.source_analysis import Source, module_name

CONSTANT: Final = re.compile(r"[A-Z][A-Z0-9_]*")
"""A module-level constant's name; a leading underscore keeps one private."""


def _sentinel(statement: ast.stmt) -> bool:
    """`NAME = sentinel("NAME")`: a marker that is its own type, shared as freely as a class."""
    match statement:
        case ast.Assign(value=ast.Call(func=ast.Name(id="sentinel"))) | ast.AnnAssign(value=ast.Call(func=ast.Name(id="sentinel"))):
            return True
        case _:
            return False


def _constants(tree: ast.Module) -> frozenset[str]:
    """The constants a module declares at its top level; a sentinel is a type, not a constant."""
    assigned = (
        target
        for statement in tree.body
        if isinstance(statement, ast.Assign | ast.AnnAssign) and not _sentinel(statement)
        for target in targets(statement)
    )
    names = (name for target in assigned for name in (target.elts if isinstance(target, ast.Tuple) else (target,)) if isinstance(name, ast.Name))
    return frozenset(name.id for name in names if CONSTANT.fullmatch(name.id))


def _declarations_only(tree: ast.Module) -> bool:
    """A data module: a docstring, imports and declarations, nothing that runs or defines behaviour."""
    for statement in tree.body:
        match statement:
            case ast.Import() | ast.ImportFrom() | ast.Assign() | ast.AnnAssign() | ast.Expr(value=ast.Constant(value=str())):
                pass
            case _:
                return False
    return True


@dataclass(frozen=True, slots=True)
class Shared:
    """What the reviewed modules share: their names, the constants each declares, and which are data modules."""

    modules: frozenset[str]
    constants: frozendict[str, frozenset[str]]
    data: frozenset[str]

    def declared(self, module: str) -> frozenset[str]:
        return self.constants.get(module, frozenset())


def shared_constants(sources: Iterable[Source], scope: Sequence[str]) -> Iterator[Finding]:
    """Constants cross a module boundary only as `module.NAME`, and only out of a data module.

    A bare name always means the module's own constant; another module's
    behaviour owns its constants, so it shares them as an enum, a function or a
    type's property instead."""
    trees = {module_name(source.name): ast.parse(source.text) for source in sources}
    shared = Shared(
        frozenset(trees),
        frozendict({module: _constants(tree) for module, tree in trees.items()}),
        frozenset(module for module, tree in trees.items() if _declarations_only(tree)),
    )
    for module, tree in sorted(trees.items()):
        if within_any(module, scope):
            yield from _constant_reads(module, tree, shared)


def _imported_name(node: ast.Import | ast.ImportFrom, alias: ast.alias) -> str:
    return alias.name if isinstance(node, ast.Import) else f"{node.module}.{alias.name}"


def _constant_imports(module: str, imported: Iterable[ast.Import | ast.ImportFrom], shared: Shared) -> Iterator[Finding]:
    """`from x import NAME` of another module's constant, which reads as this module's own."""
    for node in imported:
        match node:
            case ast.ImportFrom(module=str() as base, names=names):
                yield from (
                    Finding(
                        "constant-import",
                        module,
                        "",
                        f"{base}.{alias.name}",
                        node.lineno,
                        f"Import the module and read {base.rsplit('.', 1)[-1]}.{alias.name}: a bare name is this module's own.",
                    )
                    for alias in names
                    if alias.name in shared.declared(base)
                )
            case _:
                pass


def _shared_constant(read: ast.Attribute, bound: Mapping[str, str], shared: Shared) -> str | None:
    """The constant `module.NAME` reads out of a module with behaviour, if it reads one."""
    match read.value:
        case ast.Name(id=name) if (source := bound.get(name)) is not None and source not in shared.data:
            return f"{source}.{read.attr}" if read.attr in shared.declared(source) else None
        case _:
            return None


def _constant_reads(module: str, tree: ast.Module, shared: Shared) -> Iterator[Finding]:
    imported = tuple(node for node in ast.walk(tree) if isinstance(node, ast.Import | ast.ImportFrom))
    yield from _constant_imports(module, imported, shared)
    bound = frozendict(
        (alias.asname or alias.name, name)
        for node in imported
        for alias in node.names
        if (name := _imported_name(node, alias)) in shared.modules or isinstance(node, ast.Import)
    )
    detail = "Only a declarations-only module shares constants: move it to one, or share it as an enum, a function or a property."
    reads = (node for node in ast.walk(tree) if isinstance(node, ast.Attribute))
    yield from (
        Finding("shared-constant", module, "", constant, read.lineno, detail)
        for read in reads
        if (constant := _shared_constant(read, bound, shared)) is not None
    )


ENUM_BASES: Final = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"})


def _enum_members(definition: ast.ClassDef) -> tuple[str, ...] | None:
    """The members an enum declares, or None for a class that isn't an enum."""
    bases = frozenset(base.id if isinstance(base, ast.Name) else base.attr for base in definition.bases if isinstance(base, ast.Name | ast.Attribute))
    if bases.isdisjoint(ENUM_BASES):
        return None
    assigned = (target for statement in definition.body if isinstance(statement, ast.Assign | ast.AnnAssign) for target in targets(statement))
    return tuple(target.id for target in assigned if isinstance(target, ast.Name) and not target.id.startswith("_"))


def _member_of(node: ast.expr | None, enums: frozenset[str]) -> bool:
    return isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in enums


def _keyed_by(value: ast.expr, enums: frozenset[str]) -> bool:
    """A table literal keyed by one of the module's enums: `{E.A: ..., E.B: ...}`, `frozenset({E.A, E.B})`, or one built over `E`."""
    match value:
        case ast.Call(func=ast.Name(id="frozendict" | "frozenset" | "dict" | "set"), args=[inner]):
            return _keyed_by(inner, enums)
        case ast.Dict(keys=keys):
            return len(keys) > 1 and all(_member_of(key, enums) for key in keys)
        case ast.Set(elts=elements):
            return len(elements) > 1 and all(_member_of(item, enums) for item in elements)
        case (
            ast.DictComp(generators=[ast.comprehension(iter=ast.Name(id=name)), *_])
            | ast.SetComp(generators=[ast.comprehension(iter=ast.Name(id=name)), *_])
        ):
            return name in enums
        case _:
            return False


def enum_shapes(sources: Iterable[Source]) -> Iterator[Finding]:
    """Enums that hide another shape: one member is a sentinel, and a table beside an enum is its members' values."""
    for source in sources:
        module, tree = module_name(source.name), ast.parse(source.text)
        enums: frozendict[str, tuple[str, ...]] = frozendict(
            (node.name, members) for node in tree.body if isinstance(node, ast.ClassDef) and (members := _enum_members(node)) is not None
        )
        for node in tree.body:
            match node:
                case ast.ClassDef(name=name) if len(enums.get(name, ())) == 1:
                    detail = 'An enum with one member is a marker: use sentinel("NAME"), or None for plain absence.'
                    yield Finding("single-member-enum", module, name, name, node.lineno, detail)
                case ast.Assign(value=value) | ast.AnnAssign(value=ast.expr() as value) if _keyed_by(value, frozenset(enums)):
                    names = ", ".join(ast.unparse(target) for target in targets(node))
                    detail = "Put each member's value on the member (an enum whose values are records), not in a table beside the enum."
                    yield Finding("member-table", module, names, names, node.lineno, detail)
                case _:
                    pass
