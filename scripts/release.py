"""Build Workspace's release ZIP: the source alone, for installed Python 3.15.

python scripts/release.py dist/workspace-python315-win64.zip

It holds no dependencies. The first start builds the environment the pinned,
hashed lock names, from PyPI (`environments.py`); every later lock change does
the same at install.
"""

import argparse
import inspect
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORED = frozenset(
    {
        ".git",
        ".venv",
        ".runtime",
        ".python",
        ".bundle-cache",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".pyright",
        ".hypothesis",
        "dist",
        "typings",
    }
)
"""Development state and caches, never part of a release."""


@dataclass(frozen=True, slots=True)
class PythonRelease:
    version: str

    @property
    def minor(self) -> str:
        return ".".join(self.version.split(".")[:2])


def release(root: Path = ROOT) -> PythonRelease:
    data = PythonRelease((root / ".python-version").read_text(encoding="utf-8").strip())
    if re.fullmatch(r"3\.15\.\d+", data.version) is None:
        raise ValueError("The Python pin must specify a Python 3.15 release version.")
    return data


def build(output: Path, root: Path = ROOT) -> int:
    """Write the ZIP under `workspace/`; the number of files in it."""
    python = release(root)
    with tempfile.TemporaryDirectory(prefix="workspace-release-") as scratch:
        copy = Path(scratch) / "workspace"

        def ignored(_folder: str, names: list[str]) -> set[str]:
            return {name for name in names if name in IGNORED or name.endswith(".egg-info")}

        shutil.copytree(root, copy, ignore=ignored)
        files = tuple(path for path in sorted(copy.rglob("*")) if path.is_file())
        if executables := [path.relative_to(copy).as_posix() for path in files if path.suffix.lower() in {".exe", ".dll", ".pyd"}]:
            raise ValueError(f"A source release cannot contain binaries: {', '.join(executables[:5])}")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(copy.parent))
    print(f"Built {output}: Workspace source for Python {python.minor}, {len(files)} files", flush=True)
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    match dict(inspect.getmembers(parser.parse_args())):
        case {"output": Path() as output}:
            build(output)
        case _:
            parser.error("Invalid release arguments.")


if __name__ == "__main__":
    main()
