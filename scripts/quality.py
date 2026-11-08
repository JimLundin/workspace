"""Apply Workspace's interface policies through Ruff and direct import observations.

Ruff owns the Boolean-parameter and signature-size rules; this adapter adds the
import ownership rules Ruff lacks. Every finding blocks. A wide signature that a
real interface needs carries a targeted `# noqa: PLR0913` with its reason.
Checks and CI need Ruff, a development dependency.
"""

import ast
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Annotated, Literal

from pydantic import StrictInt, StrictStr, StringConstraints, TypeAdapter

from scripts.architecture import python_sources
from scripts.source_analysis import Cache, Source, parse

type LintRule = Literal["FBT001", "FBT002", "PLR0913", "PLC0415", "TID252"]
type Rule = LintRule | Literal["import-alias", "re-export"]
type Text = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]


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
class Finding:
    path: str
    line: int
    rule: Rule
    detail: str

    def describe(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.detail}"


DIAGNOSTICS = TypeAdapter[tuple[Diagnostic, ...]](tuple[Diagnostic, ...])
FINDINGS = TypeAdapter[tuple[Finding, ...]](tuple[Finding, ...])


def located(source: Source, diagnostics: tuple[Diagnostic, ...], cache: Cache | None) -> tuple[Finding, ...]:
    key = cache.key("quality", source, extra=DIAGNOSTICS.dump_json(diagnostics)) if cache is not None else ""
    if cache is not None and (saved := cache.read(key, FINDINGS)) is not None:
        return saved
    lint = (Finding(source.name, item.location.row, item.code, item.message) for item in diagnostics)
    result = (*lint, *imports(source.name, parse(source)))
    if cache is not None:
        cache.write(key, result, FINDINGS)
    return result


def scan(root: Path, names: Iterable[str] | None = None, *, cache: Cache | None = None) -> tuple[Finding, ...]:
    root = root.resolve()
    sources = python_sources(root, names)
    if not sources:
        return ()
    profile = root / "pyproject.toml"
    result = subprocess.run(
        (
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "FBT001,FBT002,PLR0913,PLC0415,TID252",
            "--output-format",
            "json",
            "--config",
            str(profile),
            *sources,
        ),
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode not in (0, 1) or not result.stdout.strip():
        raise RuntimeError("Signature lint did not complete: " + result.stderr.strip())
    diagnostics = DIAGNOSTICS.validate_json(result.stdout)
    # Group once instead of comparing every diagnostic's Windows path to every
    # source; a stable sort keeps each source's diagnostics in Ruff's order.
    named = sorted(((Path(item.filename).relative_to(root).as_posix(), item) for item in diagnostics), key=lambda pair: pair[0])
    grouped = frozendict((name, tuple(item for _, item in group)) for name, group in groupby(named, key=lambda pair: pair[0]))
    return tuple(
        finding for name in sources for finding in located(Source(name, (root / name).read_text(encoding="utf-8")), grouped.get(name, ()), cache)
    )


def imports(path: str, tree: ast.Module) -> Iterator[Finding]:
    for node in ast.walk(tree):
        match node:
            case ast.Import(names=names) | ast.ImportFrom(names=names) if any(alias.asname for alias in names):
                detail = "Import from the owner and use module-qualified names instead of cosmetic aliases."
                yield Finding(path, node.lineno, "import-alias", detail)
            case _:
                pass

    def bindings() -> Iterator[tuple[Literal["import", "local"], str]]:
        for node in tree.body:
            match node:
                case ast.Import(names=names) | ast.ImportFrom(names=names):
                    for alias in names:
                        yield "import", alias.asname or alias.name
                case ast.ClassDef(name=name) | ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                    yield "local", name
                case _:
                    pass

    observed = tuple(bindings())
    bound = frozenset(name for kind, name in observed if kind == "import")
    owned = frozenset(name for kind, name in observed if kind == "local")

    def forwarded_names(values: Iterable[ast.expr]) -> Iterator[str]:
        for value in values:
            match value:
                case ast.Constant(value=str() as name) if name in bound - owned:
                    yield name
                case _:
                    pass

    for node in tree.body:
        match node:
            case ast.Assign(targets=[ast.Name(id="__all__")], value=ast.List(elts=values) | ast.Tuple(elts=values)):
                forwarded = tuple(forwarded_names(values))
                if forwarded:
                    detail = "Export local interfaces; consumers should import forwarded names from their owner: " + ", ".join(forwarded)
                    yield Finding(path, node.lineno, "re-export", detail)
            case _:
                pass


def check(root: Path, names: Iterable[str] | None = None, *, cache: Cache | None = None) -> tuple[Finding, ...]:
    findings = scan(root, names, cache=cache)
    for finding in findings:
        print(finding.describe(), flush=True)
    print(f"Quality: {len(findings)} interface violations.", flush=True)
    return findings


def main() -> None:
    raise SystemExit(bool(check(Path(__file__).resolve().parent.parent)))


if __name__ == "__main__":
    main()
