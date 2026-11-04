"""Observe app windows on every virtual desktop, place them where the layout
declares, copy icons away from Qt's animation/audio thread and hide pinned web-app
windows' captions.

One worker owns all of it: placement moves and resizes the same windows whose
regions hide their captions, so a second owner would race the first.
"""

import os
import queue
import threading
from contextlib import suppress
from dataclasses import dataclass, replace

from assistant.geometry import framed
from desktop_ui.shell_items import EMPTY_SHELF, Shelf, caption_clip, shelf
from desktop_ui.window_layout import NOWHERE, Placement, Target, groups, managed, place, screens
from winapi import app_user_model, screen, windows
from winapi.icon_pixels import window_pixels
from winapi.shapes import Window
from winapi.virtual_desktops import Desktops, VirtualDesktops


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


def resize(handle: int, target: Target, *, slot: bool) -> None:
    """Draw the window exactly over its target; a window already there is not touched."""
    if windows.is_maximized(handle):
        windows.show(handle, windows.SW_SHOWNOACTIVATE)
    outer = windows.outer_rect(handle)
    visible = windows.visible_rect(handle)
    caption = windows.caption_buttons(handle) if slot else None
    # A slot window's region hides everything above its caption buttons' bottom edge.
    drawn = replace(visible, top=outer.top + caption.bottom) if caption is not None else visible
    wanted = framed(target.rect, outer, drawn)
    if wanted != outer:
        windows.move(handle, wanted)


@dataclass(frozen=True, slots=True)
class Observed:
    """Taskbar windows on every desktop, front to back, and the desktop index of each one on a known desktop."""

    windows: tuple[Window, ...]
    desktops: frozendict[int, int]
    state: Desktops | None


class Desktop:
    """The worker's connection to the shell's virtual desktops, reconnected after it fails."""

    __slots__ = ("connection",)

    def __init__(self) -> None:
        self.connection: VirtualDesktops | None = None

    def connected(self) -> VirtualDesktops | None:
        if self.connection is None:
            with suppress(OSError):  # Another Windows build, or Explorer restarting: try again next poll.
                self.connection = VirtualDesktops()
        return self.connection

    def disconnect(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def observe(self) -> Observed:
        """Other desktops' windows are cloaked; the shell's own cloaked hosts are on no desktop and stay out."""
        connection = self.connected()
        try:
            state = connection.observe() if connection is not None else None
        except OSError:
            self.disconnect()
            connection, state = None, None
        listed = windows.windows(include_cloaked=True)
        ids = state.ids if state is not None else ()
        found = tuple(
            (window, ids.index(place_id) if (place_id := connection.window_desktop(window.handle)) in ids else None)
            if connection is not None
            else (window, None)
            for window in listed
        )
        shown = tuple(
            (window, index)
            for window, index in found
            if not windows.cloaked(window.handle) or (state is not None and index is not None and ids[index] != state.current)
        )
        return Observed(
            tuple(window for window, _ in shown), frozendict((window.handle, index) for window, index in shown if index is not None), state
        )

    def arrange(self, observed: Observed, placement: Placement, slots: frozenset[int]) -> None:
        """Converge every placed window on its desktop and rectangle, creating only missing desktops."""
        connection, state = self.connection, observed.state
        if connection is None or state is None:
            return
        try:
            ids = state.ids
            while len(ids) < 1 + max((target.desktop for target in placement.values()), default=-1):
                ids = (*ids, connection.create())
        except OSError:
            self.disconnect()
            return
        for handle, target in placement.items():
            with suppress(OSError):  # A window that closed or refuses a move is tried again next poll.
                if observed.desktops.get(handle) != target.desktop:
                    connection.move(handle, ids[target.desktop])
                resize(handle, target, slot=handle in slots)

    def show(self, handle: int) -> None:
        """Bring a window forward, first switching to its desktop when it's on another one."""
        if (connection := self.connection) is not None:
            with suppress(OSError):
                current, place_id = connection.observe().current, connection.window_desktop(handle)
                if place_id is not None and place_id != current:
                    connection.switch(place_id)
        windows.focus(handle)


class ApplicationObserver:
    """One worker owns native polling, placement, desktops and slot-window regions; callers receive immutable shelf snapshots."""

    __slots__ = ("requests", "results", "stop", "thread")

    def __init__(self) -> None:
        self.results: queue.Queue[Shelf] = queue.Queue(maxsize=1)
        self.requests: queue.Queue[int | None] = queue.Queue()
        """Windows to bring forward; None only wakes the worker to stop."""
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="application icons", daemon=True)
        self.thread.start()

    def show(self, handle: int) -> None:
        self.requests.put(handle)

    def run(self) -> None:
        framed_slots: frozenset[int] = frozenset()
        desktop = Desktop()
        own = os.getpid()
        with app_user_model.apartment():
            try:
                previous, placement = EMPTY_SHELF, NOWHERE
                while not self.stop.is_set():
                    observed = desktop.observe()
                    # Only Edge hosts pinned web apps, which bounds the per-second property reads.
                    app_ids = frozendict(
                        (window.handle, app_user_model.app_id(window.handle)) for window in observed.windows if window.exe == "msedge.exe"
                    )
                    grouped = shelf(observed.windows, app_ids, previous)
                    slots = tuple(window for pinned in grouped.pinned for window in pinned.windows)
                    current = frozenset(window.handle for window in slots)
                    if (where := screens(screen.monitors())) is not None and observed.state is not None:
                        eligible = frozenset(
                            window.handle
                            for window in observed.windows
                            if managed(window, resizable=windows.resizable(window.handle), own=windows.process_id(window.handle) == own)
                        )
                        placement = place(where, groups(grouped, eligible), placement)
                        if not windows.dragging():  # A window being dragged snaps back once it's let go.
                            desktop.arrange(observed, placement, current)
                    for window in slots:
                        if not window.minimized:
                            frame(window.handle)
                    release(framed_slots - current)
                    framed_slots = current
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
                    with suppress(queue.Empty):
                        if (handle := self.requests.get(timeout=1)) is not None:
                            desktop.show(handle)
            finally:
                release(framed_slots)
                desktop.disconnect()

    def close(self) -> None:
        self.stop.set()
        self.requests.put(None)
        self.thread.join(timeout=5)
