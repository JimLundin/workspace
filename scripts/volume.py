"""Measure code volume as syntax nodes, which formatting and comments cannot move.

Lines reward dense code and punish Ruff's wrapping. A node count over the AST
ignores layout, comments, trailing commas and docstrings, and still grows with
every name, call, branch and literal the code actually adds.
"""

import argparse
import ast
import subprocess
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

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


def area(path: str) -> str:
    head, _, rest = path.partition("/")
    return head if rest else "(top level)"


def tracked(root: Path) -> list[str]:
    listing = subprocess.run(["git", "ls-files", "*.py", "*.pyw", "*.pyi"], cwd=root, capture_output=True, text=True, check=True)
    return listing.stdout.split()


def report(measures: list[Measure], top: int) -> str:
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
    measures = [Measure(path, nodes((ROOT / path).read_text(encoding="utf-8"))) for path in tracked(ROOT)]
    print(report(measures, top))


if __name__ == "__main__":
    main()
