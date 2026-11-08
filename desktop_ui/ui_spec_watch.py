"""Reload a spec folder while the desktop runs, on the Qt thread.

An install replaces spec files rather than rewriting them, which drops a watch on
the file itself, so the folder is watched too and the files are watched again
after every change. Bursts of changes (an editor's save, an install's several
files) settle for `SETTLE_MS` before one reload. A spec that loads and differs
from the current one is applied; one that fails is reported and the current spec
stays.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PySide6 import QtCore

from cell import Cell
from desktop_ui.ui_spec import SpecError

SETTLE_MS: Final = 150


@dataclass(frozen=True, slots=True, weakref_slot=True)
class SpecWatch[T]:
    """Qt connects bound methods through a weak reference to their owner."""

    _folder: Path
    _load: Callable[[], T]
    _apply: Callable[[T], None]
    _problem: Callable[[str], None]
    _settle: QtCore.QTimer
    _watcher: QtCore.QFileSystemWatcher
    _current: Cell[T]
    """The last good spec, applied."""

    @classmethod
    def start(
        cls,
        folder: Path,
        load: Callable[[], T],
        current: T,
        apply: Callable[[T], None],
        problem: Callable[[str], None],
    ) -> SpecWatch[T]:
        settle = QtCore.QTimer()
        settle.setSingleShot(True)
        settle.setInterval(SETTLE_MS)
        watch = cls(folder, load, apply, problem, settle, QtCore.QFileSystemWatcher(), Cell(current))
        settle.timeout.connect(watch.reload)
        watch._watcher.directoryChanged.connect(watch._changed)
        watch._watcher.fileChanged.connect(watch._changed)
        watch._watch()
        return watch

    def _watch(self) -> None:
        paths = [str(self._folder), *(str(path) for path in sorted(self._folder.glob("*.py")))]
        watched = set(self._watcher.files()) | set(self._watcher.directories())
        if missing := [path for path in paths if path not in watched]:
            self._watcher.addPaths(missing)

    def _changed(self, _: str) -> None:
        self._settle.start()

    def reload(self) -> None:
        self._watch()
        try:
            loaded = self._load()
        except SpecError as error:
            self._problem(f"The bar kept its last good spec: {error}")
            return
        if loaded != self._current.get():
            self._current.set(loaded)
            self._apply(loaded)

    def close(self) -> None:
        self._settle.stop()
        if paths := self._watcher.files() + self._watcher.directories():
            self._watcher.removePaths(paths)
