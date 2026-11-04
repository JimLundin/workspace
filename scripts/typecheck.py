"""Run pyright against its bundled standard-library typeshed plus Workspace's overrides.

    python -m scripts.typecheck [pyright arguments]

`typings/typeshed-overrides/` holds the few corrected stub files; their README
says why each exists. Before pyright runs, the gitignored
`typings/.workspace-typeshed/` is rebuilt from the installed pyright whenever
the pyright version or an override changes. An override replaces a whole file,
so it is applied only while pyright ships the exact upstream file it was made
from; otherwise the build stops instead of silently reverting upstream fixes.
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

OVERRIDES = Path("typings") / "typeshed-overrides"
TYPESHED = Path("typings") / ".workspace-typeshed"
# SHA-256 of each upstream file an override replaces, with CRLF read as LF.
UPSTREAM = frozendict(
    {
        "stdlib/builtins.pyi": "3f13f3d2d990428af595f1f04d8525965bd71429539da3d6bff7eae110c21abb",
        "stdlib/subprocess.pyi": "de9971246f300dd198cf454c115d337d96ae74ef01c5a405e2a591e2fc865c9b",
        "stdlib/winreg.pyi": "ae7b1b386a5e35ef13ec359072568695f1649b21d54d935b3fc49c9058442640",
        "stdlib/_ctypes.pyi": "75c5f5a1cc8b307516cf77ebd8ff3fe909be8ca55972f5ef725e3d8bbce00567",
        "stdlib/ctypes/__init__.pyi": "616cce0f635ac52b186f65c056ca37145f007acdc9de2491526aa4c2eb9cb48a",
        "stdlib/urllib/request.pyi": "1b442c1bd2d89055e7f9c270bf186e9ffb6d5bb5f706456ab862de0b7d6b26ed",
    }
)


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


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _stamp(root: Path, bundled: Bundled) -> str:
    digest = hashlib.sha256(bundled.version.encode())
    for name in sorted(UPSTREAM):
        digest.update(name.encode() + b"\0" + (root / OVERRIDES / name).read_bytes())
    return digest.hexdigest()


def ensure(root: Path, bundled: Bundled) -> Path:
    """The patched typeshed for `root`, rebuilt only when it is missing or stale."""
    target = root / TYPESHED
    stamp = _stamp(root, bundled)
    marker = target / "stamp.txt"
    if marker.is_file() and marker.read_text(encoding="utf-8") == stamp:
        return target
    changed = tuple(name for name, expected in UPSTREAM.items() if _digest(bundled.folder / name) != expected)
    if changed:
        raise RuntimeError(
            f"pyright {bundled.version} ships different upstream stubs for {', '.join(changed)}. "
            f"Re-derive those files in {OVERRIDES.as_posix()} from the new upstream and update UPSTREAM in scripts/typecheck.py."
        )
    # Built beside the target and swapped in, so a concurrent check never reads a half-copied tree.
    building = target.with_name(f"{target.name}-{uuid.uuid4().hex}")
    shutil.copytree(bundled.folder / "stdlib", building / "stdlib")
    shutil.copyfile(bundled.folder / "LICENSE", building / "LICENSE")
    (building / "stubs").mkdir()
    for name in UPSTREAM:
        shutil.copyfile(root / OVERRIDES / name, building / name)
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
