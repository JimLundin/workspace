"""Build Workspace with pinned Windows Python, Qt, and agent dependencies."""

import argparse
import hashlib
import inspect
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from http.client import HTTPResponse
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parent.parent
WEB_ENGINE_PROCESS = "PySide6/QtWebEngineProcess.exe"


@dataclass(frozen=True, slots=True)
class PythonRelease:
    version: str
    url: str
    sha256: str
    exclude: tuple[str, ...]

    @property
    def minor(self) -> str:
        return ".".join(self.version.split(".")[:2])

    @property
    def tag(self) -> str:
        return self.minor.replace(".", "")


PYTHON_RELEASE = TypeAdapter[PythonRelease](PythonRelease)


def release(root: Path = ROOT) -> PythonRelease:
    data = PYTHON_RELEASE.validate_json((root / "requirements" / "python-win64.json").read_bytes(), strict=True)
    if re.fullmatch(r"\d+\.\d+\.\d+", data.version) is None:
        raise ValueError("The Python pin must specify a release version.")
    if not data.url.startswith("https://"):
        raise ValueError("The Python archive URL must use HTTPS.")
    if re.fullmatch(r"[0-9a-f]{64}", data.sha256) is None:
        raise ValueError("The Python archive must have a pinned SHA-256.")
    for value in data.exclude:
        if (not value or "\\" in value or ":" in value
                or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts
                or PurePosixPath(value).as_posix() != value or value == "."):
            raise ValueError("Excluded runtime paths must be relative archive paths.")
    return data


def download_python(python: PythonRelease, cache: Path) -> Path:
    """Reuse verified downloads; the published archive hash is pinned in source."""
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"python-{python.version}-amd64.zip"
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == python.sha256:
        return target
    with tempfile.NamedTemporaryFile(dir=cache, suffix=".zip", delete=False) as output:
        temporary = Path(output.name)
        try:
            response: object = urlopen(python.url, timeout=60)
            match response:
                case HTTPResponse():
                    with response:
                        shutil.copyfileobj(response, output)
                case _:
                    raise ValueError("The Python archive request did not return an HTTP response.")
        except BaseException:
            output.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != python.sha256:
            raise ValueError("The Python archive does not match its pinned SHA-256.")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def extract(archive_path: Path, folder: Path, *, dependency: bool = False, exclude: tuple[str, ...] = ()) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            path = Path(info.filename)
            executable = path.suffix.lower() == ".exe" and path.as_posix() != WEB_ENGINE_PROCESS
            if info.is_dir() or (dependency and (executable or path.suffix.lower() == ".pyc" or any(p.endswith(".data") for p in path.parts))):
                continue
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Invalid archive member: {info.filename}")
            if any(path.as_posix() == value or path.as_posix().startswith(value + "/") for value in exclude):
                continue
            target = folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def build(output: Path, cache: Path) -> None:
    python = release()
    interpreter_archive = download_python(python, cache)
    with tempfile.TemporaryDirectory(prefix="workspace-bundle-") as scratch:
        root = Path(scratch)
        wheels, bundle = root / "wheels", root / "workspace"
        subprocess.run(
            [sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:", "--platform", "win_amd64",
             "--python-version", python.tag, "--implementation", "cp", "--abi", f"cp{python.tag}", "--dest", str(wheels),
             "--require-hashes", "-r", str(ROOT / "requirements" / f"windows-py{python.tag}.lock")], check=True,
        )
        patterns = (
            ".git", ".venv", ".runtime", ".python", ".bundle-cache", "__pycache__", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", ".pyright", ".hypothesis", "dist",
        )

        def ignored(folder: str, names: list[str]) -> set[str]:
            return {name for name in names if name in patterns or name.endswith(".egg-info")}

        shutil.copytree(ROOT, bundle, ignore=ignored)
        extract(interpreter_archive, bundle / ".python", exclude=python.exclude)
        runtime = bundle / ".runtime"
        runtime.mkdir()
        packages: list[str] = []
        for wheel in sorted(wheels.glob("*.whl")):
            packages.append(wheel.name)
            extract(wheel, runtime, dependency=True)
        manifest: dict[str, str | list[str]] = {
            "python": python.minor, "platform": "win_amd64", "wheels": packages,
            "interpreter_version": python.version, "interpreter_sha256": python.sha256,
            "interpreter_excluded": list(python.exclude),
        }
        (runtime / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(bundle)
                    if path.suffix.lower() == ".exe" and relative.parts[0] != ".python" and relative.as_posix() != f".runtime/{WEB_ENGINE_PROCESS}":
                        raise ValueError(f"Only the pinned Python and WebEngine runtimes may contain EXEs: {path}")
                    archive.write(path, path.relative_to(root))
        print(f"Built {output}: Python {python.version} with Qt, {len(packages)} dependency wheels", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, default=ROOT / "dist" / ".bundle-cache")
    match dict(inspect.getmembers(parser.parse_args())):
        case {'output': Path() as output, 'cache': Path() as cache}:
            build(output, cache)
        case _:
            parser.error('Invalid bundle arguments.')


if __name__ == "__main__":
    main()
