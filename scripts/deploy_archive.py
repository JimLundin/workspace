"""Assemble a bundle from preserved ZIP records without inflating or recompressing them.

The pinned CPython ZipFile writer owns the central directory and ZIP64 output.
Only its local-record registration seam is used here; regression tests exercise
ordinary, descriptor and ZIP64 records through the public ZipFile reader.
"""

import copy
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scripts.deploy_files import RUNTIME, member, names


@dataclass(frozen=True, slots=True)
class Record:
    """One validated local record: its entry, member name and end offset in its archive."""

    info: zipfile.ZipInfo
    name: str
    end: int


def repack(previous: Path, payload: Path, destination: Path) -> None:
    """The previous bundle's runtime records followed by every checked source record of the payload."""
    with (
        zipfile.ZipFile(previous) as prior,
        zipfile.ZipFile(payload) as source,
        zipfile.ZipFile(destination, "x") as output,
    ):
        runtime = tuple(record for record in records(prior) if PurePosixPath(record.name).parts[0] in RUNTIME)
        checked = records(source)
        if any(PurePosixPath(record.name).parts[0] in RUNTIME for record in checked):
            raise ValueError("The source payload contains private runtime records.")
        names(record.name for record in (*runtime, *checked))
        copy_records(prior, runtime, output)
        copy_records(source, checked, output)
        # ZipFile.close now writes one fresh central directory. Dead source records
        # never accumulate, and every local record is preserved byte-for-byte.


def records(archive: zipfile.ZipFile) -> tuple[Record, ...]:
    ordered = sorted(archive.infolist(), key=record_offset)
    seen: set[str] = set()
    result: list[Record] = []
    for index, info in enumerate(ordered):
        if not info.filename.startswith("workspace/") or info.flag_bits & 1 or (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("A bundle contains an unexpected, encrypted or linked member.")
        name = member(info.filename.removeprefix("workspace/").rstrip("/"))
        if name in seen:
            raise ValueError("A bundle contains duplicate members.")
        seen.add(name)
        end = ordered[index + 1].header_offset if index + 1 < len(ordered) else archive.start_dir
        if end <= info.header_offset:
            raise ValueError("Overlapping ZIP local records.")
        if not info.is_dir():
            result.append(Record(info, name, end))
    names(seen)
    return tuple(result)


def copy_records(archive: zipfile.ZipFile, chosen: Iterable[Record], output: zipfile.ZipFile) -> None:
    assert archive.fp is not None and output.fp is not None
    for record in chosen:
        fresh = copy.copy(record.info)
        fresh.header_offset = output.fp.tell()
        archive.fp.seek(record.info.header_offset)
        remaining = record.end - record.info.header_offset
        while remaining:
            chunk = archive.fp.read(min(remaining, 1024 * 1024))
            if not chunk:
                raise ValueError("Truncated ZIP local record.")
            output.fp.write(chunk)
            remaining -= len(chunk)
        output.filelist.append(fresh)
        output.NameToInfo[fresh.filename] = fresh
        output.start_dir = output.fp.tell()


def record_offset(info: zipfile.ZipInfo) -> int:
    return info.header_offset
