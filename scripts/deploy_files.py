"""File contracts for one source-only Workspace release; no process operations."""

import hashlib
import json
import os
import re
import stat
import zipfile
from collections.abc import Collection, Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path, PurePosixPath

from pydantic import TypeAdapter, ValidationError

RUNTIME = frozenset({".runtime"})
RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})
PINS = (".python-version", "requirements/windows-py315.lock")
HELPERS = (
    "scripts/deploy.py",
    "scripts/deploy_files.py",
    "scripts/deploy_windows.py",
    "scripts/deploy_archive.py",
    "scripts/deploy_processes.py",
    "scripts/deploy_values.py",
    "scripts/deploy_policy.py",
    "scripts/architecture.py",
    "scripts/source_analysis.py",
    "scripts/development_paths.py",
    "winapi/__init__.py",
    "winapi/_core.py",
    "winapi/shapes.py",
    "keeper_control.py",
    "keeper.py",
    "components.py",
)
RECORD = TypeAdapter[dict[str, object]](dict[str, object])
SOURCE_HASHES = TypeAdapter[dict[str, str]](dict[str, str])


def sha(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path) -> dict[str, object]:
    try:
        return RECORD.validate_json(path.read_bytes(), strict=True)
    except ValidationError as error:
        raise ValueError("A release record must be a JSON object.") from error


def write(path: Path, value: Mapping[str, object]) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@lru_cache(maxsize=32768)
def member(name: str) -> str:
    if not name or "\\" in name:
        raise ValueError("A release member must be a relative POSIX path.")
    path = PurePosixPath(name)
    if path == PurePosixPath(".") or path.is_absolute() or path.as_posix() != name or any(part in (".", "..") for part in path.parts):
        raise ValueError("A release member escapes or aliases its destination.")
    for part in path.parts:
        if part.endswith((" ", ".")) or any(char in '<>:"|?*' or ord(char) < 32 for char in part) or part.split(".")[0].upper() in RESERVED:
            raise ValueError("A release member is not a regular Windows file path.")
    return name


def names(values: Iterable[str]) -> None:
    folded: dict[str, str] = {}
    for name in values:
        member(name)
        parts = PurePosixPath(name).parts
        for length in range(1, len(parts) + 1):
            prefix = "/".join(parts[:length])
            if folded.setdefault(prefix.casefold(), prefix) != prefix:
                raise ValueError("Release paths collide on Windows.")


def bytecode(name: str) -> bool:
    path = PurePosixPath(name)
    return "__pycache__" in path.parts or path.suffix.casefold() in (".pyc", ".pyo")


def no_link(path: Path) -> os.stat_result:
    observed = Path(path).lstat()
    if stat.S_ISLNK(observed.st_mode) or (os.name == "nt" and observed.st_file_attributes & 0x400):
        raise ValueError("Release paths cannot be links or Windows reparse points.")
    return observed


def file_at(root: Path, name: str) -> Path:
    path = Path(root)
    no_link(path)
    for part in PurePosixPath(member(name)).parts:
        path /= part
        if path.exists() or path.is_symlink():
            no_link(path)
    if path.exists() and not path.is_file():
        raise ValueError("A release destination is not a regular file.")
    return path


def files(root: Path, *, skip_roots: Collection[str] = (), ignore_extra_bytecode: bool = False, expected: Collection[str] = ()) -> dict[str, str]:
    root = Path(root)
    if not stat.S_ISDIR(no_link(root).st_mode):
        raise ValueError("A release tree must be a directory.")

    def walk() -> Iterator[tuple[str, Path]]:
        pending = [root]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    observed = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(observed.st_mode) or (os.name == "nt" and observed.st_file_attributes & 0x400):
                        raise ValueError("A release tree contains a link or junction.")
                    name = member(path.relative_to(root).as_posix())
                    if stat.S_ISDIR(observed.st_mode):
                        if directory != root or entry.name not in skip_roots:
                            pending.append(path)
                    elif not stat.S_ISREG(observed.st_mode):
                        raise ValueError("A release tree contains a nonregular file.")
                    elif not (ignore_extra_bytecode and bytecode(name) and name not in expected):
                        yield name, path

    def hashed(item: tuple[str, Path]) -> tuple[str, str]:
        name, path = item
        return name, sha(path)

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="source-release-hash") as workers:
        result = dict(workers.map(hashed, walk(), buffersize=16))
    names(result)
    return dict(sorted(result.items()))


def zip_files(path: Path, root: str = "workspace", *, source_only: bool = False) -> dict[str, str]:
    if root not in ("workspace", "toolkit"):
        raise ValueError("Unknown bundle root.")
    prefix = root + "/"
    result: dict[str, str] = {}
    seen: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if not info.filename.startswith(prefix) or info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("A release ZIP contains an unexpected, encrypted, or linked member.")
            name = member(info.filename[len(prefix) :])
            if name in seen:
                raise ValueError("A release ZIP contains duplicate members.")
            seen.add(name)
            if source_only and PurePosixPath(name).parts[0] in RUNTIME:
                continue
            with archive.open(info) as stream:
                digest = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                result[name] = digest.hexdigest()
    names(seen)
    return dict(sorted(result.items()))


def source_map(value: object) -> dict[str, str]:
    try:
        record = RECORD.validate_python(value, strict=True)
        result = SOURCE_HASHES.validate_python(record.get("files"), strict=True)
    except ValidationError as error:
        raise ValueError("Supply a nonempty source manifest with a files-to-SHA-256 object.") from error
    if not result:
        raise ValueError("Supply a nonempty source manifest with a files-to-SHA-256 object.")
    names(result)
    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in result.values()):
        raise ValueError("A source manifest contains an invalid SHA-256.")
    if any(PurePosixPath(name).parts[0] in RUNTIME | {".python"} or bytecode(name) for name in result):
        raise ValueError("This release accepts source files only, without private runtimes or bytecode.")
    if any(name not in result for name in PINS):
        raise ValueError("The frozen source manifest is missing a runtime pin.")
    return dict(sorted(result.items()))
