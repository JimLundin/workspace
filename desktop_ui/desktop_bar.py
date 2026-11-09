"""The island bar: Workspace's floating capsules at the top of the primary screen.

Activity sits just left of the status capsule and acts on what it shows;
persistent navigation and status anchor right; the system tray lives in the
controls menu. `island_model` decides the views, `island_layout` where they sit,
and `ui_components.appearance` how they read. This owner observes the desktop and
publishes each result to the one bar window and its glass.
"""

import math
import queue
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from typing import assert_never
lazy import os

lazy from PySide6 import QtCore, QtGui

from cell import Cell
from desktop_ui.qt_runtime import prepare
lazy import desktop_ui.components.appearance
lazy import winapi.ambient
lazy from config import APPS
lazy from contracts.recording_state import RecordingAction
lazy from desktop_ui.ambient import Ambient
lazy from desktop_ui.application_observer import ApplicationObserver, Arrangement
lazy from desktop_ui.audio_meter import AudioMeter
lazy from desktop_ui.away_screens import AwayScreens
lazy from desktop_ui.bar_events import (
    AllControls,
    BarModel,
    BarSpec,
    ClickTray,
    Closing,
    Deactivated,
    Effect,
    Event,
    Expand,
    Framed,
    Keyboard,
    Navigate,
    NotificationSettings,
    Opening,
    Overlay,
    Record,
    Release,
    Render,
    Retargeted,
    Sampled,
    SetVolume,
    ShowHints,
    Surroundings,
    Ticked,
    ToggleAway,
    UseTool,
    menu,
    next_frame,
    transition,
)
lazy from desktop_ui.bar_status import StatusObserver
lazy from desktop_ui.components.appearance import Look, look
lazy from desktop_ui.components.meaning import Tint
lazy from desktop_ui.desktop_pager import PAGER, pager
lazy from desktop_ui.island_layout import SIZES, Content, Metrics, expansion, frame, snap
lazy from desktop_ui.island_menu import CONTROLS, Menu
lazy from desktop_ui.island_model import ISLAND, CapsuleView, Key, Marker, Observed, island, order
lazy from desktop_ui.island_motion import SPRINGS, Shown, placed, retarget
lazy from desktop_ui.island_surface import BarWindow, Drawn, Presented, expanded
lazy from desktop_ui.key_hint_overlay import KeyHintOverlay
lazy from desktop_ui.key_hints import hints
lazy from desktop_ui.navigation import AppKey, CycleApp, Order, ShowWindow
lazy from desktop_ui.qt_ui import EventLoop, application
lazy from desktop_ui.shell_controls import TaskbarControl
lazy from desktop_ui.shell_items import Application, Item, Pinned, PinnedApp
lazy from desktop_ui.window_layout import App, Program
lazy from protocol import Installed, Tool
lazy from winapi import appearance, inputs, session, shell, windows
lazy from winapi.machine_status import PowerUnavailable
lazy from winapi.shapes import Rect
lazy from winapi.tray_host import Click, TrayHost

prepare()


@dataclass(frozen=True, slots=True)
class BarActions:
    record: Callable[[RecordingAction], None]
    keyboard: Callable[[], None]
    overlay: Callable[[], None]
    menu: Callable[[], None]
    problem: Callable[[str], None]
    tool: Callable[[Tool], None]


def level(value: float | None) -> float:
    """A microphone level as a wave bar's height, on a perceptual scale."""
    return min(1.0, math.log10(1 + max(0.0, value or 0.0) * 90) / math.log10(91))


@dataclass(frozen=True, slots=True)
class _Shell:
    """The production desktop's native owners: system status, shell controls and taskbar recovery."""

    status: StatusObserver
    controls: shell.AppWindow
    away: AwayScreens
    tray: TrayHost
    applications: ApplicationObserver
    hints: KeyHintOverlay
    worker: threading.Thread


@dataclass(frozen=True, slots=True, weakref_slot=True)
class DesktopBar:
    # Qt connects the timers to bound methods through a weak reference to the bar.
    """The bar's native owners and window, and the fold of everything reported to it into what it shows."""

    actions: BarActions
    taskbar: TaskbarControl
    shell: _Shell
    audio_meter: AudioMeter | None
    errors: queue.Queue[str]
    loop: EventLoop
    materials: appearance.FrostSampler
    resolution: appearance.TimerResolution
    window: BarWindow
    timer: QtCore.QTimer
    """The 100 ms desktop observation tick."""
    audio_timer: QtCore.QTimer
    """The 50 ms microphone trace while dictating."""
    _model: Cell[BarModel]

    @classmethod
    def open(cls, actions: BarActions, *, audio_level: Callable[[], float | None] | None = None) -> DesktopBar:
        # The window reports to the bar made just after it.
        def report(event: Event) -> None:
            bar.handle(event)

        errors: queue.Queue[str] = queue.Queue()
        loop = EventLoop.start(application())
        window = BarWindow(report, loop.composition)
        tick, audio = QtCore.QTimer(window), QtCore.QTimer(window)
        tick.setInterval(100)
        audio.setInterval(50)
        audio.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        seen = Surroundings(preference=appearance.preference(), ambient=Ambient(datetime.now().strftime("%H:%M"), PowerUnavailable.UNKNOWN))
        taskbar = TaskbarControl()
        bar = cls(
            actions,
            taskbar,
            _start_shell(errors, taskbar),
            None,
            errors,
            loop,
            appearance.FrostSampler(),
            appearance.TimerResolution(),
            window,
            tick,
            audio,
            Cell(BarModel(BarSpec(ISLAND, CONTROLS, SPRINGS, SIZES), seen=seen)),
        )
        try:
            bar = replace(bar, audio_meter=AudioMeter.start(audio_level) if audio_level is not None else None)
            loop.timer.timeout.connect(bar.paint)
            tick.timeout.connect(bar.tick)
            audio.timeout.connect(bar.sample_audio)
            bar.timer.start()
            bar.tick()  # The first observation renders the bar.
        except BaseException:
            bar.close()
            raise
        return bar

    # ---- what the model says ------------------------------------------------------------

    @property
    def model(self) -> BarModel:
        return self._model.get()

    # ---- the fold ----------------------------------------------------------------------

    def handle(self, event: Event) -> None:
        """Qt thread: fold `event` into the model and perform its effects in order."""
        if self.model.closed and not isinstance(event, Closing):
            return
        model, effects = transition(self.model, event)
        self._model.set(model)
        for effect in effects:
            self._perform(effect)

    def _perform(self, effect: Effect) -> None:
        match effect:
            case Render():
                self.render()
            case Expand(opened, remember):
                target = windows.foreground() if remember else None
                windows.allow_activation(int(self.window.winId()), allowed=True)
                self.window.activateWindow()
                self.window.setFocus()
                self.handle(Opening(opened, target))
            case Release(target):
                windows.allow_activation(int(self.window.winId()), allowed=False)
                if target:
                    windows.focus(target)
            case Record(action=recording):
                self.actions.record(recording)
            case Keyboard():
                self.actions.keyboard()
            case Overlay():
                self.actions.overlay()
            case AllControls():
                self.actions.menu()
            case UseTool(tool):
                self.actions.tool(tool)
            case Navigate(order):
                self.navigate(order)
            case ToggleAway():
                self.shell.away.toggle()
            case NotificationSettings():
                os.startfile("ms-settings:notifications")
            case SetVolume(level):
                self.shell.status.set_volume(level)
            case ClickTray(slot, click):
                entries = self.window.tray
                if slot < len(entries):
                    self.shell.tray.click(entries[slot], click, inputs.cursor_position())
            case ShowHints():
                self._show_hints()
            case _:
                assert_never(effect)

    def _show_hints(self) -> None:
        """The hints follow the window in front, which can change while the chord is held."""
        model = self.model
        world = model.seen.arrangement.world
        if not model.chord_held or world is None:
            self.shell.hints.show((), model.seen.preference)
            return
        self.shell.hints.show(hints(replace(world, foreground=windows.foreground())), model.seen.preference)

    # ---- measuring and painting ----------------------------------------------------------

    def _measure(self, view: CapsuleView, opened: Menu | None, spec: BarSpec) -> Content:
        if opened is not None and view.key is Key.STATUS:
            return expansion(opened, self.window.measure(view), spec.sizes.menu)
        return self.window.measure(view)

    def render(self) -> None:
        """Retarget the capsules at what the bar should show now, then paint; frames carry them there."""
        model = self.model
        opened = menu(model) if model.opened is not None else None
        observed = Observed(
            model.job, model.recording, model.seen.ambient, model.seen.system, plain_keyboard=not model.layout_enabled, dictating=model.dictating
        )
        views = island(observed, model.spec.island, hovered=model.hovered, expanded=opened is not None)
        shown = tuple(Shown(view, self._measure(view, opened, model.spec)) for view in views)
        motion = retarget(model.motion, shown, model.spec.springs, animate=appearance.animations_enabled())
        listening = model.dictating
        if listening and not self.audio_timer.isActive():
            self.window.samples.extend(0.0 for _ in range(len(self.window.samples)))
            self.window.wave_from = tuple(self.window.samples)
            self.window.wave_progress = 1.0
            self.audio_timer.start()
        elif not listening:
            self.audio_timer.stop()
        if self.audio_meter is not None:
            self.audio_meter.listen(enabled=listening)
        self.window.setVisible(True)
        self.handle(Retargeted(views, motion, opened))
        self.paint()

    def _draw(self, model: BarModel) -> None:
        seen, sizes = model.seen, model.spec.sizes
        metrics = Metrics(seen.screen.width, sizes.bar.top, sizes.bar.gap, sizes.bar.edge)
        framed = frozendict(
            (each.key, each) for each in snap(frame(placed(model.motion, sizes.capsule.height), metrics, order(model.spec.island)), seen.scale)
        )
        match seen.preference:
            case appearance.Contrast():
                contrast = True
            case appearance.Material.GLASS | appearance.Material.SOLID:
                contrast = False
            case _:
                assert_never(seen.preference)
        drawn = tuple(
            Drawn(
                moving.view,
                moving.content,
                moving.previous,
                moving.fade.value,
                _style(seen, moving.view.tint, moving.content.height),
                framed[moving.key],
            )
            for moving in model.motion.capsules
            if moving.key in framed
        )
        # The window keeps the room a capsule is heading for, so it resizes only as an expansion starts and settles.
        reach = max((max(moving.height.value, moving.height.target) for moving in model.motion.capsules), default=float(sizes.capsule.height))
        self.window.present(
            Presented(
                drawn,
                reach,
                model.opened,
                seen.screen,
                seen.scale,
                frost=seen.frost,
                contrast=contrast,
                glass=seen.preference is appearance.Material.GLASS,
                shell_look=_style(seen, Tint.NONE, sizes.capsule.height),
            )
        )
        # A closed menu keeps the last locations: a clicked application anchors its flyout where its icon was.
        if model.opened is not None:
            self.shell.tray.locate(self.window.tray_locations())

    def paint(self) -> None:
        """Paint the next frame."""
        model = self.model
        if model.closed:
            return
        now = time.monotonic()
        drawn = next_frame(model, now, animate=appearance.animations_enabled())
        self.window.wave_progress = drawn.wave_progress
        self.window.spin_angle = drawn.spin_angle
        self._draw(replace(model, motion=drawn.motion))
        if drawn.indicators:
            for key, capsule in self.window.capsules.items():
                if key in (Key.ISLAND, Key.STATUS, Key.JOB):
                    capsule.update_indicators()
        self.resolution.update(active=drawn.running)
        self.loop.watch(visible=drawn.running)
        self.handle(Framed(drawn.motion, now if drawn.running else None))

    def tick(self) -> None:
        """Observe the desktop, the shell and the system."""
        model = self.model
        if model.closed:
            return
        try:
            self.taskbar.enforce()
        except OSError as error:
            self.errors.put(str(error))
        while not self.errors.empty():
            self.actions.problem(self.errors.get_nowait())
        self.shell.away.poll(recording=model.recording.capturing)
        now = time.monotonic()
        seen = model.seen
        arrangement = self._poll_shell(model)
        power, next_power = (winapi.ambient.power(), now + 15) if now >= model.next_power else (seen.ambient.power, model.next_power)
        system = seen.system
        with suppress(queue.Empty):
            system = self.shell.status.results.get_nowait()
        sample_bounds = self.window.bounds(Key.ISLAND) or self.window.bounds(Key.STATUS)
        # Small glass takes its scheme from the desktop beside the island.
        frost = next((sample.frost for sample in self.materials.read() if sample.bounds == sample_bounds), seen.frost)
        preference, next_material = seen.preference, model.next_material
        if now >= model.next_material:
            preference, next_material = appearance.preference(), now + 0.75
            if preference is appearance.Material.GLASS and sample_bounds is not None:
                self.materials.submit((sample_bounds,))
        area = QtGui.QGuiApplication.primaryScreen().geometry()
        observed = Surroundings(
            system,
            Ambient(datetime.now().strftime("%H:%M"), power),
            preference,
            frost,
            arrangement,
            dark_when_away=self.shell.away.setting.enabled,
            tray_tips=tuple(entry.tip or "Tray application" for entry in self.window.tray),
            screen=Rect(area.x(), area.y(), area.x() + area.width(), area.y() + area.height()),
            scale=self.window.devicePixelRatioF(),
        )
        self.handle(Ticked(observed, next_power, next_material))

    def _poll_shell(self, model: BarModel) -> Arrangement:
        self.window.show_tray(self.shell.tray.poll())  # The tick's render rebuilds an open menu's tray cells.
        arrangement = model.seen.arrangement
        with suppress(queue.Empty):
            arrangement = self.shell.applications.results.get_nowait()
        pager_bar = self.window.pager
        pager_bar.remember_icons(arrangement.shelf)
        # Changed pager targets must also publish section geometry when the island is still,
        # or a pager that loses its hints keeps its wider capsule.
        if pager_bar.desktops(pager(arrangement.placed, arrangement.current, PAGER, chord=model.chord_held), self.navigate, self.app_click):
            self.window.presentation = None
        if model.chord_held:
            self._show_hints()
        return arrangement

    def sample_audio(self) -> None:
        """Sample the microphone for the dictation trace."""
        model = self.model
        if model.closed or not model.dictating:
            return
        # Begin at the last painted interpolation, including if a sample
        # arrives early. The bounded history stays with its Qt paint owner.
        self.window.wave_from = tuple(self.window.trace())
        self.window.samples.append(level(self.audio_meter.level() if self.audio_meter is not None else None))
        self.window.wave_progress = 0.0 if appearance.animations_enabled() else 1.0
        capsule = self.window.capsules.get(Key.ISLAND)
        if capsule is not None and any(Marker.WAVE in slot for view in model.views for slot in view.slots):
            capsule.update_indicators()
        self.handle(Sampled(time.monotonic()))

    def app_click(self, app: App, click: Click) -> None:
        """A pager icon: go to the app, cycling its windows or starting it; right-click lists its windows."""
        shelf = self.model.seen.arrangement.shelf
        match app:
            case PinnedApp():
                self._application_click(next((slot for slot in shelf.pinned if slot.app is app), Pinned(app, ())), click)
            case Program(exe=exe):
                running = next((each for each in shelf.running if each.identity == exe), None)
                if running is not None and click is Click.RIGHT:
                    self._application_click(running, click)
                elif click is not Click.RIGHT:
                    self.handle(Deactivated())
                    # A configured app key also starts the app when it isn't running.
                    key = next((each for each in APPS if isinstance(each.target, Installed) and each.target.exe.lower() == exe), None)
                    self.navigate(AppKey(key) if key is not None else CycleApp(app))
            case _:
                assert_never(app)

    def _application_click(self, item: Item, click: Click) -> None:
        self.handle(Deactivated())
        match item:
            case Pinned(windows=listed) | Application(windows=listed) if listed and click is Click.RIGHT:
                chosen = shell.show_menu(int(self.window.winId()), tuple(shell.MenuItem(window.handle, window.title) for window in listed))
                if chosen:
                    self.navigate(ShowWindow(chosen))
            case Pinned(app=app):
                self.navigate(CycleApp(app))
            case Application(identity=identity):
                self.navigate(CycleApp(Program(identity)))

    # ---- what others tell the bar ------------------------------------------------------

    def navigate(self, order: Order) -> None:
        """The application observer owns windows and desktops; it carries out every navigation."""
        if not self.model.closed:
            self.shell.applications.order(order)

    def close(self) -> None:
        if self.model.closed:
            return
        self.handle(Closing())
        self.timer.stop()
        self.audio_timer.stop()
        if self.audio_meter is not None:
            self.audio_meter.close()
        self.materials.close()
        built = self.shell
        built.hints.close()
        built.status.close()
        built.tray.close()
        built.applications.close()
        try:
            self.taskbar.close()
            built.worker.join(timeout=6)
        finally:
            built.away.close()
            session.unsubscribe(built.controls.handle)
            built.controls.destroy()
            self.resolution.update(active=False)
            self.window.dispose()
            self.loop.close()


def _start_shell(errors: queue.Queue[str], taskbar: TaskbarControl) -> _Shell:
    status = StatusObserver.start()
    away = AwayScreens.start()

    def message(_hwnd: int, message: int, wparam: int, _lparam: int) -> int | None:
        away.message(message, wparam)
        return None

    controls = shell.AppWindow.create("workspace shell controls", message)
    try:
        session.subscribe(controls.handle)
    except OSError as error:
        errors.put(f"Screens can't go dark when locked: {error}")
    worker = threading.Thread(target=_start_taskbar, args=(taskbar, errors), name="taskbar recovery", daemon=True)
    built = _Shell(status, controls, away, TrayHost.start(), ApplicationObserver.start(errors.put), KeyHintOverlay(), worker)
    worker.start()
    return built


def _start_taskbar(taskbar: TaskbarControl, errors: queue.Queue[str]) -> None:
    try:
        taskbar.start()
    except OSError as error:
        errors.put(str(error))


def _style(seen: Surroundings, tint: Tint, height: float) -> Look:
    pane = desktop_ui.components.appearance.Menu(seen.frost) if expanded(height) else desktop_ui.components.appearance.Capsule(seen.frost)
    return look(seen.preference, pane, tint)
