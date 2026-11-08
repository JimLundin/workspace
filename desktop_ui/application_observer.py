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
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import assert_never

import protocol
from contracts.geometry import framed
from desktop_ui.navigation import Effect, Focus, Launch, Order, Placing, Switch, World, ZoomIn, ZoomOut, decide, zoom_after
from desktop_ui.shell_items import EMPTY_SHELF, WEB_APPS, Launches, PinnedApp, Shelf, caption_clip, launch, outstanding, shelf
from desktop_ui.window_layout import (
    NOWHERE,
    App,
    Placement,
    Screens,
    Setup,
    Target,
    groups,
    managed,
    place,
    reading_order,
    screens,
)
from winapi import app_user_model, screen, windows
from winapi.icon_pixels import window_pixels
from winapi.processes import edge_path
from winapi.shapes import Window
from winapi.virtual_desktops import Desktops, VirtualDesktops

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


type Connection = VirtualDesktops | None
"""The worker's connection to the shell's virtual desktops; None until it connects, and again after it fails."""


def connected(connection: Connection) -> Connection:
    if connection is None:
        with suppress(OSError):  # Another Windows build, or Explorer restarting: try again next poll.
            return VirtualDesktops.connect()
    return connection


def disconnected(connection: Connection) -> None:
    if connection is not None:
        connection.close()


def observe(connection: Connection) -> tuple[Connection, Observed]:
    """Other desktops' windows are cloaked; the shell's own cloaked hosts are on no desktop and stay out."""
    connection = connected(connection)
    try:
        state = connection.observe() if connection is not None else None
    except OSError:
        connection = disconnected(connection)
        state = None
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
    return connection, Observed(
        tuple(window for window, _ in shown), frozendict((window.handle, index) for window, index in shown if index is not None), state
    )


def arrange(connection: Connection, observed: Observed, placement: Placement, slots: frozenset[int], *, follow: int) -> Connection:
    """Converge every placed window on its desktop and rectangle, creating only missing desktops.

    The window in front, `follow`, takes the user along when it moves to another desktop:
    a window just opened or brought forward on the wrong desktop is the one being worked in.
    """
    state = observed.state
    if connection is None or state is None:
        return connection
    try:
        ids = state.ids
        while len(ids) < 1 + max((target.desktop for target in placement.values()), default=-1):
            ids = (*ids, connection.create())
    except OSError:
        return disconnected(connection)
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
    return connection


def show(connection: Connection, handle: int) -> None:
    """Bring a window forward, first switching to its desktop when it's on another one."""
    if connection is not None:
        with suppress(OSError):
            current, place_id = connection.observe().current, connection.window_desktop(handle)
            if place_id is not None and place_id != current:
                connection.switch(place_id)
    focus(handle)


def switch(connection: Connection, index: int) -> tuple[Connection, bool]:
    if connection is None:
        return None, False
    try:
        ids = connection.ids()
        if index < len(ids):
            connection.switch(ids[index])
            return connection, True
    except OSError:
        return disconnected(connection), False
    return connection, False


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


@dataclass(frozen=True, slots=True)
class ApplicationObserver:
    """One worker owns native polling, placement, desktops, navigation and slot-window regions; callers receive immutable snapshots."""

    problem: Callable[[str], None]
    results: queue.Queue[Arrangement] = field(default_factory=lambda: queue.Queue[Arrangement](maxsize=1))
    requests: queue.Queue[Order | None] = field(default_factory=queue.Queue[Order | None])
    """Navigation and placement orders; None only wakes the worker to stop."""
    stop: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    """Set when the worker thread exits."""

    @classmethod
    def start(cls, problem: Callable[[str], None]) -> ApplicationObserver:
        observer = cls(problem)
        threading.Thread(target=observer.run, name="application icons", daemon=True).start()
        return observer

    def order(self, order: Order) -> None:
        self.requests.put(order)

    def run(self) -> None:
        try:
            with app_user_model.apartment():
                Worker(self).run()
        finally:
            self.finished.set()

    def close(self) -> None:
        self.stop.set()
        self.requests.put(None)
        self.finished.wait(timeout=5)


@dataclass(frozen=True, slots=True)
class _Watched:
    framed: frozenset[int] = frozenset()
    previous: Arrangement = EMPTY_ARRANGEMENT
    placement: Placement = NOWHERE
    paused: bool = False
    zoomed: int | None = None
    recent: tuple[int, ...] = ()
    launches: Launches = frozendict()
    world: World | None = None
    setup: Setup | None = None
    where: Screens | None = None
    connection: Connection = None


@dataclass(frozen=True, slots=True)
class Worker:
    """The observer thread's work: each step takes what it has watched so far and returns what it watches now.

    The thread's loop holds that record (`_Watched`); nothing else sees it.
    """

    observer: ApplicationObserver

    def run(self) -> None:
        watched = _Watched()
        try:
            while not self.observer.stop.is_set():
                watched = self.poll(watched)
                with suppress(queue.Empty):
                    while (order := self.observer.requests.get(timeout=1)) is not None:
                        watched, more = self.carry(watched, order)
                        if not more:
                            break
        finally:
            release(watched.framed)
            disconnected(watched.connection)

    def poll(self, watched: _Watched) -> _Watched:
        connection, observed = observe(watched.connection)
        # Only Edge hosts pinned web apps, which bounds the per-second property reads.
        app_ids = frozendict((window.handle, app_user_model.app_id(window.handle)) for window in observed.windows if window.exe == "msedge.exe")
        own = os.getpid()
        grouped = shelf(observed.windows, app_ids, watched.previous.shelf)
        slots = tuple(window for pinned in grouped.pinned for window in pinned.windows)
        current = frozenset(window.handle for window in slots)
        foreground = windows.foreground()
        zoomed = zoom_after(watched.zoomed, foreground)
        state = observed.state
        where = screens(screen.monitors())
        placement = watched.placement
        if where is not None and state is not None:
            eligible = frozenset(
                window.handle
                for window in observed.windows
                if managed(window, resizable=windows.resizable(window.handle), own=windows.process_id(window.handle) == own)
            )
            placement = place(where, groups(grouped, eligible), placement)
            if not watched.paused and not windows.dragging():  # A window being dragged snaps back once it's let go.
                kept = frozendict((handle, target) for handle, target in placement.items() if handle != zoomed)
                connection = arrange(connection, observed, kept, current, follow=foreground)
        for window in slots:
            if not window.minimized:
                frame(window.handle)
        release(watched.framed - current)
        live = frozenset(window.handle for window in observed.windows)
        candidates = tuple(handle for handle in (foreground, *watched.recent) if handle in placement and handle in live)
        recent = tuple(handle for index, handle in enumerate(candidates) if handle not in candidates[:index])[:RECENT]
        world = World(
            len(state.ids) if state is not None else 1,
            state.ids.index(state.current) if state is not None else 0,
            foreground,
            frozendict((group.app, group.windows) for group in groups(grouped, live)),
            observed.desktops,
            placement,
            recent,
            zoomed,
        )
        return self.publish(
            replace(
                watched,
                connection=connection,
                launches=outstanding(watched.launches, grouped),
                zoomed=zoomed,
                setup=where.setup if where is not None else None,
                where=where,
                placement=placement,
                framed=current,
                recent=recent,
                world=world,
            ),
            grouped,
            state,
        )

    @staticmethod
    def placed(watched: _Watched, desktops: int) -> tuple[tuple[App, ...], ...]:
        if (world := watched.world) is None:
            return tuple(() for _ in range(desktops))
        return tuple(reading_order(watched.where, world.windows, watched.placement, index) for index in range(desktops))

    def publish(self, watched: _Watched, grouped: Shelf, state: Desktops | None) -> _Watched:
        stop = self.observer.stop
        running = tuple(
            replace(app, image=window_pixels(app.windows[0].handle))
            if not stop.is_set() and all(old.identity != app.identity for old in watched.previous.shelf.running)
            else app
            for app in grouped.running
        )
        desktops, current = (len(state.ids), state.ids.index(state.current)) if state is not None else (0, 0)
        snapshot = Arrangement(
            replace(grouped, running=running), desktops, current, self.placed(watched, desktops), paused=watched.paused, world=watched.world
        )
        if snapshot != watched.previous:
            with suppress(queue.Empty):
                self.observer.results.get_nowait()
            self.observer.results.put_nowait(snapshot)
        return replace(watched, previous=snapshot)

    def carry(self, watched: _Watched, order: Order) -> tuple[_Watched, bool]:
        """Carry out one order; False when the next poll should run first."""
        match order:
            case Placing.TOGGLE_PAUSE:
                return replace(watched, paused=not watched.paused), False
            case Placing.NOW:
                return replace(watched, paused=False, zoomed=None), False
            case _:
                if (world := watched.world) is None:
                    return watched, False
                fresh = replace(world, foreground=windows.foreground())
                chosen, record = decide(order, fresh)
                watched = self.effect(watched, chosen)
                return replace(watched, world=replace(fresh, current=record.to_desktop)), True

    def effect(self, watched: _Watched, chosen: Effect) -> _Watched:
        match chosen:
            case Focus(window=window):
                show(watched.connection, window)
                return watched
            case Switch(desktop=index, then=then):
                connection, switched = switch(watched.connection, index)
                if switched and then is not None:
                    focus(then)
                return replace(watched, connection=connection)
            case Launch(app=app):
                return self.start(watched, app)
            case ZoomIn(window=window):
                if (target := watched.placement.get(window)) is not None:
                    resize(window, Target(target.desktop, screen.monitor_of(window).work), slot=window in watched.framed)
                return replace(watched, zoomed=window)
            case ZoomOut(window=window):
                if (target := watched.placement.get(window)) is not None:
                    resize(window, target, slot=window in watched.framed)
                return replace(watched, zoomed=None)
            case None:
                return watched
            case _:
                assert_never(chosen)

    def start(self, watched: _Watched, app: protocol.Installed | PinnedApp) -> _Watched:
        match app:
            case protocol.Installed(command=command):
                try:
                    os.startfile(command)  # as the Run dialog would: program names, paths, URLs
                except OSError:
                    subprocess.Popen(["cmd", "/c", "start", "", command], creationflags=_CREATE_NO_WINDOW)
                return watched
            case PinnedApp():
                return self.open_web_app(watched, app)
            case _:
                assert_never(app)

    def open_web_app(self, watched: _Watched, app: PinnedApp) -> _Watched:
        """Edge opens the slot's app window in the user's own profile; a repeated launch waits for it."""
        pending = launch(watched.launches, app, time.monotonic())
        if pending is None:
            return watched
        edge = edge_path()
        if edge is None:
            self.observer.problem(f"Microsoft Edge is needed to open {WEB_APPS[app].label}.")
            return watched
        try:
            os.startfile(edge, arguments=f"--app={WEB_APPS[app].url}")
        except OSError as error:
            self.observer.problem(f"Could not open {WEB_APPS[app].label}: {error}")
            return watched
        return replace(watched, launches=pending)
