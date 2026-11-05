"""Run pyright against its bundled standard-library typeshed with Workspace's corrections.

    python -m scripts.typecheck [pyright arguments]

`typings/typeshed.patch` holds the few stub corrections; `typings/README.md`
says why each exists. Before pyright runs, the gitignored
`typings/.workspace-typeshed/` is rebuilt from the installed pyright whenever
the pyright version or the patch changes. `git apply` refuses a hunk whose
upstream context moved, so a pyright upgrade stops the build instead of
silently reverting an upstream fix.
"""

import hashlib
import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

PATCH = Path("typings") / "typeshed.patch"
TYPESHED = Path("typings") / ".workspace-typeshed"


@dataclass(frozen=True, slots=True)
class Bundled:
    """The typeshed shipped inside an installed pyright."""

    folder: Path
    version: str


def installed() -> Bundled:
    spec = importlib.util.find_spec("pyright")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("pyright is not installed in this environment.")
    folder = Path(spec.submodule_search_locations[0]) / "dist" / "dist" / "typeshed-fallback"
    return Bundled(folder, importlib.metadata.version("pyright"))


def _stamp(root: Path, bundled: Bundled) -> str:
    return hashlib.sha256(bundled.version.encode() + b"\0" + (root / PATCH).read_bytes()).hexdigest()


def ensure(root: Path, bundled: Bundled) -> Path:
    """The patched typeshed for `root`, rebuilt only when it is missing or stale."""
    target = root / TYPESHED
    stamp = _stamp(root, bundled)
    marker = target / "stamp.txt"
    if marker.is_file() and marker.read_text(encoding="utf-8") == stamp:
        return target
    # Built beside the target and swapped in, so a concurrent check never reads a half-copied tree.
    building = target.with_name(f"{target.name}-{uuid.uuid4().hex}")
    shutil.copytree(bundled.folder / "stdlib", building / "stdlib")
    shutil.copyfile(bundled.folder / "LICENSE", building / "LICENSE")
    (building / "stubs").mkdir()
    # Run from the checkout root: inside a repository, git apply skips paths outside its index.
    applied = subprocess.run(
        ("git", "apply", f"--directory={building.relative_to(root).as_posix()}", PATCH.as_posix()),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if applied.returncode:
        shutil.rmtree(building, ignore_errors=True)
        raise RuntimeError(
            f"{PATCH.as_posix()} does not apply to pyright {bundled.version}'s typeshed; re-derive it from the new upstream.\n{applied.stderr}"
        )
    (building / "stamp.txt").write_text(stamp, encoding="utf-8")
    # Windows briefly denies renaming a folder whose new files a scanner still holds open.
    for _ in range(50):
        shutil.rmtree(target, ignore_errors=True)
        try:
            os.replace(building, target)
        except OSError:
            if marker.is_file() and marker.read_text(encoding="utf-8") == stamp:
                shutil.rmtree(building, ignore_errors=True)  # another check published it first
                return target
            time.sleep(0.1)
        else:
            return target
    raise RuntimeError(f"Could not publish {target}; {building} holds the built typeshed.")


def main() -> None:
    root = Path.cwd()
    ensure(root, installed())
    sys.exit(subprocess.run((sys.executable, "-m", "pyright", *sys.argv[1:]), cwd=root, check=False).returncode)


if __name__ == "__main__":
    main()
