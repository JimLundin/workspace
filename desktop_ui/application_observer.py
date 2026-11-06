"""Observe app windows on every virtual desktop, place them where the layout
declares, carry out and log navigation, copy icons away from Qt's animation/audio
thread and hide pinned web-app windows' captions.

One worker owns all of it: placement moves and resizes the same windows whose
regions hide their captions and that navigation focuses, zooms and launches, so a
second owner would race the first.
"""

import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import assert_never

import protocol
from assistant.browser_session import edge_path
from assistant.geometry import framed
from desktop_ui.navigation import Effect, Focus, Launch, Order, Placing, Switch, World, ZoomIn, ZoomOut, decide, owner, zoom_after
from desktop_ui.navigation_log import NAVIGATION_LOG, START, Arrival, Entry, Moment, Tracker, append, arrived, navigated, noticed, seen, settled
from desktop_ui.shell_items import EMPTY_SHELF, WEB_APPS, Launches, PinnedApp, Shelf, caption_clip, launch, outstanding, shelf
from desktop_ui.window_layout import (
    CANVAS_TITLE,
    NOWHERE,
    App,
    Group,
    Placement,
    Program,
    Setup,
    Target,
    WorkspaceView,
    groups,
    managed,
    place,
    reading_order,
    screens,
)
from winapi import app_user_model, screen, windows
from winapi.icon_pixels import window_pixels
from winapi.shapes import Window
from winapi.virtual_desktops import Desktops, VirtualDesktops
from winapi.win_events import CaptureStart, Foreground, SwitchEnd, SwitchStart, WinEvent, WinEvents

_CREATE_NO_WINDOW = 0x0800_0000
RECENT = 32
"""Windows remembered as last in front, for landing on a desktop."""


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
    if windows.is_maximized(handle) or windows.is_minimized(handle):
        windows.show(handle, windows.SW_SHOWNOACTIVATE)
    outer = windows.outer_rect(handle)
    visible = windows.visible_rect(handle)
    caption = windows.caption_buttons(handle) if slot else None
    # A slot window's region hides everything above its caption buttons' bottom edge.
    drawn = replace(visible, top=outer.top + caption.bottom) if caption is not None else visible
    wanted = framed(target.rect, outer, drawn)
    if wanted != outer:
        windows.move(handle, wanted)


def focus(handle: int) -> None:
    """Desktop switches animate; the window can take the keyboard once the switch lets it."""
    for _ in range(10):
        if windows.focus(handle):
            return
        time.sleep(0.05)


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
        ids = state.ids if state is not None else ()
        found = tuple(
            (window, ids.index(place_id) if connection is not None and (place_id := connection.window_desktop(window.handle)) in ids else None)
            for window in windows.windows(include_cloaked=True)
        )
        shown = tuple(
            (window, index)
            for window, index in found
            if not windows.cloaked(window.handle) or (state is not None and index is not None and ids[index] != state.current)
        )
        return Observed(
            tuple(window for window, _ in shown), frozendict((window.handle, index) for window, index in shown if index is not None), state
        )

    def arrange(self, observed: Observed, placement: Placement, slots: frozenset[int], *, follow: int) -> None:
        """Converge every placed window on its desktop and rectangle, creating only missing desktops.

        The window in front, `follow`, takes the user along when it moves to another desktop:
        a window just opened or brought forward on the wrong desktop is the one being worked in.
        """
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
        followed: int | None = None
        for handle, target in placement.items():
            with suppress(OSError):  # A window that closed or refuses a move is tried again next poll.
                if observed.desktops.get(handle) != target.desktop:
                    connection.move(handle, ids[target.desktop])
                    if handle == follow:
                        followed = target.desktop
                resize(handle, target, slot=handle in slots)
        if followed is not None and ids[followed] != state.current:
            with suppress(OSError):
                connection.switch(ids[followed])
                focus(follow)

    def show(self, handle: int) -> None:
        """Bring a window forward, first switching to its desktop when it's on another one."""
        if (connection := self.connection) is not None:
            with suppress(OSError):
                current, place_id = connection.observe().current, connection.window_desktop(handle)
                if place_id is not None and place_id != current:
                    connection.switch(place_id)
        focus(handle)

    def switch(self, index: int) -> bool:
        if (connection := self.connection) is None:
            return False
        try:
            ids = connection.ids()
            if index < len(ids):
                connection.switch(ids[index])
                return True
        except OSError:
            self.disconnect()
        return False


@dataclass(frozen=True, slots=True)
class Arrangement:
    """What the bar shows: the applications, the desktops, whether placement is paused and the navigation world."""

    shelf: Shelf
    desktops: int
    current: int
    placed: tuple[tuple[App, ...], ...] = ()
    """Each desktop's placed applications, in shelf order."""
    paused: bool = field(default=False, kw_only=True)
    world: World | None = field(default=None, kw_only=True)
    """What navigation is decided against, so the bar's key hints name what each chord reaches."""


EMPTY_ARRANGEMENT = Arrangement(EMPTY_SHELF, 0, 0)


class ApplicationObserver:
    """One worker owns native polling, placement, desktops, navigation and slot-window regions; callers receive immutable snapshots."""

    __slots__ = ("log", "problem", "requests", "results", "stop", "thread")

    def __init__(self, problem: Callable[[str], None], log: Path = NAVIGATION_LOG) -> None:
        self.problem = problem
        self.log = log
        """The navigation log, appended only by the worker."""
        self.results: queue.Queue[Arrangement] = queue.Queue(maxsize=1)
        self.requests: queue.Queue[Order | WinEvent | None] = queue.Queue()
        """Navigation and placement orders and foreground events; None only wakes the worker to stop."""
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="application icons", daemon=True)
        self.thread.start()

    def order(self, order: Order) -> None:
        self.requests.put(order)

    def run(self) -> None:
        with app_user_model.apartment():
            Worker(self).run()

    def close(self) -> None:
        self.stop.set()
        self.requests.put(None)
        self.thread.join(timeout=5)


class Worker:
    """The observer thread's state: the last placement, zoom, pause, recent windows, pending web-app launches and focus history."""

    __slots__ = (
        "arrival",
        "desktop",
        "framed",
        "launches",
        "observer",
        "paused",
        "placement",
        "previous",
        "recent",
        "setup",
        "tracker",
        "world",
        "zoomed",
    )

    def __init__(self, observer: ApplicationObserver) -> None:
        self.observer = observer
        self.desktop = Desktop()
        self.framed: frozenset[int] = frozenset()
        self.previous = EMPTY_ARRANGEMENT
        self.placement: Placement = NOWHERE
        self.paused = False
        self.zoomed: int | None = None
        self.recent: tuple[int, ...] = ()
        self.launches: Launches = frozendict()
        self.world: World | None = None
        self.setup: Setup | None = None
        self.tracker: Tracker = START
        self.arrival: Foreground | None = None
        """A foreground change waiting for the next poll to identify its window."""

    def run(self) -> None:
        # The hooks' own thread waits for their messages; it only queues each event for this worker.
        events = WinEvents(self.observer.requests.put)
        try:
            while not self.observer.stop.is_set():
                self.poll()
                self.follow()
                with suppress(queue.Empty):
                    while (order := self.observer.requests.get(timeout=1)) is not None:
                        if not self.carry(order):
                            break
        finally:
            events.close()
            release(self.framed)
            self.desktop.disconnect()

    def moment(self, at: float) -> Moment:
        return Moment(at, datetime.now().astimezone(), self.setup)

    def write(self, entries: Iterable[Entry]) -> None:
        with suppress(OSError):  # A full or locked disk loses entries, never navigation.
            append(entries, self.observer.log)

    def follow(self) -> None:
        """Resolve a foreground change against the poll that just ran, and let pending expectations expire."""
        if (world := self.world) is not None:
            self.tracker = seen(self.tracker, world)
        if (event := self.arrival) is not None:
            self.arrival = None
            app = owner(world, event.window) if world is not None else None
            if app is None and (exe := windows.exe(event.window)):
                app = Program(exe)  # A dialog or shell surface outside the taskbar: its program, never its title.
            here = Arrival(event.window, app, world.current if world is not None else None, held=event.held)
            self.tracker, entries = arrived(self.tracker, here, self.moment(event.at))
        else:
            self.tracker, entries = settled(self.tracker, self.moment(time.monotonic()))
        self.write(entries)

    def poll(self) -> None:
        observed = self.desktop.observe()
        # Only Edge hosts pinned web apps, which bounds the per-second property reads.
        app_ids = frozendict((window.handle, app_user_model.app_id(window.handle)) for window in observed.windows if window.exe == "msedge.exe")
        own = os.getpid()
        # The canvas is Workspace's own window: placed as an app, but never a running app on the shelf.
        canvas = next((w.handle for w in observed.windows if w.title == CANVAS_TITLE and windows.process_id(w.handle) == own), None)
        views = (Group(WorkspaceView.CANVAS, (canvas,)),) if canvas is not None else ()
        grouped = shelf(tuple(w for w in observed.windows if w.handle != canvas), app_ids, self.previous.shelf)
        self.launches = outstanding(self.launches, grouped)
        slots = tuple(window for pinned in grouped.pinned for window in pinned.windows)
        current = frozenset(window.handle for window in slots)
        foreground = windows.foreground()
        self.zoomed = zoom_after(self.zoomed, foreground)
        state = observed.state
        where = screens(screen.monitors())
        self.setup = where.setup if where is not None else None
        if where is not None and state is not None:
            eligible = frozenset(
                window.handle
                for window in observed.windows
                if managed(window, resizable=windows.resizable(window.handle), own=windows.process_id(window.handle) == own)
            )
            self.placement = place(where, (*views, *groups(grouped, eligible)), self.placement)
            if not self.paused and not windows.dragging():  # A window being dragged snaps back once it's let go.
                kept = frozendict((handle, target) for handle, target in self.placement.items() if handle != self.zoomed)
                self.desktop.arrange(observed, kept, current, follow=foreground)
        for window in slots:
            if not window.minimized:
                frame(window.handle)
        release(self.framed - current)
        self.framed = current
        live = frozenset(window.handle for window in observed.windows)
        candidates = tuple(handle for handle in (foreground, *self.recent) if handle in self.placement and handle in live)
        self.recent = tuple(handle for index, handle in enumerate(candidates) if handle not in candidates[:index])[:RECENT]
        self.world = World(
            len(state.ids) if state is not None else 1,
            state.ids.index(state.current) if state is not None else 0,
            foreground,
            frozendict((group.app, group.windows) for group in (*views, *groups(grouped, live))),
            observed.desktops,
            self.placement,
            self.recent,
            self.zoomed,
        )
        self.publish(grouped, state)

    def placed(self, desktops: int) -> tuple[tuple[App, ...], ...]:
        world = self.world
        if world is None:
            return tuple(() for _ in range(desktops))
        return tuple(reading_order(world.windows, self.placement, index) for index in range(desktops))

    def publish(self, grouped: Shelf, state: Desktops | None) -> None:
        stop = self.observer.stop
        running = tuple(
            replace(app, image=window_pixels(app.windows[0].handle))
            if not stop.is_set() and all(old.identity != app.identity for old in self.previous.shelf.running)
            else app
            for app in grouped.running
        )
        desktops, current = (len(state.ids), state.ids.index(state.current)) if state is not None else (0, 0)
        snapshot = Arrangement(replace(grouped, running=running), desktops, current, self.placed(desktops), paused=self.paused, world=self.world)
        if snapshot != self.previous:
            with suppress(queue.Empty):
                self.observer.results.get_nowait()
            self.observer.results.put_nowait(snapshot)
        self.previous = snapshot

    def carry(self, order: Order | WinEvent) -> bool:
        """Carry out one order; False when the next poll should run first."""
        match order:
            case Foreground():
                self.arrival = order
                return False
            case CaptureStart() | SwitchStart() | SwitchEnd():
                self.tracker = noticed(self.tracker, order)
                return True
            case Placing.TOGGLE_PAUSE:
                self.paused = not self.paused
                return False
            case Placing.NOW:
                self.paused, self.zoomed = False, None
                return False
            case _:
                if (world := self.world) is None:
                    return False
                fresh = replace(world, foreground=windows.foreground())
                chosen, record = decide(order, fresh)
                self.tracker, entries = navigated(self.tracker, (chosen, record), self.moment(time.monotonic()))
                self.effect(chosen)
                self.write(entries)
                self.world = replace(fresh, current=record.to_desktop)
                return True

    def effect(self, chosen: Effect) -> None:
        match chosen:
            case Focus(window=window):
                self.desktop.show(window)
            case Switch(desktop=index, then=then):
                if self.desktop.switch(index) and then is not None:
                    focus(then)
            case Launch(app=app):
                self.start(app)
            case ZoomIn(window=window):
                self.zoomed = window
                if (target := self.placement.get(window)) is not None:
                    resize(window, Target(target.desktop, screen.monitor_of(window).work), slot=window in self.framed)
            case ZoomOut(window=window):
                self.zoomed = None
                if (target := self.placement.get(window)) is not None:
                    resize(window, target, slot=window in self.framed)
            case None:
                pass
            case _:
                assert_never(chosen)

    def start(self, app: protocol.Installed | PinnedApp) -> None:
        match app:
            case protocol.Installed(command=command):
                try:
                    os.startfile(command)  # as the Run dialog would: program names, paths, URLs
                except OSError:
                    subprocess.Popen(["cmd", "/c", "start", "", command], creationflags=_CREATE_NO_WINDOW)
            case PinnedApp():
                self.open_web_app(app)
            case _:
                assert_never(app)

    def open_web_app(self, app: PinnedApp) -> None:
        """Edge opens the slot's app window in the user's own profile; a repeated launch waits for it."""
        pending = launch(self.launches, app, time.monotonic())
        if pending is None:
            return
        edge = edge_path()
        if edge is None:
            self.observer.problem(f"Microsoft Edge is needed to open {WEB_APPS[app].label}.")
            return
        try:
            os.startfile(edge, arguments=f"--app={WEB_APPS[app].url}")
        except OSError as error:
            self.observer.problem(f"Could not open {WEB_APPS[app].label}: {error}")
            return
        self.launches = pending
