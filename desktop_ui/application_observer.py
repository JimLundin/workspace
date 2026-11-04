"""Observe app windows and copy icons away from Qt's animation/audio thread."""

import queue
import threading
from contextlib import suppress
from dataclasses import replace

from desktop_ui.shell_items import EMPTY_SHELF, Shelf, shelf
from winapi import app_user_model, windows
from winapi.icon_pixels import window_pixels


class ApplicationObserver:
    """One worker owns native polling; callers receive immutable shelf snapshots."""

    __slots__ = ("results", "stop", "thread")

    def __init__(self) -> None:
        self.results: queue.Queue[Shelf] = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="application icons", daemon=True)
        self.thread.start()

    def run(self) -> None:
        with app_user_model.apartment():
            previous = EMPTY_SHELF
            while not self.stop.is_set():
                observed = windows.windows()
                # Only Edge hosts pinned web apps, which bounds the per-second property reads.
                app_ids = frozendict((window.handle, app_user_model.app_id(window.handle)) for window in observed if window.exe == "msedge.exe")
                grouped = shelf(observed, app_ids, previous)
                snapshot = replace(
                    grouped,
                    running=tuple(
                        replace(app, image=window_pixels(app.windows[0].handle))
                        if not self.stop.is_set() and all(old.identity != app.identity for old in previous.running)
                        else app
                        for app in grouped.running
                    ),
                )
                if snapshot != previous:
                    with suppress(queue.Empty):
                        self.results.get_nowait()
                    self.results.put_nowait(snapshot)
                previous = snapshot
                self.stop.wait(1)

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5)
