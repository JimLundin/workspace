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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

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
    rule: str
    module: str
    declaration: str
    expression: str
    reason: str
    kind: Literal['necessity', 'migration'] = 'necessity'

    def matches(self, finding: Finding) -> bool:
        return (self.rule, self.module, self.declaration, self.expression) == (
            finding.rule, finding.module, finding.declaration, finding.expression)


@dataclass(frozen=True, slots=True)
class Report:
    sources: tuple[str, ...]
    failures: tuple[Finding, ...]
    exceptions: tuple[ExceptionSpec, ...]


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


def _call_name(node: ast.expr, aliases: Mapping[str, str]) -> str:
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


def dependencies(name: str, text: str) -> frozenset[str]:
    return _imports(name, ast.parse(text, filename=name))


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in cast('dict[object, object]', value)):
        raise ValueError('Architecture configuration must contain named tables.')
    return cast('dict[str, object]', value)


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in cast('list[object]', value)):
        raise ValueError('Architecture declarations must contain nonempty strings.')
    return tuple(cast('list[str]', value))


def _configuration(root: Path) -> tuple[tuple[str, ...], tuple[ExceptionSpec, ...]]:
    document = _object(cast(object, tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))))
    workspace = _object(_object(document.get('tool')).get('workspace'))
    configuration = _object(workspace.get('architecture'))
    models = _strings(configuration.get('models'))
    rows = configuration.get('exceptions', [])
    if not isinstance(rows, list):
        raise ValueError('Architecture exceptions must be a list of exact declarations.')
    exceptions: list[ExceptionSpec] = []
    for row in cast('list[object]', rows):
        fields = _object(row)
        values = _strings([fields.get(key) for key in ('rule', 'module', 'declaration', 'expression', 'reason')])
        rule, module, declaration, expression, reason = values
        if rule not in ('explicit-attributes', 'immutable-data', 'mutable-field') or any('*' in value for value in (module, declaration)):
            raise ValueError('Architecture exceptions require a supported rule and an exact declaration.')
        expression = ast.unparse(ast.parse(expression, mode='eval').body)
        kind = fields.get('kind', 'necessity')
        if kind not in ('necessity', 'migration'):
            raise ValueError('An exception must describe a necessity or existing migration debt.')
        exception = ExceptionSpec(rule, module, declaration, expression, reason, kind)
        if any((item.rule, item.module, item.declaration, item.expression) == (rule, module, declaration, expression) for item in exceptions):
            raise ValueError('Duplicate architecture exception.')
        exceptions.append(exception)
    return models, tuple(exceptions)


def _scope_aliases(tree: ast.AST, inherited: Mapping[str, str]) -> dict[str, str]:
    local = dict(inherited)
    pending = list(ast.iter_child_nodes(tree))
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        match node:
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
                  aliases: Mapping[str, str] | None = None) -> Iterable[Finding]:
    # Copy aliases once per lexical scope, not for every expression. Imports
    # inside conditional statements still belong to their enclosing scope.
    local = aliases or {}
    if isinstance(tree, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        local = _scope_aliases(tree, local)
    if isinstance(tree, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        declaration = '.'.join(part for part in (declaration, tree.name) if part)
    if isinstance(tree, ast.ClassDef):
        for decorator in tree.decorator_list:
            function = decorator.func if isinstance(decorator, ast.Call) else decorator
            if _call_name(function, local) != 'dataclasses.dataclass':
                continue
            flags = {keyword.arg: keyword.value for keyword in decorator.keywords} if isinstance(decorator, ast.Call) else {}
            if not all(isinstance(value := flags.get(flag), ast.Constant) and value.value is True for flag in ('frozen', 'slots')):
                yield Finding('immutable-data', module, declaration, tree.name, tree.lineno,
                              'Data records require frozen=True and slots=True, or an exact necessary-mutation exception.')
            # A mutable owner has one exception for its state. Frozen records
            # need a separate declaration for any concrete mutable field.
            frozen = flags.get('frozen')
            if isinstance(frozen, ast.Constant) and frozen.value is True:
                for field in tree.body:
                    if (isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name)
                            and any(isinstance(node, (ast.Name, ast.Attribute)) and _call_name(node, local) in MUTABLE_TYPES
                                    for node in ast.walk(field.annotation))):
                        yield Finding('mutable-field', module, declaration + '.' + field.target.id, ast.unparse(field.annotation), field.lineno,
                                      'Frozen records must not contain concrete mutable collections without an exact necessity.')
    if isinstance(tree, ast.Call):
        call = _call_name(tree.func, local)
        if call in REFLECTION or call in {'builtins.' + name for name in REFLECTION}:
            yield Finding('explicit-attributes', module, declaration, ast.unparse(tree), tree.lineno,
                          'Use typed direct attributes, or declare an exact native/inspection exception.')
    for child in ast.iter_child_nodes(tree):
        yield from _declarations(child, module, declaration, local)


def review(root: Path, names: Iterable[str] | None = None) -> Report:
    sources = python_sources(root, names)
    models, exceptions = _configuration(root)
    trees = {module_name(name): ast.parse((root / name).read_text(encoding='utf-8'), filename=name)
             for name in sources if not name.startswith('tests/')}
    graph = {module_name(name): _imports(name, trees[module_name(name)]) & trees.keys()
             for name in sources if not name.startswith('tests/')}
    findings = [finding for module, tree in trees.items() for finding in _declarations(tree, module)]
    findings.extend(Finding('model-coverage', module, '', '', 0, 'Declared model module is absent; update its ownership declaration.')
                    for module in models if module not in trees)
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
        aliases = _aliases(trees[module])
        for node in ast.walk(trees[module]):
            if (isinstance(node, ast.Call) and _call_name(node.func, aliases) in
                    ('importlib.import_module', '__import__', 'builtins.__import__')
                    and (not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str)
                         or node.args[0].value.startswith('.') or any(keyword.arg == 'level' for keyword in node.keywords))):
                findings.append(Finding('keyboard-import', module, '', ast.unparse(node), node.lineno,
                                        'Keyboard dependencies require statically resolvable absolute import targets.'))
        pending.extend((*route, target) for target in sorted(graph[module]) if target not in visited)
    accepted = tuple(exception for exception in exceptions if any(exception.matches(finding) for finding in findings))
    failures = [finding for finding in findings if not any(exception.matches(finding) for exception in accepted)]
    failures.extend(Finding('stale-exception', exception.module, exception.declaration, exception.expression, 0,
                            'Remove the exception: its exact expression no longer exists.') for exception in exceptions if exception not in accepted)
    return Report(sources, tuple(failures), accepted)
