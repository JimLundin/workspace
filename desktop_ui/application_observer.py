"""Observe app windows, copy icons away from Qt's animation/audio thread and hide
pinned web-app windows' captions."""

import queue
import threading
from contextlib import suppress
from dataclasses import replace

from desktop_ui.shell_items import EMPTY_SHELF, Shelf, caption_clip, shelf
from winapi import app_user_model, windows
from winapi.icon_pixels import window_pixels


def frame(window: int) -> None:
    """Converge a slot window's region on hiding its caption; Edge keeps an applied region across resizes."""
    caption = windows.caption_buttons(window)
    if caption is not None and (clip := caption_clip(windows.outer_rect(window), caption, windows.region(window))) is not None:
        windows.set_region(window, clip)


def release(handles: frozenset[int]) -> None:
    """Windows that are no longer slots, or outlive Workspace, get their captions back."""
    for handle in handles:
        if windows.exists(handle):
            windows.set_region(handle, None)


class ApplicationObserver:
    """One worker owns native polling and slot-window regions; callers receive immutable shelf snapshots."""

    __slots__ = ("results", "stop", "thread")

    def __init__(self) -> None:
        self.results: queue.Queue[Shelf] = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="application icons", daemon=True)
        self.thread.start()

    def run(self) -> None:
        framed: frozenset[int] = frozenset()
        with app_user_model.apartment():
            try:
                previous = EMPTY_SHELF
                while not self.stop.is_set():
                    observed = windows.windows()
                    # Only Edge hosts pinned web apps, which bounds the per-second property reads.
                    app_ids = frozendict((window.handle, app_user_model.app_id(window.handle)) for window in observed if window.exe == "msedge.exe")
                    grouped = shelf(observed, app_ids, previous)
                    slots = tuple(window for pinned in grouped.pinned for window in pinned.windows)
                    for window in slots:
                        if not window.minimized:
                            frame(window.handle)
                    current = frozenset(window.handle for window in slots)
                    release(framed - current)
                    framed = current
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
            finally:
                release(framed)

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5)
