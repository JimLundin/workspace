"""Exclusive work-folder ownership released by the operating system on exit."""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

from cell import Cell


@dataclass(frozen=True, slots=True)
class ProfileLease:
    """One OS-released owner, acquired before opening/recovering the task store.

    The live file handle is held while the native lock is, and cleared on
    release. No mutable lease state leaves this owner.
    """

    folder: Path
    _file: Cell[BinaryIO | None] = field(default_factory=lambda: Cell[BinaryIO | None](None), init=False, repr=False)

    def __enter__(self) -> ProfileLease:
        if self._file.get() is not None:
            raise RuntimeError("The worker ownership lease is already held.")
        self.folder.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.folder / "worker.lock", os.O_RDWR | os.O_CREAT, 0o600)
        file = os.fdopen(descriptor, "r+b")
        try:
            if not file.read(1):
                file.write(b"0")
                file.flush()
            file.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            file.close()
            raise
        self._file.set(file)
        return self

    def close(self) -> None:
        file = self._file.get()
        self._file.set(None)
        if file is not None:
            try:
                file.seek(0)
                if sys.platform == "win32":
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(file, fcntl.LOCK_UN)
            finally:
                file.close()

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None) -> None:
        self.close()
