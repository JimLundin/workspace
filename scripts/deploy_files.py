"""Check receipts and source manifests: what a check proved and what a deploy may install."""

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import TypeAdapter, ValidationError

RUNTIME = frozenset({".runtime"})
RESERVED = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})
PINS = (".python-version", "requirements/windows-py315.lock")
RECORD = TypeAdapter[dict[str, object]](dict[str, object])
SOURCE_HASHES = TypeAdapter[dict[str, str]](dict[str, str])


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckedArchitecture:
    sources: int
    exceptions: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckReceipt:
    """A successful scripts.check run, bound to the exact source bytes it checked."""

    files: frozendict[str, str]
    tests: tuple[str, ...]
    profile: str
    platform: str
    passed: int
    skipped: int
    architecture: CheckedArchitecture
    elapsed_seconds: float
    checked_at_ns: int
    # Whether the whole-tree lint, format and type standards passed in this run.
    standards: bool
    kind: Literal["workspace-edit-check-v1"] = "workspace-edit-check-v1"


CHECK_RECEIPT = TypeAdapter[CheckReceipt](CheckReceipt)


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


def json_record[T](adapter: TypeAdapter[T], value: T) -> dict[str, object]:
    """A typed value as the JSON object `write` stores, read back through its wire form."""
    return RECORD.validate_json(adapter.dump_json(value))


def write_receipt(path: Path, receipt: CheckReceipt) -> None:
    write(path, json_record(CHECK_RECEIPT, receipt))


def read_receipt(path: Path) -> CheckReceipt:
    try:
        return CHECK_RECEIPT.validate_json(path.read_bytes(), strict=True)
    except ValidationError as error:
        raise ValueError("Supply a successful scripts.check source-bound receipt.") from error


def source_map(value: object) -> dict[str, str]:
    try:
        record = RECORD.validate_python(value, strict=True)
        result = SOURCE_HASHES.validate_python(record.get("files"), strict=True)
    except ValidationError as error:
        raise ValueError("Supply a nonempty source manifest with a files-to-SHA-256 object.") from error
    return checked_sources(result)


def checked_sources(result: Mapping[str, str]) -> dict[str, str]:
    """A release's source manifest: hashed source files only, including the runtime pins."""
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
