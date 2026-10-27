"""Apply Workspace's interface policies through Ruff and direct import observations.

Ruff owns signature detection. Python's mutable ASTs remain private to this
source-location adapter; immutable findings and exact migration keys leave it.
The installed selfcheck needs no Ruff dependency; editing checks and CI do.
"""

import ast
import hashlib
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import StrictInt, StrictStr, StringConstraints, TypeAdapter

from scripts.architecture import python_sources

type LintRule = Literal['FBT001', 'FBT002', 'PLR0913']
type Rule = LintRule | Literal['import-alias', 're-export', 'inline-import']
type Text = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
type Digest = Annotated[StrictStr, StringConstraints(pattern=r'^[0-9a-f]{64}$')]
type _Definition = tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]


@dataclass(frozen=True, slots=True)
class Location:
    row: StrictInt
    column: StrictInt


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: LintRule
    filename: Text
    location: Location
    message: Text


@dataclass(frozen=True, slots=True)
class Key:
    rule: Rule
    path: Text
    scope: Text
    signature: Digest


@dataclass(frozen=True, slots=True)
class Entry:
    key: Key
    reason: Text


@dataclass(frozen=True, slots=True)
class Baseline:
    kind: Literal['workspace-quality-migrations-v1']
    entries: tuple[Entry, ...]


@dataclass(frozen=True, slots=True)
class Finding:
    key: Key
    line: int
    detail: str

    def describe(self) -> str:
        return f'{self.key.path}:{self.line}: {self.key.rule}: {self.key.scope}: {self.detail}'


@dataclass(frozen=True, slots=True)
class Report:
    failures: tuple[Finding, ...]
    warnings: tuple[Finding, ...]
    stale: tuple[Entry, ...]
    legacy: int


DIAGNOSTICS = TypeAdapter[tuple[Diagnostic, ...]](tuple[Diagnostic, ...])
BASELINE = TypeAdapter[Baseline](Baseline)


def definitions(tree: ast.AST, scope: str = '') -> Iterator[_Definition]:
    match tree:
        case ast.ClassDef(name=name):
            scope = '.'.join(part for part in (scope, name) if part)
        case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
            scope = '.'.join(part for part in (scope, name) if part)
            yield scope, tree
        case _:
            pass
    for child in ast.iter_child_nodes(tree):
        yield from definitions(child, scope)


def _location_rank(item: _Definition) -> tuple[int, int]:
    return item[1].lineno, len(item[0])


def identify(root: Path, diagnostic: Diagnostic, scopes: Iterable[_Definition]) -> Finding:
    row = diagnostic.location.row
    candidates = (item for item in scopes if item[1].lineno <= row <= (item[1].end_lineno or item[1].lineno))
    scope, node = max(candidates, key=_location_rank)
    if diagnostic.code != 'PLR0913':
        parameter = next((arg.arg for arg in (*node.args.posonlyargs, *node.args.args)
                          if arg.lineno == row and arg.col_offset + 1 == diagnostic.location.column), '')
        scope = '.'.join(part for part in (scope, parameter) if part)
    signature = hashlib.sha256(ast.dump(node.args, include_attributes=False).encode()).hexdigest()
    key = Key(rule=diagnostic.code, path=Path(diagnostic.filename).relative_to(root).as_posix(), scope=scope, signature=signature)
    return Finding(key, row, diagnostic.message)


def scan(root: Path, names: Iterable[str] | None = None) -> tuple[Finding, ...]:
    root = root.resolve()
    sources = python_sources(root, names)
    if not sources:
        return ()
    profile = Path(__file__).resolve().parent.parent / 'pyproject.toml'
    result = subprocess.run((sys.executable, '-m', 'ruff', 'check', '--select', 'FBT001,FBT002,PLR0913',
                             '--ignore-noqa', '--output-format', 'json', '--config', str(profile),
                             '--config', 'lint.ignore=[]', '--config', 'lint.per-file-ignores={}', *sources),
                            cwd=root, capture_output=True, text=True, encoding='utf-8', check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError('Signature lint did not complete: ' + result.stderr.strip())
    diagnostics = DIAGNOSTICS.validate_json(result.stdout)

    def located() -> Iterator[Finding]:
        for name in sources:
            filename = str(root / name)
            tree = ast.parse(Path(filename).read_text(encoding='utf-8'), filename=filename)
            scopes = tuple(definitions(tree))
            for item in diagnostics:
                if Path(item.filename) == Path(filename):
                    yield identify(root, item, scopes)
            yield from imports(name, tree)
    return tuple(located())


def imports(path: str, tree: ast.Module) -> Iterator[Finding]:
    def walk(node: ast.AST, scope: str = '<module>') -> Iterator[Finding]:
        match node:
            case ast.ClassDef(name=name) | ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                scope = name if scope == '<module>' else scope + '.' + name
            case ast.Import(names=names) | ast.ImportFrom(names=names):
                signature = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
                if scope != '<module>':
                    key = Key(rule='inline-import', path=path, scope=scope, signature=signature)
                    yield Finding(key, node.lineno, 'Declare imports at module level; use lazy imports to defer loading.')
                if any(alias.asname for alias in names):
                    key = Key(rule='import-alias', path=path, scope=scope, signature=signature)
                    yield Finding(key, node.lineno, 'Import from the owner and use module-qualified names instead of cosmetic aliases.')
            case _:
                pass
        for child in ast.iter_child_nodes(node):
            yield from walk(child, scope)

    yield from walk(tree)
    def bindings() -> Iterator[tuple[Literal['import', 'local'], str]]:
        for node in tree.body:
            match node:
                case ast.Import(names=names) | ast.ImportFrom(names=names):
                    for alias in names:
                        yield 'import', alias.asname or alias.name
                case ast.ClassDef(name=name) | ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                    yield 'local', name
                case _:
                    pass
    observed = tuple(bindings())
    bound = frozenset(name for kind, name in observed if kind == 'import')
    owned = frozenset(name for kind, name in observed if kind == 'local')

    def forwarded_names(values: Iterable[ast.expr]) -> Iterator[str]:
        for value in values:
            match value:
                case ast.Constant(value=str() as name) if name in bound - owned:
                    yield name
                case _:
                    pass
    for node in tree.body:
        match node:
            case ast.Assign(targets=[ast.Name(id='__all__')], value=ast.List(elts=values) | ast.Tuple(elts=values)):
                forwarded = tuple(forwarded_names(values))
                if forwarded:
                    key = Key(rule='re-export', path=path, scope='__all__',
                              signature=hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest())
                    yield Finding(key, node.lineno, 'Export local interfaces; consumers should import forwarded names from their owner: '
                                  + ', '.join(forwarded))
            case _:
                pass


def load(path: Path) -> tuple[Entry, ...]:
    entries = BASELINE.validate_json(path.read_bytes()).entries
    if len(frozenset(entry.key for entry in entries)) != len(entries):
        raise ValueError('Quality migrations must contain unique exact keys.')
    for entry in entries:
        source = Path(entry.key.path)
        if source.is_absolute() or '..' in source.parts or source.as_posix() != entry.key.path or '*' in entry.key.scope:
            raise ValueError('Quality migrations require exact relative paths and declarations.')
    return entries


def compare(findings: Iterable[Finding], entries: Iterable[Entry]) -> Report:
    observations, baseline = tuple(findings), tuple(entries)
    accepted = frozenset(entry.key for entry in baseline)
    observed = frozenset(finding.key for finding in observations)
    new = tuple(finding for finding in observations if finding.key not in accepted)
    return Report(failures=tuple(finding for finding in new if finding.key.rule != 'PLR0913'),
                  warnings=tuple(finding for finding in new if finding.key.rule == 'PLR0913'),
                  stale=tuple(entry for entry in baseline if entry.key not in observed), legacy=len(accepted & observed))


def check(root: Path, names: Iterable[str] | None = None) -> Report:
    report = compare(scan(root, names), load(root / 'docs' / 'quality-migrations.json'))
    for finding in (*report.failures, *report.warnings):
        print(('Review warning: ' if finding.key.rule == 'PLR0913' else '') + finding.describe(), flush=True)
    for entry in report.stale:
        print(f'Stale quality migration: {entry.key.path}: {entry.key.scope}; remove its exact baseline entry.', flush=True)
    print(f'Quality: {len(report.failures)} interface violations, {len(report.warnings)} signature review warnings; '
          f'{report.legacy} existing migration entries.', flush=True)
    return report


def main() -> None:
    report = check(Path(__file__).resolve().parent.parent)
    raise SystemExit(bool(report.failures or report.stale))


if __name__ == '__main__':
    main()
