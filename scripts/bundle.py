"""Build Workspace with pinned Qt and agent dependencies for installed Python 3.15."""

import argparse
import inspect
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class DependencyManifest:
    python: str
    platform: Literal["win_amd64"]
    wheels: tuple[str, ...]


DEPENDENCIES = TypeAdapter[DependencyManifest](DependencyManifest)


@dataclass(frozen=True, slots=True)
class PythonRelease:
    version: str

    @property
    def minor(self) -> str:
        return ".".join(self.version.split(".")[:2])

    @property
    def tag(self) -> str:
        return self.minor.replace(".", "")


def release(root: Path = ROOT) -> PythonRelease:
    data = PythonRelease((root / ".python-version").read_text(encoding="utf-8").strip())
    if re.fullmatch(r"3\.15\.\d+", data.version) is None:
        raise ValueError("The Python pin must specify a Python 3.15 release version.")
    return data


def extract(archive_path: Path, folder: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            path = Path(info.filename)
            executable = path.suffix.lower() == ".exe"
            if info.is_dir() or (executable or path.suffix.lower() == ".pyc" or any(p.endswith(".data") for p in path.parts)):
                continue
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Invalid archive member: {info.filename}")
            target = folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def build(output: Path) -> None:
    python = release()
    with tempfile.TemporaryDirectory(prefix="workspace-bundle-") as scratch:
        root = Path(scratch)
        wheels, bundle = root / "wheels", root / "workspace"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--only-binary=:all:",
                "--platform",
                "win_amd64",
                "--python-version",
                python.tag,
                "--implementation",
                "cp",
                "--abi",
                f"cp{python.tag}",
                "--dest",
                str(wheels),
                "--require-hashes",
                "-r",
                str(ROOT / "requirements" / f"windows-py{python.tag}.lock"),
            ],
            check=True,
        )
        patterns = (
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
        )

        def ignored(folder: str, names: list[str]) -> set[str]:
            return {name for name in names if name in patterns or name.endswith(".egg-info")}

        shutil.copytree(ROOT, bundle, ignore=ignored)
        runtime = bundle / ".runtime"
        runtime.mkdir()
        packages: list[str] = []
        for wheel in sorted(wheels.glob("*.whl")):
            packages.append(wheel.name)
            extract(wheel, runtime)
        manifest = DependencyManifest(python.minor, "win_amd64", tuple(packages))
        (runtime / "manifest.json").write_bytes(DEPENDENCIES.dump_json(manifest, indent=2))
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    if path.suffix.lower() == ".exe":
                        raise ValueError(f"Dependency bundles cannot contain EXEs: {path}")
                    archive.write(path, path.relative_to(root))
        print(f"Built {output}: installed Python {python.version} with Qt, {len(packages)} dependency wheels", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    match dict(inspect.getmembers(parser.parse_args())):
        case {"output": Path() as output}:
            build(output)
        case _:
            parser.error("Invalid bundle arguments.")


if __name__ == "__main__":
    main()
