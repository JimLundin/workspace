"""Copy the edit check's own scripts into fixture source trees.

The copied set follows the entry modules' imports, including lazy ones, so a
new check dependency reaches every fixture without editing a file list.
"""

import ast
import shutil
from collections.abc import Iterable
from pathlib import Path

from scripts.architecture import dependencies

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def check_scripts(entries: Iterable[str]) -> frozenset[str]:
    """Source file names, relative to the root, reachable from the scripts/ entry file names.

    Every scripts/ import is followed, and eager imports of top-level modules."""
    found: set[str] = set()
    pending = [f"scripts/{name}" for name in entries]
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found.add(name)
        for module in dependencies(name, (ROOT / name).read_text(encoding="utf-8")):
            match module.split("."):
                case ["scripts", child] if (SCRIPTS / f"{child}.py").is_file():
                    pending.append(f"scripts/{child}.py")
                case _:
                    pass
        pending.extend(f"{top}.py" for top in eager_roots((ROOT / name).read_text(encoding="utf-8")) if (ROOT / f"{top}.py").is_file())
    return frozenset(found)


def eager_roots(text: str) -> frozenset[str]:
    """Top-level modules a file imports when it loads; lazily imported ones are left out, as before."""
    roots: set[str] = set()
    for node in ast.parse(text).body:
        match node:
            case ast.Import(names=names, is_lazy=0):
                roots.update(alias.name.split(".")[0] for alias in names)
            case ast.ImportFrom(module=str() as module, level=0, is_lazy=0):
                roots.add(module.split(".")[0])
            case _:
                pass
    return frozenset(roots)


def copy_check_scripts(root: Path, entries: Iterable[str]) -> None:
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "__init__.py").write_text("")
    for name in check_scripts(entries):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, root / name)
