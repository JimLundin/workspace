"""Measure code volume as syntax nodes, which formatting and comments cannot move, beside its code lines.

Lines reward dense code and punish Ruff's wrapping. A node count over the AST
ignores layout, comments, trailing commas and docstrings, and still grows with
every name, call, branch and literal the code actually adds. Page scripts and
PowerShell count their tokens the same way: comments and layout drop out, and a
string or regular-expression literal counts once, as a Python string is one node.
Code lines (no blanks, comments or docstrings) are reported beside the nodes,
because a line is easier to picture.

    python -m scripts.volume [--top N]                print the measure
    python -m scripts.volume --write docs/volume.md   rewrite the committed report
    python -m scripts.volume --check docs/volume.md   fail when the report is stale

With --staged the measure reads what is staged for the next commit, which the
pre-commit hook (.githooks/pre-commit) writes into the commit it makes.
"""

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parent.parent
SUPPORT = ("tests", "typings", "scripts")
REPORT_TOP: Final = 25
"""How many of the largest files the committed report lists."""


@dataclass(frozen=True, slots=True)
class Measure:
    path: str
    nodes: int
    lines: int


def docstrings(tree: ast.Module) -> frozenset[ast.Expr]:
    owners = (tree, *(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)))
    return frozenset(first for owner in owners if (first := _docstring(owner.body)))


def _docstring(body: Sequence[ast.stmt]) -> ast.Expr | None:
    match body:
        case [ast.Expr(value=ast.Constant(value=str())) as first, *_]:
            return first
        case _:
            return None


def _levels(tree: ast.AST, skipped: frozenset[ast.Expr]) -> Iterator[tuple[ast.AST, ...]]:
    """The counted nodes one depth at a time; a skipped node hides its whole subtree."""
    level: tuple[ast.AST, ...] = (tree,)
    while level:
        yield level
        level = tuple(
            child for node in level for child in ast.iter_child_nodes(node) if child not in skipped and not isinstance(child, ast.expr_context)
        )


def nodes(text: str) -> int:
    tree = ast.parse(text)
    return sum(len(level) for level in _levels(tree, docstrings(tree)))


_LAYOUT: Final = frozenset({tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER})


def code_lines(text: str) -> int:
    """Lines holding Python code: not blank, not only a comment, and not part of a docstring."""
    documented = frozenset(line for doc in docstrings(ast.parse(text)) for line in range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    written = (
        line
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type not in _LAYOUT
        for line in range(token.start[0], token.end[0] + 1)
    )
    return len(frozenset(written) - documented)


_LITERAL = r"""'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`"""
_WORD = r"[A-Za-z_$][\w$]*|\d[\w.]*"
# A slash after an operator or an opening bracket starts a regular expression, not a division.
_REGEX = r"(?<=[(,=:\[!&|?{};])\s*/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\n])+/[a-z]*"
_MARK = r"=>|[=!]==|\?\?|\?\.|\.\.\.|&&|\|\||[=!<>]=|\S"
_JS = re.compile(rf"(?P<skip>//[^\n]*|/\*.*?\*/|\s+)|(?P<literal>{_LITERAL})|(?P<regex>{_REGEX})|(?P<word>{_WORD})|(?P<mark>{_MARK})", re.DOTALL)
_POWERSHELL = re.compile(
    rf"(?P<skip><#.*?#>|#[^\n]*|\s+)|(?P<literal>{_LITERAL})|(?P<word>-?[A-Za-z_$][\w$:]*|\d[\w.]*)|(?P<mark>{_MARK})", re.DOTALL
)
SCRIPTS: Final = frozendict({".js": _JS, ".ps1": _POWERSHELL})
"""Each tracked script language and its tokenizer."""


def tokens(text: str, suffix: str) -> int:
    """A script's tokens: every match that isn't a comment or whitespace."""
    return sum(1 for match in SCRIPTS[suffix].finditer(text) if match.lastgroup != "skip")


def _script_lines(text: str, suffix: str) -> int:
    """Lines a script's tokens start on: comments and blank lines drop out."""
    return len(frozenset(text.count("\n", 0, match.start()) for match in SCRIPTS[suffix].finditer(text) if match.lastgroup != "skip"))


def measured(path: str, text: str) -> int:
    suffix = Path(path).suffix
    return tokens(text, suffix) if suffix in SCRIPTS else nodes(text)


def measure(path: str, text: str) -> Measure:
    suffix = Path(path).suffix
    return Measure(path, measured(path, text), _script_lines(text, suffix) if suffix in SCRIPTS else code_lines(text))


def area(path: str) -> str:
    head, _, rest = path.partition("/")
    return head if rest else "(top level)"


_PATTERNS: Final = ("*.py", "*.pyw", "*.pyi", *("*" + suffix for suffix in SCRIPTS))


def tracked(root: Path) -> list[str]:
    listing = subprocess.run(["git", "ls-files", *_PATTERNS], cwd=root, capture_output=True, text=True, check=True)
    return listing.stdout.split()


def working_tree(root: Path) -> Iterator[Measure]:
    return (measure(path, (root / path).read_text(encoding="utf-8")) for path in tracked(root) if (root / path).is_file())


def staged(root: Path) -> Iterator[Measure]:
    """What is staged for the next commit: each source's blob, read in one batch."""
    listing = subprocess.run(["git", "ls-files", "--stage", "-z", *_PATTERNS], cwd=root, capture_output=True, text=True, check=True)
    entries = tuple(line.split("\t", 1) for line in listing.stdout.split("\0") if line)
    blobs = tuple((info.split()[1], path) for info, path in entries)
    batch = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=root, input="".join(blob + "\n" for blob, _ in blobs).encode(), capture_output=True, check=True
    )
    return _blobs(batch.stdout, tuple(path for _, path in blobs))


def _blobs(output: bytes, paths: Sequence[str]) -> Iterator[Measure]:
    """Each `git cat-file --batch` record, `<sha> blob <size>\\n<content>\\n`, measured as the path it was staged at."""
    offset = 0
    for path in paths:
        header_end = output.index(b"\n", offset)
        size = int(output[offset:header_end].split()[2])
        yield measure(path, output[header_end + 1 : header_end + 1 + size].decode("utf-8"))
        offset = header_end + 1 + size + 1


@dataclass(frozen=True, slots=True)
class Total:
    name: str
    nodes: int
    lines: int


def _total(name: str, measures: Iterable[Measure]) -> Total:
    counted = tuple(measures)
    return Total(name, sum(m.nodes for m in counted), sum(m.lines for m in counted))


def totals(measures: Sequence[Measure]) -> tuple[tuple[Total, ...], Total, Total]:
    """Each area by size, then product and support."""
    names = dict.fromkeys(area(m.path) for m in measures)
    areas = sorted((_total(name, (m for m in measures if area(m.path) == name)) for name in names), key=lambda t: -t.nodes)
    product = _total("product", (m for m in measures if area(m.path) not in SUPPORT))
    support = _total("support", (m for m in measures if area(m.path) in SUPPORT))
    return tuple(areas), product, support


def report(measures: Sequence[Measure], top: int) -> str:
    areas, product, support = totals(measures)
    largest = sorted(measures, key=lambda m: m.nodes, reverse=True)[:top]
    return "\n".join(
        (
            f"{'':<14}{'nodes':>9}{'lines':>9}",
            *(f"{t.name:<14}{t.nodes:>9,}{t.lines:>9,}" for t in areas),
            "",
            *(f"{t.name:<14}{t.nodes:>9,}{t.lines:>9,}" for t in (product, support)),
            "",
            *(f"{m.nodes:>9,}{m.lines:>9,}  {m.path}" for m in largest),
        )
    )


def markdown(measures: Sequence[Measure], top: int = REPORT_TOP) -> str:
    """The committed report: deterministic, so it changes only when the code does."""
    areas, product, support = totals(measures)
    largest = sorted(measures, key=lambda m: (-m.nodes, m.path))[:top]
    ratio = product.nodes / product.lines if product.lines else 0.0
    return "\n".join(
        (
            "# Code volume",
            "",
            "Written by `python -m scripts.volume --write docs/volume.md` on every commit (`.githooks/pre-commit`);",
            "CI fails when it is stale. Nodes are syntax nodes (layout, comments and docstrings don't count);",
            f"lines are code lines. Product code averages {ratio:.1f} nodes a line.",
            "",
            "| | nodes | lines |",
            "|---|---:|---:|",
            *(f"| **{t.name}** | {t.nodes:,} | {t.lines:,} |" for t in (product, support)),
            "",
            "| area | nodes | lines |",
            "|---|---:|---:|",
            *(f"| {t.name} | {t.nodes:,} | {t.lines:,} |" for t in areas),
            "",
            f"The {top} largest files:",
            "",
            "| file | nodes | lines |",
            "|---|---:|---:|",
            *(f"| `{m.path}` | {m.nodes:,} | {m.lines:,} |" for m in largest),
            "",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=15, help="list this many of the largest files")
    parser.add_argument("--staged", action="store_true", help="measure what is staged for the next commit")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--write", type=Path, help="rewrite this Markdown report")
    target.add_argument("--check", type=Path, help="fail when this Markdown report doesn't match the code")
    args = parser.parse_args()
    measures = tuple(staged(ROOT) if args.staged else working_tree(ROOT))
    if args.write is not None:
        (ROOT / args.write).write_text(markdown(measures), encoding="utf-8", newline="\n")
    elif args.check is not None:
        path = ROOT / args.check
        if not path.is_file() or path.read_text(encoding="utf-8") != markdown(measures):
            print(f"{args.check} is stale: run python -m scripts.volume --write {args.check.as_posix()}")
            sys.exit(1)
    else:
        print(report(measures, args.top))


if __name__ == "__main__":
    main()
