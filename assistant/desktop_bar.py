"""The island bar: Workspace's floating capsules at the top of the primary screen.

The island stays centred and acts on what it shows; temporary capsules sit beside
it. `island_model` decides the views, `island_layout` where they sit, and
`ui_components.appearance` how they read. This owner observes the desktop and
publishes each result to the one bar window and its glass.
"""

import math
import queue
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import assert_never
lazy import os

lazy from PySide6 import QtCore, QtGui, QtWidgets

from assistant.qt_runtime import prepare
lazy import winapi.ambient
lazy from assistant.ambient import Ambient, SystemStatus
lazy from assistant.audio_meter import AudioMeter
lazy from assistant.bar_status import StatusObserver
lazy from assistant.icons import State
lazy from assistant.island_layout import HEIGHT, Metrics, Placed, frame, snap
lazy from assistant.island_model import Action, CapsuleView, Key, Marker, Observed, Spinner, island, keyboard
lazy from assistant.island_surface import TOP, BarWindow, font
lazy from assistant.qt_ui import EventLoop, application
lazy from assistant.recording_state import RecordingAction, RecordingState
lazy from assistant.shell_controls import TASKBAR_TOGGLE, TaskbarControl, WindowsKeyObserver
lazy from assistant.ui_components.appearance import GLASS_ACCENT, look
lazy from protocol import Tool
lazy from winapi import appearance, shell, system_notices, windows
lazy from winapi.machine_status import Power, PowerUnavailable
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
    notices: Callable[[system_notices.Observed], None] = lambda _: None
    handled_notice: Callable[[system_notices.NoticeKey], bool] = lambda _: False


@dataclass(frozen=True, slots=True)
class BarObservations:
    """Native facts and presentation preferences, supplied at UI composition."""

    clock: Callable[[], float] = time.monotonic
    foreground: Callable[[], int] = windows.foreground
    power: Callable[[], Power] = winapi.ambient.power
    material: Callable[[], appearance.Preference] = appearance.preference
    motion: Callable[[], bool] = appearance.animations_enabled
    local_time: Callable[[], datetime] = datetime.now


def level(value: float | None) -> float:
    """A microphone level as a wave bar's height, on a perceptual scale."""
    return min(1.0, math.log10(1 + max(0.0, value or 0.0) * 90) / math.log10(91))


class DesktopBar:
    __slots__ = (
        "actions",
        "activity",
        "ambient",
        "audio_meter",
        "audio_timer",
        "closed",
        "controls",
        "current_layer",
        "errors",
        "frost",
        "hovered",
        "inbox",
        "keys",
        "layout_enabled",
        "loop",
        "materials",
        "menu",
        "next_material",
        "next_power",
        "notification_access",
        "notification_observation",
        "notification_service",
        "observations",
        "power",
        "preference",
        "recording",
        "sample_bounds",
        "status_service",
        "system",
        "taskbar",
        "timer",
        "views",
        "visible",
        "window",
        "worker",
    )

    # Actions, native-shell lifetime, audio ownership and desktop observations
    # are separate composition dependencies rather than UI options.
    def __init__(
        self,
        actions: BarActions,
        *,
        native_shell: bool = True,
        audio_level: Callable[[], float | None] | None = None,
        observations: BarObservations | None = None,
    ) -> None:
        self.actions = actions
        self.observations = BarObservations() if observations is None else observations
        self.closed = False
        self.visible = native_shell
        self.activity = State.READY
        self.recording = RecordingState()
        self.layout_enabled = True
        self.current_layer: str | None = None
        self.inbox = 0
        self.hovered: Key | None = None
        self.views: tuple[CapsuleView, ...] = ()
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
        self.system = SystemStatus()
        self.status_service: StatusObserver | None = None
        self.ambient = Ambient(self.observations.local_time().strftime("%H:%M"), self.power)
        self.audio_meter: AudioMeter | None = None
        self.sample_bounds: Rect | None = None
        self.preference: appearance.Preference = self.observations.material()
        self.frost = appearance.Frost.SMOKED
        self.window = BarWindow(self.loop, self.press, self.hover)
        self.menu = QtWidgets.QMenu(self.window)
        self.notification_service: NotificationObserver | None = None
        self.notification_access = system_notices.Access.UNAVAILABLE
        self.notification_observation: system_notices.Observed | None = None
        self.timer, self.audio_timer = self.timers()
        try:
            if audio_level is not None:
                self.audio_meter = AudioMeter(audio_level)
            if native_shell:
                self.notification_service = NotificationObserver()
                self.status_service = StatusObserver()
                self.controls = shell.AppWindow("workspace shell controls", self.message)
                self.keys = WindowsKeyObserver(self.controls.handle)
                self.worker = threading.Thread(target=self.start_taskbar, name="taskbar recovery", daemon=True)
                self.worker.start()
            self.timer.start()
            self.render()
            self.tick()
        except BaseException:
            self.close()
            raise

    def timers(self) -> tuple[QtCore.QTimer, QtCore.QTimer]:
        """The 100 ms desktop observation tick, and the 50 ms microphone trace while dictating."""
        tick, audio = QtCore.QTimer(self.window), QtCore.QTimer(self.window)
        tick.setInterval(100)
        tick.timeout.connect(self.tick)
        audio.setInterval(50)
        audio.timeout.connect(self.sample_audio)
        return tick, audio

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

    def press(self, action: Action) -> None:
        match action:
            case Action.OPEN_MENU:
                self.open_menu()
            case Action.STOP_DICTATION | Action.STOP_AGENT:
                self.actions.stop()
            case Action.OPEN_QUESTION | Action.OPEN_INBOX:
                self.actions.inbox()
            case Action.OPEN_CANVAS:
                self.actions.work()
            case Action.OPEN_KEYMAP:
                self.actions.keyboard()
            case Action.STOP_RECORDING:
                self.actions.record("stop")
            case _:
                assert_never(action)

    def hover(self, key: Key | None) -> None:
        if self.hovered is not key:
            self.hovered = key
            self.render()

    def open_menu(self) -> None:
        target = self.observations.foreground()
        self.menu.clear()

        def item(label: str, action: Callable[[], None]) -> None:
            def triggered() -> None:
                action()

            self.menu.addAction(label).triggered.connect(triggered)

        item("Your work canvas", self.actions.work)
        item("Your work feed", self.actions.agent)
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

        def tile_action(selected: Tool) -> Callable[[object], None]:
            def triggered(_checked: object) -> None:
                self.actions.tiling(selected, target)

            return triggered

        for label, tool in (
            ("Focus left", Tool.TILE_FOCUS_LEFT),
            ("Focus right", Tool.TILE_FOCUS_RIGHT),
            ("Previous workspace", Tool.TILE_PREVIOUS_WORKSPACE),
            ("Next workspace", Tool.TILE_NEXT_WORKSPACE),
            ("Float or tile the active window", Tool.TILE_FLOAT),
            ("Change split direction", Tool.TILE_DIRECTION),
            ("Pause or resume automatic tiling", Tool.TILE_PAUSE),
        ):
            tiling.addAction(label).triggered.connect(tile_action(tool))
        self.menu.addSeparator()
        item("All Workspace controls…", self.actions.menu)
        self.menu.setFont(font(strong=False))
        self.menu.setStyleSheet(menu_style(self.preference))
        anchor = self.window.capsules.get(Key.ISLAND)
        origin = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height() + 6)) if anchor is not None else self.window.mapToGlobal(QtCore.QPoint())
        self.menu.popup(origin)

    def state(self, state: State) -> None:
        if self.activity != state:
            self.activity = state
            self.render()

    def inbox_changed(self, count: int) -> None:
        if not self.closed and self.inbox != count:
            self.inbox = count
            self.render()

    def recording_changed(self, recording: RecordingState) -> None:
        if self.recording != recording:
            self.recording = recording
            self.render()

    def layer(self, text: str | None) -> None:
        self.current_layer = text
        self.render()

    def layout(self, *, enabled: bool) -> None:
        self.layout_enabled = enabled
        self.render()

    def observed(self) -> Observed:
        return Observed(
            self.activity, self.recording, self.ambient, self.system, self.inbox, keyboard(enabled=self.layout_enabled, layer=self.current_layer)
        )

    def render(self) -> None:
        if self.closed:
            return
        self.views = island(self.observed(), hovered=self.hovered)
        contents = tuple(self.window.measure(view) for view in self.views)
        width = QtGui.QGuiApplication.primaryScreen().geometry().width()
        placed = tuple(Placed(view.key, view.zone, content.width, HEIGHT) for view, content in zip(self.views, contents, strict=True))
        framed = frozendict((each.key, each) for each in snap(frame(placed, Metrics(width, top=TOP)), self.window.devicePixelRatioF()))
        match self.preference:
            case appearance.Contrast():
                contrast = True
            case appearance.Material.GLASS | appearance.Material.SOLID:
                contrast = False
            case _:
                assert_never(self.preference)
        self.window.present(
            tuple(
                (view, content, look(self.preference, self.frost, view.tint), framed[view.key])
                for view, content in zip(self.views, contents, strict=True)
            ),
            contrast=contrast,
            glass=self.preference is appearance.Material.GLASS,
        )
        listening = self.activity is State.LISTENING
        if listening and not self.audio_timer.isActive():
            self.window.samples.extend(0.0 for _ in range(len(self.window.samples)))
            self.audio_timer.start()
        elif not listening:
            self.audio_timer.stop()
        if self.audio_meter is not None:
            self.audio_meter.listen(enabled=listening)
        self.window.setVisible(self.visible)
        self.paint_frames()

    def spinning(self) -> bool:
        def spinner(part: object) -> bool:
            match part:
                case Spinner():
                    return True
                case _:
                    return False

        return any(spinner(part) for view in self.views for slot in view.slots for part in slot)

    def paint_frames(self) -> None:
        if self.closed:
            return
        animate = self.visible and self.observations.motion() and self.spinning()
        self.window.spin_angle = (90 - self.observations.clock() * 300) % 360 if animate else 90.0
        if self.spinning():
            for key, capsule in self.window.capsules.items():
                if key in (Key.ISLAND, Key.AGENT):
                    capsule.update()
        self.loop.watch(visible=animate)

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
        if self.status_service is not None:
            with suppress(queue.Empty):
                self.system = self.status_service.results.get_nowait()
        self.ambient = Ambient(self.observations.local_time().strftime("%H:%M"), self.power)
        self.sample_bounds = self.window.bounds(Key.ISLAND)
        # Small glass takes its scheme from the desktop beside the island.
        for sample in self.materials.read():
            if sample.bounds == self.sample_bounds:
                self.frost = sample.frost
        if now >= self.next_material:
            self.next_material = now + 0.75
            self.preference = self.observations.material()
            if self.preference is appearance.Material.GLASS and self.sample_bounds is not None:
                self.materials.submit((self.sample_bounds,))
        # Each tick re-measures, so a growing timer pushes its neighbours out.
        self.render()

    def dismiss_notification(self, key: system_notices.NoticeKey) -> None:
        if not self.actions.handled_notice(key):
            self.remove_notification(key)

    def remove_notification(self, key: system_notices.NoticeKey) -> None:
        if self.notification_service is not None:
            self.notification_service.dismiss(key)

    def notification_settings(self) -> None:
        os.startfile("ms-settings:notifications")

    def poll_notifications(self) -> None:
        if self.notification_service is not None:
            with suppress(queue.Empty):
                observed = self.notification_service.results.get_nowait()
                match observed:
                    case system_notices.Observed():
                        self.notification_access = system_notices.Access.ALLOWED
                        self.notification_observation = observed
                        self.actions.notices(observed)
                    case system_notices.Unavailable(access=access):
                        self.notification_access = access

    def sample_audio(self) -> None:
        if not self.closed and self.activity is State.LISTENING:
            self.window.samples.append(level(self.audio_meter.level() if self.audio_meter is not None else None))
            capsule = self.window.capsules.get(Key.ISLAND)
            if capsule is not None and any(Marker.WAVE in slot for view in self.views for slot in view.slots):
                capsule.update()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        self.audio_timer.stop()
        if self.audio_meter is not None:
            self.audio_meter.close()
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
            self.window.dispose()
            self.loop.close()


def menu_style(preference: appearance.Preference) -> str:
    """The controls menu stays a solid Qt menu until it becomes the island's expansion."""
    match preference:
        case appearance.Contrast(background=background, foreground=foreground):
            surface, ink, edge, selected = background, foreground, foreground, foreground
        case appearance.Material.GLASS | appearance.Material.SOLID:
            surface, ink, edge, selected = "#26262a", "rgba(255,255,255,240)", "rgba(255,255,255,24)", GLASS_ACCENT
        case _:
            assert_never(preference)
    return f"""
QMenu {{ background: {surface}; color: {ink}; border: 1px solid {edge}; border-radius: 12px; padding: 5px; }}
QMenu::item {{ padding: 6px 16px; border-radius: 7px; }}
QMenu::item:selected {{ background: {selected}; color: #ffffff; }}
QMenu::separator {{ height: 1px; background: {edge}; margin: 4px 10px; }}
"""
