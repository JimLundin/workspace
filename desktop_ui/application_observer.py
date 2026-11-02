"""Observe app windows and copy icons away from Qt's animation/audio thread."""

import queue
import threading
from contextlib import suppress
from dataclasses import replace

from desktop_ui.shell_items import Application, applications
from winapi import windows
from winapi.icon_pixels import window_pixels


class ApplicationObserver:
    """One worker owns native polling; callers receive immutable app snapshots."""

    __slots__ = ("results", "stop", "thread")

    def __init__(self) -> None:
        self.results: queue.Queue[tuple[Application, ...]] = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="application icons", daemon=True)
        self.thread.start()

    def run(self) -> None:
        previous: tuple[Application, ...] = ()
        while not self.stop.is_set():
            grouped = applications(windows.windows(), previous)
            snapshot = tuple(
                replace(app, image=window_pixels(app.windows[0].handle))
                if not self.stop.is_set() and all(old.identity != app.identity for old in previous)
                else app
                for app in grouped
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
