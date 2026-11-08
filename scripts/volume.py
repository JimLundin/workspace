"""Measure code volume as syntax nodes, which formatting and comments cannot move.

Lines reward dense code and punish Ruff's wrapping. A node count over the AST
ignores layout, comments, trailing commas and docstrings, and still grows with
every name, call, branch and literal the code actually adds. Page scripts and
PowerShell count their tokens the same way: comments and layout drop out, and a
string or regular-expression literal counts once, as a Python string is one node.
"""

import argparse
import ast
import re
import subprocess
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parent.parent
SUPPORT = ("tests", "typings", "scripts")


@dataclass(frozen=True, slots=True)
class Measure:
    path: str
    nodes: int


def docstrings(tree: ast.Module) -> frozenset[ast.AST]:
    owners = (tree, *(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)))
    return frozenset(first for owner in owners if (first := _docstring(owner.body)) is not None)


def _docstring(body: Sequence[ast.stmt]) -> ast.Expr | None:
    match body:
        case [ast.Expr(value=ast.Constant(value=str())) as first, *_]:
            return first
        case _:
            return None


def _levels(tree: ast.AST, skipped: frozenset[ast.AST]) -> Iterator[tuple[ast.AST, ...]]:
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


def measured(path: str, text: str) -> int:
    suffix = Path(path).suffix
    return tokens(text, suffix) if suffix in SCRIPTS else nodes(text)


def area(path: str) -> str:
    head, _, rest = path.partition("/")
    return head if rest else "(top level)"


def tracked(root: Path) -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", "*.py", "*.pyw", "*.pyi", *("*" + suffix for suffix in SCRIPTS)], cwd=root, capture_output=True, text=True, check=True
    )
    return listing.stdout.split()


def report(measures: Sequence[Measure], top: int) -> str:
    by_area = sorted(measures, key=lambda m: area(m.path))
    sums = frozendict((name, sum(m.nodes for m in group)) for name, group in groupby(by_area, key=lambda m: area(m.path)))
    # In first-seen order, so most_common breaks ties as it always has.
    totals = Counter({name: sums[name] for name in dict.fromkeys(area(m.path) for m in measures)})
    product = sum(n for name, n in totals.items() if name not in SUPPORT)
    support = sum(n for name, n in totals.items() if name in SUPPORT)
    rows = [f"{name:<14}{count:>9,}" for name, count in totals.most_common()]
    largest = sorted(measures, key=lambda m: m.nodes, reverse=True)[:top]
    rows += ["", f"{'product':<14}{product:>9,}", f"{'support':<14}{support:>9,}", ""]
    rows += [f"{m.nodes:>9,}  {m.path}" for m in largest]
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=15, help="list this many of the largest files")
    top: int = parser.parse_args().top
    measures = [Measure(path, measured(path, (ROOT / path).read_text(encoding="utf-8"))) for path in tracked(ROOT)]
    print(report(measures, top))


if __name__ == "__main__":
    main()
