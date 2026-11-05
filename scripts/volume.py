"""Measure code volume as syntax nodes, which formatting and comments cannot move.

Lines reward dense code and punish Ruff's wrapping. A node count over the AST
ignores layout, comments, trailing commas and docstrings, and still grows with
every name, call, branch and literal the code actually adds.
"""

import argparse
import ast
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUPPORT = ("tests", "typings", "scripts")


@dataclass(frozen=True, slots=True)
class Measure:
    path: str
    nodes: int


def docstrings(tree: ast.Module) -> set[ast.AST]:
    owners = [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef))]
    found: set[ast.AST] = set()
    for owner in owners:
        match owner.body:
            case [ast.Expr(value=ast.Constant(value=str())) as first, *_]:
                found.add(first)
            case _:
                pass
    return found


def nodes(text: str) -> int:
    tree = ast.parse(text)
    skipped = docstrings(tree)
    pending: list[ast.AST] = [tree]
    count = 0
    while pending:
        node = pending.pop()
        if node in skipped or isinstance(node, ast.expr_context):
            continue
        count += 1
        pending.extend(ast.iter_child_nodes(node))
    return count


def area(path: str) -> str:
    head, _, rest = path.partition("/")
    return head if rest else "(top level)"


def tracked(root: Path) -> list[str]:
    listing = subprocess.run(["git", "ls-files", "*.py", "*.pyw", "*.pyi"], cwd=root, capture_output=True, text=True, check=True)
    return listing.stdout.split()


def report(measures: list[Measure], top: int) -> str:
    totals: Counter[str] = Counter()
    for measure in measures:
        totals[area(measure.path)] += measure.nodes
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
