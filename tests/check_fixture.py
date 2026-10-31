"""Copy the edit check's own scripts into fixture source trees.

The copied set follows the entry modules' imports, including lazy ones, so a
new check dependency reaches every fixture without editing a file list.
"""

import shutil
from collections.abc import Iterable
from pathlib import Path

from scripts.architecture import dependencies

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def check_scripts(entries: Iterable[str]) -> frozenset[str]:
    """scripts/ file names reachable from the entry file names by import."""
    found: set[str] = set()
    pending = list(entries)
    while pending:
        name = pending.pop()
        if name in found:
            continue
        found.add(name)
        for module in dependencies(f"scripts/{name}", (SCRIPTS / name).read_text(encoding="utf-8")):
            match module.split("."):
                case ["scripts", child] if (SCRIPTS / f"{child}.py").is_file():
                    pending.append(f"{child}.py")
                case _:
                    pass
    return frozenset(found)


def copy_check_scripts(root: Path, entries: Iterable[str]) -> None:
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (scripts / "__init__.py").write_text("")
    for name in check_scripts(entries):
        shutil.copyfile(SCRIPTS / name, scripts / name)
