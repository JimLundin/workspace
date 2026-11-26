from pathlib import Path

from pydantic import TypeAdapter


def read[T](path: Path, adapter: TypeAdapter[T]) -> T | None:
    try:
        return adapter.validate_json(path.read_bytes(), strict=True)
    except OSError, ValueError:
        return None


def save[T](data: T, path: Path, adapter: TypeAdapter[T]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_bytes(adapter.dump_json(data) + b"\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
