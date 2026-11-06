"""Reload a spec folder while the desktop runs, on the Qt thread.

An install replaces spec files rather than rewriting them, which drops a watch on
the file itself, so the folder is watched too and the files are watched again
after every change. Bursts of changes (an editor's save, an install's several
files) settle for `SETTLE_MS` before one reload. A spec that loads and differs
from the current one is applied; one that fails is reported and the current spec
stays.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Final

from PySide6 import QtCore

from desktop_ui.ui_spec import SpecError

SETTLE_MS: Final = 150


class SpecWatch[T]:
    __slots__ = ("__weakref__", "_apply", "_current", "_folder", "_load", "_problem", "_settle", "_watcher")
    """Qt connects bound methods through a weak reference to their owner."""

    def __init__(
        self,
        folder: Path,
        load: Callable[[Path], T],
        current: T,
        apply: Callable[[T], None],
        problem: Callable[[str], None],
    ) -> None:
        self._folder, self._load, self._current = folder, load, current
        self._apply, self._problem = apply, problem
        self._settle = QtCore.QTimer()
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self.reload)
        self._watcher = QtCore.QFileSystemWatcher()
        self._watcher.directoryChanged.connect(self._changed)
        self._watcher.fileChanged.connect(self._changed)
        self._watch()

    def _watch(self) -> None:
        paths = [str(self._folder), *(str(path) for path in sorted(self._folder.glob("*.toml")))]
        watched = set(self._watcher.files()) | set(self._watcher.directories())
        if missing := [path for path in paths if path not in watched]:
            self._watcher.addPaths(missing)

    def _changed(self, _: str) -> None:
        self._settle.start()

    def reload(self) -> None:
        self._watch()
        try:
            loaded = self._load(self._folder)
        except SpecError as error:
            self._problem(f"The bar kept its last good spec: {error}")
            return
        if loaded != self._current:
            self._current = loaded
            self._apply(loaded)

    def close(self) -> None:
        self._settle.stop()
        if paths := self._watcher.files() + self._watcher.directories():
            self._watcher.removePaths(paths)
