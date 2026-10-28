"""Contextual desktop capsules; native glass is shared with agent messages."""
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false

import queue
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
lazy import os

lazy from PySide6 import QtCore, QtGui, QtWidgets

from assistant.qt_runtime import prepare
lazy import winapi.ambient
lazy from assistant.ambient import Ambient, Power, PowerUnavailable, Weather
lazy from assistant.audio_meter import AudioMeter
lazy from assistant.bar_button import Divider, StatusView
lazy from assistant.bar_geometry import OVERLAP
lazy from assistant.bar_model import Resting, Toolbar, toolbar
lazy from assistant.bar_status import StatusObserver
lazy from assistant.bar_surface import Pill
lazy from assistant.bar_weather import LocalWeather
lazy from assistant.icons import State
lazy from assistant.notifications import Tone
lazy from assistant.qt_ui import EventLoop, application
lazy from assistant.recording_state import RecordingAction, RecordingState
lazy from assistant.shell_controls import TASKBAR_TOGGLE, TaskbarControl, WindowsKeyObserver
lazy from assistant.system_notices import Access, NoticeKey, Observed, Unavailable
lazy from protocol import Tool
lazy from winapi import appearance, shell, windows
lazy from winapi.notifications import NotificationObserver
lazy from winapi.shapes import Rect

prepare()


@dataclass(frozen=True, slots=True)
class BarActions:
    agent: Callable[[], None]
    work: Callable[[], None]
    stop: Callable[[], None]
    record: Callable[[RecordingAction], None]
    keyboard: Callable[[], None]
    overlay: Callable[[], None]
    menu: Callable[[], None]
    problem: Callable[[str], None]
    inbox: Callable[[], None] = field(kw_only=True)
    tiling: Callable[[Tool, int], None] = lambda tool, hwnd: None
    notices: Callable[[Observed], None] = lambda _: None
    handled_notice: Callable[[NoticeKey], bool] = lambda _: False


@dataclass(frozen=True, slots=True)
class BarObservations:
    """Native facts and presentation preferences, supplied at UI composition."""

    clock: Callable[[], float] = time.monotonic
    foreground: Callable[[], int] = windows.foreground
    power: Callable[[], Power] = winapi.ambient.power
    material: Callable[[], appearance.Preference] = appearance.preference
    motion: Callable[[], bool] = appearance.animations_enabled


class DesktopBar:
    __slots__ = (
        'actions',
        'activity',
        'ambient',
        'audio_meter',
        'audio_timer',
        'capture',
        'closed',
        'controls',
        'controls_divider',
        'current_layer',
        'errors',
        'inbox',
        'inbox_divider',
        'keyboard',
        'keycaps',
        'keys',
        'layout_enabled',
        'loop',
        'materials',
        'menu',
        'menu_button',
        'next_material',
        'next_power',
        'notification_access',
        'notification_observation',
        'notification_service',
        'observations',
        'pills',
        'power',
        'preference',
        'record',
        'record_stop',
        'recording',
        'sample_bounds',
        'status',
        'status_service',
        'stop',
        'taskbar',
        'timer',
        'view',
        'visible',
        'weather',
        'weather_service',
        'window',
        'worker',
    )

    # Actions, native-shell lifetime, audio ownership and desktop observations
    # are separate composition dependencies rather than UI options.
    def __init__(self, actions: BarActions, *, native_shell: bool = True, audio_level: Callable[[], float | None] | None = None,
                 observations: BarObservations | None = None) -> None:
        self.actions = actions
        self.observations = BarObservations() if observations is None else observations
        self.closed = False
        self.visible = native_shell
        self.activity = State.READY
        self.recording = RecordingState()
        self.layout_enabled = True
        self.current_layer: str | None = None
        self.view: Toolbar | None = None
        self.errors: queue.Queue[str] = queue.Queue()
        self.taskbar = TaskbarControl()
        self.controls: shell.AppWindow | None = None
        self.keys: WindowsKeyObserver | None = None
        self.worker: threading.Thread | None = None
        self.loop = EventLoop(application(), self.paint_frames)
        self.materials = appearance.FrostSampler()
        self.next_material = 0.0
        self.next_power = 0.0
        self.power: Power = PowerUnavailable.UNKNOWN
        self.weather: Weather | None = None
        self.weather_service: LocalWeather | None = None
        self.status_service: StatusObserver | None = None
        self.ambient = Ambient(datetime.now().strftime("%H:%M"), self.power)
        self.audio_meter: AudioMeter | None = None
        self.sample_bounds: Rect | None = None
        self.preference: appearance.Preference = appearance.Material.SOLID
        self.create_surfaces()
        self.notification_service: NotificationObserver | None = None
        self.notification_access = Access.UNAVAILABLE
        self.notification_observation: Observed | None = None
        self.timer = QtCore.QTimer(self.window)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        try:
            if audio_level is not None:
                self.audio_meter = AudioMeter(audio_level)
            if native_shell:
                self.notification_service = NotificationObserver()
                self.weather_service = LocalWeather()
                self.status_service = StatusObserver()
                self.controls = shell.AppWindow("workspace shell controls", self.message)
                self.keys = WindowsKeyObserver(self.controls.handle)
                self.worker = threading.Thread(target=self.start_taskbar, name="taskbar recovery", daemon=True)
                self.worker.start()
            self.render(animate=self.observations.motion())
            self.tick()
        except BaseException:
            self.close()
            raise

    def create_surfaces(self) -> None:
        self.window = Pill(self.loop, "Workspace floating bar", attached=True)
        self.capture = Pill(self.loop, "Workspace recording controls", attached=True)
        self.keycaps = Pill(self.loop, "Workspace keyboard mode", attached=True)
        self.pills = (self.window, self.capture, self.keycaps)
        # Function boundaries are menu | status + its Stop | inbox. Auxiliary
        # capsules already mark recording/keyboard boundaries with their shape.
        self.menu_button = self.window.button("menu", "", "Open Workspace controls", self.open_menu)
        self.controls_divider = Divider(self.window)
        self.window.row.addWidget(self.controls_divider)
        self.status = StatusView(self.window)
        self.window.row.addWidget(self.status)
        self.stop = self.window.button("close", "", "Stop agent work", self.actions.stop)
        self.stop.hide()
        self.inbox_divider = Divider(self.window)
        self.window.row.addWidget(self.inbox_divider)
        self.inbox_divider.hide()
        self.inbox: QtWidgets.QToolButton = self.window.button("bell", "", "Open inbox · Hold V + T", self.actions.inbox)
        self.inbox.hide()
        self.record = self.capture.button("mic", "", "Open meeting recording", self.actions.work)
        self.record_stop = self.capture.button("close", "", "Stop recording", lambda: self.actions.record("stop"))
        self.keyboard = self.keycaps.button("keyboard", "", "Current keyboard mode · open key map", self.actions.keyboard)
        self.menu = QtWidgets.QMenu(self.window)
        self.audio_timer = QtCore.QTimer(self.window)
        self.audio_timer.setInterval(50)
        self.audio_timer.timeout.connect(self.sample_audio)

    def start_taskbar(self) -> None:
        try:
            self.taskbar.start()
        except OSError as error:
            self.errors.put(str(error))

    def message(self, hwnd: int, message: int, wparam: int, lparam: int) -> int | None:
        if message == TASKBAR_TOGGLE:
            self.toggle_taskbar()
            return 0
        return None

    def toggle_taskbar(self) -> None:
        try:
            self.taskbar.toggle()
        except OSError as error:
            self.actions.problem(str(error))

    def open_menu(self) -> None:
        target = self.observations.foreground()
        self.menu.clear()
        def item(label: str, action: Callable[[], None]) -> None:
            self.menu.addAction(label).triggered.connect(lambda: action())  # noqa: PLW0108
        item("Your work feed", self.actions.agent)
        item("Work and meetings", self.actions.work)
        record_action: RecordingAction = "stop" if self.recording.capturing else "start"
        item("Stop recording" if self.recording.capturing else "Record a meeting", lambda: self.actions.record(record_action))
        self.menu.addSeparator()
        item("Keyboard map", self.actions.keyboard)
        item("Keyboard overlay", self.actions.overlay)
        item("Windows taskbar", self.toggle_taskbar)
        item("Switch windows · Apps + Esc", lambda: self.actions.tiling(Tool.WINDOW_SWITCHER, target))
        item("Copy latest transcript", lambda: self.actions.tiling(Tool.COPY_TRANSCRIPT, target))
        item("Windows notification settings", self.notification_settings)
        tiling = self.menu.addMenu("Window tiling")
        tiling.addAction("Spread windows across screens").triggered.connect(lambda: self.actions.tiling(Tool.TILE_BALANCE, target))
        for label, tool in (("Focus left", Tool.TILE_FOCUS_LEFT), ("Focus right", Tool.TILE_FOCUS_RIGHT),
                            ("Previous workspace", Tool.TILE_PREVIOUS_WORKSPACE), ("Next workspace", Tool.TILE_NEXT_WORKSPACE),
                            ("Float or tile the active window", Tool.TILE_FLOAT), ("Change split direction", Tool.TILE_DIRECTION),
                            ("Pause or resume automatic tiling", Tool.TILE_PAUSE)):
            tiling.addAction(label).triggered.connect(lambda checked=False, selected=tool: self.actions.tiling(selected, target))
        self.menu.addSeparator()
        item("All Workspace controls…", self.actions.menu)
        colors, ink = self.window.colors, self.window.ink
        self.menu.setStyleSheet(f"""
QMenu {{ background: {colors.surface}; color: {ink.foreground}; border: 1px solid {colors.edge};
 border-radius: 12px; padding: 6px; font: 12px 'Segoe UI'; }}
QMenu::item {{ padding: 8px 18px; border-radius: 7px; }}
QMenu::item:selected {{ background: rgba(150,145,180,45); }}
QMenu::separator {{ height: 1px; background: {colors.edge}; margin: 4px 10px; }}
""")
        self.menu.popup(self.window.mapToGlobal(QtCore.QPoint(0, self.window.height() + 8)))

    def state(self, state: State) -> None:
        if self.activity != state:
            self.activity = state
            # Content follows input immediately; only a new segment slides in.
            self.render(animate=self.observations.motion())

    def inbox_changed(self, count: int) -> None:
        """Qt requires updating its live button in place, solely on this owner thread."""
        if self.closed:
            return
        text = "" if not count else str(count) if count < 100 else "99+"
        description = f"{count} inbox {'item needs' if count == 1 else 'items need'} your attention · open inbox · Hold V + T"
        if self.inbox.text() == text and self.inbox.toolTip() == description:
            return
        self.inbox.setText(text)
        self.inbox.setToolTip(description)
        self.inbox.setAccessibleName(description)
        self.inbox.setVisible(count > 0)
        self.inbox_divider.setVisible(count > 0)
        self.window.adjustSize()
        self.position()

    def recording_changed(self, recording: RecordingState) -> None:
        if self.recording != recording:
            self.recording = recording
            self.render(animate=self.observations.motion())

    def layer(self, text: str | None) -> None:
        self.current_layer = text
        self.render(animate=self.observations.motion())

    def layout(self, enabled: bool) -> None:
        self.layout_enabled = enabled
        self.render(animate=self.observations.motion())

    def render(self, *, animate: bool) -> None:
        if self.closed:
            return
        view = toolbar(self.activity, self.recording, enabled=self.layout_enabled, layer=self.current_layer)
        if view != self.view:
            self.view = view
            self.status.capture(listening=self.activity is State.LISTENING, processing=self.activity is State.WORKING)
            if isinstance(view.activity, Resting):
                self.status.facts(self.ambient)
                self.status.setToolTip("Clock, battery and local weather")
                self.stop.hide()
            else:
                self.status.facts(None)
                self.status.setText("" if self.status.listening or self.status.processing else view.activity.title)
                self.status.setToolTip(view.activity.title)
                self.status.accessible()
                self.status.symbol = view.activity.icon
                self.stop.setVisible(view.activity.can_stop)
                self.stop.setToolTip("Stop speech capture" if self.activity is State.LISTENING else "Stop agent work")
                self.status.setToolTip("Transcribing captured audio" if self.activity is State.WORKING
                                       else view.activity.title + (" · use Stop to finish" if view.activity.can_stop else ""))
            if self.activity is State.LISTENING:
                self.audio_timer.start()
            else:
                self.audio_timer.stop()
            if self.audio_meter is not None:
                self.audio_meter.listen(enabled=self.activity is State.LISTENING)
            if view.capture is not None:
                self.record.setText(view.capture.title)
                self.record_stop.setVisible(view.capture.can_stop)
                if self.record.property("recording") != self.recording.capturing:
                    self.record.setProperty("recording", self.recording.capturing)
                    self.capture.recolor()
            self.keyboard.setText(view.keyboard or "")
            for pill in self.pills:
                pill.adjustSize()
        self.position()
        now = self.observations.clock()
        self.window.show_activity(self.visible, now, animate=animate)
        self.capture.show_activity(self.visible and view.capture is not None, now, animate=animate)
        self.keycaps.show_activity(self.visible and view.keyboard is not None, now, animate=animate)
        self.paint_frames()

    def position(self) -> None:
        area = QtGui.QGuiApplication.primaryScreen().geometry()
        x = area.x() + (area.width() - self.window.width()) // 2
        y = area.y()
        self.window.place(x, y)
        right = x + self.window.width() - OVERLAP
        left = x - self.keycaps.attached_width() + OVERLAP
        fits_capture = right + self.capture.attached_width() <= area.right() - 12
        fits_keyboard = left >= area.left() + 12
        self.capture.attach(fits_capture)
        self.keycaps.attach(fits_keyboard)
        capture = fits_capture and (self.capture.presented or self.capture.alpha > 0)
        keyboard = fits_keyboard and (self.keycaps.presented or self.keycaps.alpha > 0)
        self.window.connections(left=keyboard, right=capture)
        self.capture.connections(left=capture)
        self.keycaps.connections(right=keyboard)
        self.capture.place(right if fits_capture else x, y if fits_capture else y + self.window.height() + 6, origin=y)
        self.keycaps.place(left if fits_keyboard else x, y if fits_keyboard else y + self.window.height() + 6, origin=y)

    def paint_frames(self) -> None:
        if self.closed:
            return
        now = self.observations.clock()
        moving = [pill.advance(now) for pill in self.pills]
        spinning = self.status.pulse(now, animate=self.visible and self.observations.motion())
        self.position()
        self.loop.watch(any(moving) or spinning)

    def tick(self) -> None:
        if self.closed:
            return
        try:
            self.taskbar.enforce()
        except OSError as error:
            self.errors.put(str(error))
        while not self.errors.empty():
            self.actions.problem(self.errors.get_nowait())
        self.poll_notifications()
        now = self.observations.clock()
        if now >= self.next_power:
            self.next_power = now + 15
            self.power = self.observations.power()
        if self.weather_service is not None:
            with suppress(queue.Empty):
                self.weather = self.weather_service.results.get_nowait()
        if self.status_service is not None:
            with suppress(queue.Empty):
                system = self.status_service.results.get_nowait()
                if system != self.status.system:
                    self.status.system_changed(system)
                    self.window.adjustSize()
        ambient = Ambient(datetime.now().strftime("%H:%M"), self.power, self.weather)
        if ambient != self.ambient:
            self.ambient = ambient
            if self.view is not None and isinstance(self.view.activity, Resting):
                self.status.facts(ambient)
                self.window.adjustSize()
        visible_bounds = tuple(pill.bounds for pill in self.pills if pill.isVisible() and pill.bounds is not None)
        self.sample_bounds = (Rect(min(rect.left for rect in visible_bounds), min(rect.top for rect in visible_bounds),
                                   max(rect.right for rect in visible_bounds), max(rect.bottom for rect in visible_bounds))
                              if visible_bounds else None)
        # Sample outside the entire group: adjacent glass must not darken its neighbor.
        for sample in self.materials.read():
            if sample.bounds == self.sample_bounds:
                for pill in self.pills:
                    pill.frost = sample.frost
        if now >= self.next_material:
            self.next_material = now + .75
            self.preference = self.observations.material()
            if self.preference is appearance.Material.GLASS and self.sample_bounds is not None:
                self.materials.submit((self.sample_bounds,))
        if self.view is not None:
            for pill, tone in ((self.window, self.view.activity.tone), (self.capture, Tone.RECORDING), (self.keycaps, Tone.REPLY)):
                pill.material(tone, self.preference)
        self.position()

        self.paint_frames()

    def dismiss_notification(self, key: NoticeKey) -> None:
        if not self.actions.handled_notice(key):
            self.remove_notification(key)

    def remove_notification(self, key: NoticeKey) -> None:
        if self.notification_service is not None:
            self.notification_service.dismiss(key)

    def notification_settings(self) -> None:
        os.startfile('ms-settings:notifications')

    def poll_notifications(self) -> None:
        if self.notification_service is not None:
            with suppress(queue.Empty):
                observed = self.notification_service.results.get_nowait()
                match observed:
                    case Observed():
                        self.notification_access = Access.ALLOWED
                        self.notification_observation = observed
                        self.actions.notices(observed)
                    case Unavailable(access=access):
                        self.notification_access = access

    def sample_audio(self) -> None:
        if not self.closed and self.activity is State.LISTENING:
            self.status.observe(self.audio_meter.level() if self.audio_meter is not None else None)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        self.audio_timer.stop()
        if self.audio_meter is not None:
            self.audio_meter.close()
        if self.weather_service is not None:
            self.weather_service.close()
        if self.status_service is not None:
            self.status_service.close()
        self.menu.close()
        if self.notification_service is not None:
            self.notification_service.close()
        self.materials.close()
        try:
            if self.keys is not None:
                self.keys.close()
            self.taskbar.close()
            if self.worker is not None:
                self.worker.join(timeout=6)
        finally:
            if self.controls is not None:
                self.controls.destroy()
            for pill in self.pills:
                pill.dispose()
            self.loop.close()
