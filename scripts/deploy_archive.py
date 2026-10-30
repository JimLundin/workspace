"""Reindex preserved ZIP records without inflating or recompressing the runtime.

The pinned CPython ZipFile writer owns the central directory and ZIP64 output.
Only its local-record registration seam is used here; regression tests exercise
ordinary, descriptor and ZIP64 records through the public ZipFile reader.
"""

import copy
import zipfile
from pathlib import Path

from scripts.deploy_files import RUNTIME, member, names


def repack(previous: Path, destination: Path, source: Path, wanted: dict[str, str]) -> None:
    with zipfile.ZipFile(previous) as prior, zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED, compresslevel=1) as output:
        records = sorted(prior.infolist(), key=record_offset)
        members: set[str] = set()
        for info in records:
            if not info.filename.startswith("workspace/") or info.flag_bits & 1 or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("The prior bundle contains an unexpected, encrypted or linked member.")
            name = member(info.filename.removeprefix("workspace/").rstrip("/"))
            if name in members:
                raise ValueError("The prior bundle contains duplicate members.")
            members.add(name)
        names(members)
        assert prior.fp is not None and output.fp is not None
        for index, info in enumerate(records):
            name = info.filename.removeprefix("workspace/")
            if info.is_dir() or name.split("/")[0] not in RUNTIME:
                continue
            end = records[index + 1].header_offset if index + 1 < len(records) else prior.start_dir
            if end <= info.header_offset:
                raise ValueError("Overlapping ZIP local records.")
            fresh = copy.copy(info)
            fresh.header_offset = output.fp.tell()
            prior.fp.seek(info.header_offset)
            remaining = end - info.header_offset
            while remaining:
                chunk = prior.fp.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise ValueError("Truncated ZIP local record.")
                output.fp.write(chunk)
                remaining -= len(chunk)
            output.filelist.append(fresh)
            output.NameToInfo[fresh.filename] = fresh
            output.start_dir = output.fp.tell()
        for name in wanted:
            output.write(source / name, "workspace/" + name)
        # ZipFile.close now writes one fresh central directory. Dead source records
        # never accumulate, and retained compressed local records are byte-for-byte.


def record_offset(info: zipfile.ZipInfo) -> int:
    return info.header_offset
