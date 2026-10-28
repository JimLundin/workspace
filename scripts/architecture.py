"""Source ownership and coding policies, without importing application modules.

The same inventory works in a Git checkout and a deployed source copy. Callers
may supply Git-listed names to bind the review to their checked source snapshot.

Parsing uses private mutable ASTs and traversal worklists: copying the growing
graph at every step would add substantial algorithmic overhead. Only immutable
policy reports leave this owner.
"""

import ast
import os
import tomllib
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import StrictStr, StringConstraints, TypeAdapter

from scripts.source_analysis import Cache, Source, parse

type Text = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]

REFLECTION = frozenset({'getattr', 'hasattr', 'setattr', 'delattr'})
MUTABLE_TYPES = frozenset({'list', 'dict', 'set', 'bytearray', 'collections.deque', 'typing.List', 'typing.Dict', 'typing.Set',
                           'typing.MutableMapping', 'typing.MutableSequence', 'typing.MutableSet',
                           'collections.abc.MutableMapping', 'collections.abc.MutableSequence', 'collections.abc.MutableSet'})


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    module: str
    declaration: str
    expression: str
    line: int
    detail: str

    def describe(self) -> str:
        location = self.module + ('.' + self.declaration if self.declaration else '')
        return f'{self.rule}: {location}:{self.line}: {self.detail}'


@dataclass(frozen=True, slots=True)
class ExceptionSpec:
    rule: Literal['explicit-attributes', 'immutable-data', 'mutable-field']
    module: Text
    declaration: Text
    expression: Text
    reason: Text
    kind: Literal['necessity', 'migration'] = 'necessity'

    def matches(self, finding: Finding) -> bool:
        return (self.rule, self.module, self.declaration, self.expression) == (
            finding.rule, finding.module, finding.declaration, finding.expression)


@dataclass(frozen=True, slots=True)
class Report:
    sources: tuple[str, ...]
    failures: tuple[Finding, ...]
    exceptions: tuple[ExceptionSpec, ...]


@dataclass(frozen=True, slots=True)
class Configuration:
    models: tuple[Text, ...]
    exceptions: tuple[ExceptionSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class Observation:
    declarations: tuple[Finding, ...]
    dynamic_imports: tuple[Finding, ...]


CONFIGURATION = TypeAdapter[Configuration](Configuration)
OBSERVATION = TypeAdapter[Observation](Observation)
DEPENDENCIES = TypeAdapter[frozenset[str]](frozenset[str])


def python_sources(root: Path, names: Iterable[str] | None = None) -> tuple[str, ...]:
    if names is None:
        found: list[str] = []
        for folder, directories, files in os.walk(root):
            directories[:] = sorted(name for name in directories if not name.startswith(('.', '__pycache__')))
            found.extend((Path(folder) / name).relative_to(root).as_posix() for name in files)
        names = found
    return tuple(sorted({name for name in names if name.endswith(('.py', '.pyw'))
                         and not any(part.startswith(('.', '__pycache__')) for part in Path(name).parts)
                         and (root / name).is_file()}))


def module_name(name: str) -> str:
    parts = Path(name).with_suffix('').parts
    return '.'.join(parts[:-1] if parts[-1] == '__init__' else parts)


def _call_name(node: ast.AST, aliases: Mapping[str, str]) -> str:
    match node:
        case ast.Name(id=name):
            return aliases.get(name, name)
        case ast.Attribute(value=value, attr=attribute):
            return _call_name(value, aliases) + '.' + attribute
        case _:
            return ''


def _aliases(tree: ast.AST) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=names):
                result.update({alias.asname or alias.name.split('.')[0]: alias.name if alias.asname else alias.name.split('.')[0]
                               for alias in names})
            case ast.ImportFrom(module=module, level=0, names=names) if module:
                result.update({alias.asname or alias.name: module + '.' + alias.name for alias in names})
            case _:
                pass
    return result


def _imports(name: str, tree: ast.AST) -> frozenset[str]:
    result: set[str] = set()
    aliases = _aliases(tree)
    package = module_name(name).split('.') if name.endswith('/__init__.py') else module_name(name).split('.')[:-1]
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=names):
                result.update(alias.name for alias in names)
            case ast.ImportFrom(module=base, level=level, names=names):
                prefix = '.'.join(package[:len(package) - level + 1]) if level else ''
                target = '.'.join(value for value in (prefix, base) if value)
                result.add(target)
                result.update('.'.join(value for value in (target, alias.name) if value) for alias in names if alias.name != '*')
            case ast.Call(func=function, args=[ast.Constant(value=str(value)), *_]) if _call_name(function, aliases) in (
                    'importlib.import_module', '__import__', 'builtins.__import__'):
                result.add(value)
            case _:
                pass
    # Importing a submodule executes its ancestor package initializers too.
    return frozenset('.'.join(value.split('.')[:index]) for value in result for index in range(1, len(value.split('.')) + 1))


def dependencies(name: str, text: str, *, cache: Cache | None = None) -> frozenset[str]:
    source = Source(name, text)
    key = cache.key('dependencies', source) if cache is not None else ''
    if cache is not None and (saved := cache.read(key, DEPENDENCIES)) is not None:
        return saved
    result = _imports(name, parse(source))
    if cache is not None:
        cache.write(key, result, DEPENDENCIES)
    return result


def _configuration(root: Path) -> tuple[tuple[str, ...], tuple[ExceptionSpec, ...]]:
    match tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8')):
        case {'tool': {'workspace': {'architecture': object() as value}}}:
            configuration = CONFIGURATION.validate_python(value)
        case _:
            raise ValueError('Architecture configuration must contain its named table.')
    exceptions = tuple(replace(entry, expression=ast.unparse(ast.parse(entry.expression, mode='eval').body))
                       for entry in configuration.exceptions)
    keys = tuple((entry.rule, entry.module, entry.declaration, entry.expression) for entry in exceptions)
    if len(frozenset(keys)) != len(keys):
        raise ValueError('Duplicate architecture exception.')
    for entry in exceptions:
        if any('*' in value for value in (entry.module, entry.declaration)):
            raise ValueError('Architecture exceptions require a supported rule and an exact declaration.')
    return configuration.models, exceptions


def _scope_aliases(tree: ast.AST, inherited: Mapping[str, str]) -> dict[str, str]:
    local = dict(inherited)
    pending = list(ast.iter_child_nodes(tree))
    while pending:
        node = pending.pop()
        match node:
            case ast.ClassDef() | ast.FunctionDef() | ast.AsyncFunctionDef():
                continue
            case ast.Import(names=names):
                local.update({alias.asname or alias.name.split('.')[0]: alias.name if alias.asname else alias.name.split('.')[0]
                              for alias in names})
            case ast.ImportFrom(module=base, level=0, names=names) if base:
                local.update({alias.asname or alias.name: base + '.' + alias.name for alias in names})
            case ast.Assign(targets=[ast.Name(id=name)], value=value):
                resolved = _call_name(value, local)
                if resolved in REFLECTION or resolved in {'builtins.' + item for item in REFLECTION}:
                    local[name] = resolved
            case _:
                pass
        pending.extend(ast.iter_child_nodes(node))
    return local


def _declarations(tree: ast.AST, module: str, declaration: str = '',
                  aliases: Mapping[str, str] | None = None) -> Iterator[Finding]:
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
            declaration = '.'.join(part for part in (declaration, name) if part)
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
                if _call_name(function, local) != 'dataclasses.dataclass':
                    continue
                match flags.get('frozen'), flags.get('slots'):
                    case ast.Constant(value=True), ast.Constant(value=True):
                        pass
                    case _:
                        yield Finding('immutable-data', module, declaration, name, tree.lineno,
                                      'Data records require frozen=True and slots=True, or an exact necessary-mutation exception.')
                # A mutable owner has one state exception. Frozen records need
                # a separate declaration for each concrete mutable field.
                match flags.get('frozen'):
                    case ast.Constant(value=True):
                        for field in fields:
                            match field:
                                case ast.AnnAssign(target=ast.Name(id=field_name), annotation=annotation):
                                    if any(_call_name(node, local) in MUTABLE_TYPES for node in ast.walk(annotation)):
                                        yield Finding('mutable-field', module, declaration + '.' + field_name,
                                                      ast.unparse(annotation), field.lineno,
                                                      'Frozen records must not contain concrete mutable collections without an exact necessity.')
                                case _:
                                    pass
                    case _:
                        pass
        case ast.Call(func=function) if _call_name(function, local) in REFLECTION | {'builtins.' + name for name in REFLECTION}:
            yield Finding('explicit-attributes', module, declaration, ast.unparse(tree), tree.lineno,
                          'Use typed direct attributes, or declare an exact native/inspection exception.')
        case _:
            pass
    for child in ast.iter_child_nodes(tree):
        yield from _declarations(child, module, declaration, local)


def observation(source: Source, cache: Cache | None) -> Observation:
    key = cache.key('architecture', source) if cache is not None else ''
    if cache is not None and (saved := cache.read(key, OBSERVATION)) is not None:
        return saved
    tree = parse(source)
    module = module_name(source.name)
    aliases = _aliases(tree)
    dynamic: list[Finding] = []
    for node in ast.walk(tree):
        match node:
            case ast.Call(func=function, args=args, keywords=keywords) if _call_name(function, aliases) in (
                    'importlib.import_module', '__import__', 'builtins.__import__'):
                match args:
                    case [ast.Constant(value=str() as target), *_] if not target.startswith('.') and not any(
                            keyword.arg == 'level' for keyword in keywords):
                        pass
                    case _:
                        dynamic.append(Finding('keyboard-import', module, '', ast.unparse(node), node.lineno,
                                               'Keyboard dependencies require statically resolvable absolute import targets.'))
            case _:
                pass
    result = Observation(tuple(_declarations(tree, module)), tuple(dynamic))
    if cache is not None:
        cache.write(key, result, OBSERVATION)
    return result


FORBIDDEN_TEST_TOOLS = frozenset({'unittest.mock', 'mock', 'pytest_mock', 'mockito', 'pytest.MonkeyPatch'})


def testing_dependencies(source: Source) -> Iterator[Finding]:
    """Reject framework replacement seams in production and test source alike."""
    tree = parse(source)
    aliases = _aliases(tree)
    for node in ast.walk(tree):
        target = ''
        match node:
            case ast.Import(names=names):
                target = next((item.name for item in names if any(item.name == name or item.name.startswith(name + '.')
                              for name in FORBIDDEN_TEST_TOOLS)), '')
            case ast.ImportFrom(module=str() as module, names=names):
                imports = (module, *(module + '.' + item.name for item in names))
                target = next((item for item in imports if any(item == name or item.startswith(name + '.')
                              for name in FORBIDDEN_TEST_TOOLS)), '')
            case ast.Call(func=function, args=args):
                call = _call_name(function, aliases)
                if call in ('importlib.import_module', '__import__', 'builtins.__import__'):
                    match args:
                        case [ast.Constant(value=str() as module), *_] if module in FORBIDDEN_TEST_TOOLS:
                            target = module
                        case _:
                            pass
                elif (any(call == name or call.startswith(name + '.') for name in FORBIDDEN_TEST_TOOLS)
                      or call.split('.')[0] in ('monkeypatch', 'mocker')):
                    target = call
            case ast.arg(arg='monkeypatch' | 'mocker' as name):
                target = name
            case _:
                pass
        if target:
            match node:
                case ast.stmt(lineno=line) | ast.expr(lineno=line) | ast.arg(lineno=line):
                    yield Finding('testing-dependencies', module_name(source.name), '', ast.unparse(node), line,
                                  'Patches and mocks are disallowed; pass explicit dependencies or use real local resources: ' + target)
                case _:
                    pass


def review(root: Path, names: Iterable[str] | None = None, *, cache: Cache | None = None) -> Report:
    sources = python_sources(root, names)
    models, exceptions = _configuration(root)
    all_source = tuple(Source(name, (root / name).read_text(encoding='utf-8')) for name in sources)
    loaded = tuple(source for source in all_source if not source.name.startswith('tests/'))
    observations = {module_name(source.name): observation(source, cache) for source in loaded}
    graph = {module_name(source.name): dependencies(source.name, source.text, cache=cache) & observations.keys() for source in loaded}
    findings = [finding for observed in observations.values() for finding in observed.declarations]
    findings.extend(finding for source in all_source for finding in testing_dependencies(source))
    findings.extend(Finding('model-coverage', module, '', '', 0, 'Declared model module is absent; update its ownership declaration.')
                    for module in models if module not in observations)
    pending: deque[tuple[str, ...]] = deque((module,) for module in sorted(graph) if module == 'miryoku' or module.startswith('miryoku.'))
    visited: set[str] = set()
    while pending:
        route = pending.popleft()
        module = route[-1]
        if module in visited:
            continue
        visited.add(module)
        if module == 'assistant' or module.startswith('assistant.') or module == 'automation' or module.startswith('automation.'):
            findings.append(Finding('keyboard-isolation', route[0], '', '', 0, ' → '.join(route)))
            continue
        findings.extend(observations[module].dynamic_imports)
        pending.extend((*route, target) for target in sorted(graph[module]) if target not in visited)
    accepted = tuple(exception for exception in exceptions if any(exception.matches(finding) for finding in findings))
    failures = [finding for finding in findings if not any(exception.matches(finding) for exception in accepted)]
    failures.extend(Finding('stale-exception', exception.module, exception.declaration, exception.expression, 0,
                            'Remove the exception: its exact expression no longer exists.') for exception in exceptions if exception not in accepted)
    return Report(sources, tuple(failures), accepted)
