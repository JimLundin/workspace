"""The ban on patch and mock frameworks, in production and test source alike."""

import ast
from collections.abc import Iterator, Mapping, Sequence

from pydantic import TypeAdapter

from scripts.policy import Finding
from scripts.source_analysis import DYNAMIC_IMPORTS, Cache, Source, call_name, import_aliases, module_name, parse

FINDINGS = TypeAdapter[tuple[Finding, ...]](tuple[Finding, ...])
FORBIDDEN_TEST_TOOLS = frozenset({"unittest.mock", "mock", "pytest_mock", "mockito", "pytest.MonkeyPatch"})
FIXTURES = frozenset({"monkeypatch", "mocker"})
"""The pytest fixtures that patch."""


def _forbidden(name: str) -> bool:
    """A forbidden tool, or anything inside one."""
    return any(name == tool or name.startswith(tool + ".") for tool in FORBIDDEN_TEST_TOOLS)


def _called_seam(call: str, args: Sequence[ast.expr]) -> str:
    """The forbidden tool a call loads or uses, or nothing."""
    if call in DYNAMIC_IMPORTS:
        match args:
            case [ast.Constant(value=str() as module), *_] if module in FORBIDDEN_TEST_TOOLS:
                return module
            case _:
                return ""
    return call if _forbidden(call) or call.partition(".")[0] in FIXTURES else ""


def _seam(node: ast.AST, aliases: Mapping[str, str]) -> str:
    """The forbidden tool a node imports, calls or takes as a fixture, or nothing."""
    match node:
        case ast.Import(names=names):
            return next((item.name for item in names if _forbidden(item.name)), "")
        case ast.ImportFrom(module=str() as module, names=names):
            return next((item for item in (module, *(module + "." + item.name for item in names)) if _forbidden(item)), "")
        case ast.Call(func=function, args=args):
            return _called_seam(call_name(function, aliases), args)
        case ast.arg(arg=name) if name in FIXTURES:
            return name
        case _:
            return ""


def testing_dependencies(source: Source) -> Iterator[Finding]:
    """Reject framework replacement seams in production and test source alike."""
    tree = parse(source)
    aliases = import_aliases(tree)
    detail = "Patches and mocks are disallowed; pass explicit dependencies or use real local resources: "
    for node in ast.walk(tree):
        match node:
            case ast.stmt(lineno=line) | ast.expr(lineno=line) | ast.arg(lineno=line) if target := _seam(node, aliases):
                yield Finding("testing-dependencies", module_name(source.name), "", ast.unparse(node), line, detail + target)
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
