"""Check receipts and their source manifests: what a check proved, the baseline the next check selects from."""

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter, ValidationError

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
        raise ValueError("A check record must be a JSON object.") from error


def write(path: Path, value: Mapping[str, object]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def json_record[T](adapter: TypeAdapter[T], value: T) -> dict[str, object]:
    """A typed value as the JSON object `write` stores, read back through its wire form."""
    return RECORD.validate_json(adapter.dump_json(value))


def write_receipt(path: Path, receipt: CheckReceipt) -> None:
    write(path, json_record(CHECK_RECEIPT, receipt))


def source_map(value: object) -> dict[str, str]:
    try:
        record = RECORD.validate_python(value, strict=True)
        result = SOURCE_HASHES.validate_python(record.get("files"), strict=True)
    except ValidationError as error:
        raise ValueError("Supply a nonempty source manifest with a files-to-SHA-256 object.") from error
    if not result or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in result.values()):
        raise ValueError("Supply a nonempty source manifest with a files-to-SHA-256 object.")
    return dict(sorted(result.items()))
