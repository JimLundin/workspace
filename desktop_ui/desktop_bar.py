"""The island bar: Workspace's floating capsules at the top of the primary screen.

Activity stays centred and acts on what it shows; persistent navigation and
status anchor right; the system tray lives in the controls menu. `island_model` decides the views, `island_layout` where they sit, and
`ui_components.appearance` how they read. This owner observes the desktop and
publishes each result to the one bar window and its glass.
"""

import math
import queue
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import assert_never
lazy import os

lazy from PySide6 import QtCore, QtGui

from desktop_ui.qt_runtime import prepare
lazy import desktop_ui.components.appearance
lazy import winapi.ambient
lazy from assistant.meeting_detection import AutomaticStatus
lazy from assistant.recording_state import RecordingAction, RecordingState
lazy from desktop_ui import island_menu
lazy from desktop_ui.agent_progress import Phase, coalesced, stable_phases
lazy from desktop_ui.ambient import Ambient, SystemStatus
lazy from desktop_ui.application_observer import ApplicationObserver
lazy from desktop_ui.audio_meter import AudioMeter
lazy from desktop_ui.bar_status import StatusObserver
lazy from desktop_ui.components.appearance import Look, look
lazy from desktop_ui.components.meaning import Tint
lazy from desktop_ui.island_layout import HEIGHT, Metrics, expansion, frame, snap
lazy from desktop_ui.island_menu import (
    Applied,
    Chosen,
    Command,
    Controls,
    Dismissed,
    Menu,
    Slider,
    ToolChoice,
    TrayChoice,
    Volume,
    entries,
    restores_focus,
    shown,
)
lazy from desktop_ui.island_model import Action, Agent, CapsuleView, Expansion, Job, Key, Marker, Observed, Spinner, capture, island, keyboard
lazy from desktop_ui.island_motion import IslandMotion, Shown, advance, finish, placed, retarget, settled
lazy from desktop_ui.island_surface import TOP, BarWindow, Drawn, Presented
lazy from desktop_ui.qt_ui import EventLoop, application
lazy from desktop_ui.request_panel import RequestActions
lazy from desktop_ui.shell_controls import TASKBAR_TOGGLE, TaskbarControl, WindowsKeyObserver
lazy from desktop_ui.shell_items import Application, next_window
lazy from protocol import Tool
lazy from winapi import appearance, inputs, shell, system_notices, windows
lazy from winapi.machine_status import Power, PowerUnavailable, Speakers
lazy from winapi.notifications import NotificationObserver
lazy from winapi.shapes import Rect
lazy from winapi.tray_host import Click, TrayHost

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
    tool: Callable[[Tool, int], None] = lambda tool, hwnd: None
    notices: Callable[[system_notices.Observed], None] = lambda _: None
    requests: RequestActions | None = field(default=None, kw_only=True)


@dataclass(frozen=True, slots=True)
class BarObservations:
    """Native facts, the desktop's focus and presentation preferences, supplied at UI composition."""

    clock: Callable[[], float] = time.monotonic
    foreground: Callable[[], int] = windows.foreground
    focus: Callable[[int], bool] = windows.focus
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
        "agent",
        "ambient",
        "application_service",
        "applications",
        "audio_meter",
        "audio_timer",
        "automatic_recording",
        "closed",
        "controls",
        "current_layer",
        "dictating",
        "errors",
        "expanded",
        "frost",
        "hovered",
        "inbox",
        "job",
        "keys",
        "last_frame",
        "layout_enabled",
        "loop",
        "materials",
        "menu_target",
        "motion",
        "next_material",
        "next_power",
        "notification_access",
        "notification_observation",
        "notification_service",
        "observations",
        "overlay_enabled",
        "power",
        "preference",
        "recording",
        "request",
        "resolution",
        "sample_bounds",
        "sampled_at",
        "status_service",
        "system",
        "taskbar",
        "timer",
        "tray_host",
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
        self.applications: tuple[Application, ...] = ()
        self.application_service: ApplicationObserver | None = None
        self.tray_host: TrayHost | None = None
        self.observations = BarObservations() if observations is None else observations
        self.closed, self.visible = False, native_shell
        # Each activity comes from its own owner: dictation and quick jobs from the
        # voice controller, the agent from its session.
        self.dictating, self.automatic_recording = False, AutomaticStatus.OFF
        self.overlay_enabled = False
        self.job: Job | None = None
        self.agent: Agent | None = None
        self.recording = RecordingState()
        self.layout_enabled = True
        self.current_layer: str | None = None
        self.inbox = 0
        self.hovered: Key | None = None
        # The open menu, and the window that had the keyboard before it opened.
        self.expanded: Menu | None = None
        self.request: Phase | None = None
        self.menu_target = 0
        self.views: tuple[CapsuleView, ...] = ()
        # Reassigned each frame; the bar mutates no motion or view record.
        self.motion = IslandMotion()
        self.last_frame: float | None = None
        self.resolution = appearance.TimerResolution()
        self.errors: queue.Queue[str] = queue.Queue()
        self.taskbar = TaskbarControl()
        self.controls: shell.AppWindow | None = None
        self.keys: WindowsKeyObserver | None = None
        self.worker: threading.Thread | None = None
        self.loop = EventLoop(application(), self.paint_frames)
        self.materials = appearance.FrostSampler()
        self.next_material, self.next_power = 0.0, 0.0
        self.power: Power = PowerUnavailable.UNKNOWN
        self.system = SystemStatus()
        self.status_service: StatusObserver | None = None
        self.ambient = Ambient(self.observations.local_time().strftime("%H:%M"), self.power)
        self.audio_meter: AudioMeter | None = None
        self.sample_bounds: Rect | None = None
        self.sampled_at: float | None = None
        self.preference: appearance.Preference = self.observations.material()
        self.frost = appearance.Frost.SMOKED
        self.window = BarWindow(self.loop, self)
        self.notification_service: NotificationObserver | None = None
        self.notification_access = system_notices.Access.UNAVAILABLE
        self.notification_observation: system_notices.Observed | None = None
        self.timer, self.audio_timer = self.timers()
        self.start(native_shell=native_shell, audio_level=audio_level)

    def start(self, *, native_shell: bool, audio_level: Callable[[], float | None] | None) -> None:
        """Start native observations only after all resource fields are initialized."""
        try:
            if audio_level is not None:
                self.audio_meter = AudioMeter(audio_level)
            if native_shell:
                self.start_shell()
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
        audio.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        audio.timeout.connect(self.sample_audio)
        return tick, audio

    def start_shell(self) -> None:
        """The production desktop: notifications, system status, shell controls and taskbar recovery."""
        self.notification_service = NotificationObserver()
        self.status_service = StatusObserver()
        self.controls = shell.AppWindow("workspace shell controls", self.message)
        self.tray_host = TrayHost()
        self.application_service = ApplicationObserver()
        self.keys = WindowsKeyObserver(self.controls.handle)
        self.worker = threading.Thread(target=self.start_taskbar, name="taskbar recovery", daemon=True)
        self.worker.start()

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

    def poll_shell(self) -> None:
        if self.tray_host is None:
            return
        previous = self.window.shell_sections.app_snapshot
        self.window.show_tray(self.tray_host.poll())  # The tick's render rebuilds an open menu's tray cells.
        if self.application_service is not None:
            with suppress(queue.Empty):
                self.applications = self.application_service.results.get_nowait()
        self.window.shell_sections.applications((self.applications, self.observations.foreground()), self.application_click)
        # A changed snapshot must also publish section geometry when the island is still.
        if previous != self.window.shell_sections.app_snapshot:
            self.window.presentation = None

    def application_click(self, app: Application, click: Click) -> None:
        self.close_menu(restore=False)
        if click is Click.RIGHT:
            chosen = shell.show_menu(int(self.window.winId()), tuple(shell.MenuItem(window.handle, window.title) for window in app.windows))
            if chosen:
                self.observations.focus(chosen)
        else:
            self.observations.focus(next_window(app, self.observations.foreground()))

    def tray(self, slot: int, click: Click) -> None:
        """The application gets the click and the keyboard; the menu closes without taking it back."""
        self.close_menu(restore=False)
        entries = self.window.tray
        if self.tray_host is not None and slot < len(entries):
            self.tray_host.click(entries[slot], click, inputs.cursor_position())

    def press(self, action: Action) -> None:
        match action:
            case Action.OPEN_MENU:
                self.open_menu()
            case Action.CLOSE_MENU:
                self.close_menu(restore=True)
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

    def menu(self) -> Menu:
        """The menu for what's happening now, keeping the current selection and disclosure."""
        recorded = capture(self.recording) if self.recording.capturing else None
        working = self.agent if self.agent is not None and not self.agent.waiting else None
        sound = Slider("Sound", self.system.volume, muted=self.system.speakers is Speakers.MUTED)
        menu = Menu(
            entries(
                Controls(
                    recorded.title if recorded is not None else None,
                    working.phase if working is not None else None,
                    self.automatic_recording,
                    overlay=self.overlay_enabled,
                    taskbar=self.taskbar.revealed,
                    sound=sound,
                    tray=tuple(entry.tip or "Tray application" for entry in self.window.tray),
                )
            )
        )
        if self.expanded is None:
            return menu
        return replace(menu, selected=self.expanded.selected, disclosed=self.expanded.disclosed)

    def request_actions(self) -> RequestActions | None:
        return self.actions.requests

    def requests_changed(self, choices: tuple[Phase, ...]) -> None:
        choices = tuple(coalesced(stable_phases(choices, (self.request,) if self.request is not None else ())))
        if self.request is not None:
            current = next((phase for phase in choices if phase.key == self.request.key), None)
            if current is None:
                self.close_menu(restore=False)
            elif current != self.request:
                self.request = current
                if self.actions.requests is not None:
                    self.actions.requests.select(current.request)
                self.render()

    def open_request(self, phase: Phase) -> None:
        if self.closed:
            return
        self.menu_target = self.observations.foreground()
        self.expanded = None
        self.request = phase
        actions = self.actions.requests
        if actions is not None:
            actions.select(phase.request)
        windows.allow_activation(int(self.window.winId()), allowed=True)
        self.window.activateWindow()
        self.window.setFocus()
        self.render()

    def open_menu(self) -> None:
        """The island expands into the menu and takes the keyboard from the window that had it."""
        if self.closed:
            return
        self.menu_target = self.observations.foreground()
        self.request = None
        if self.actions.requests is not None:
            self.actions.requests.select(None)
        self.expanded = self.menu()
        handle = int(self.window.winId())
        windows.allow_activation(handle, allowed=True)
        self.window.activateWindow()
        self.window.setFocus()
        self.render()

    def close_menu(self, *, restore: bool) -> None:
        if self.expanded is None and self.request is None:
            return
        self.expanded = None
        self.request = None
        if self.actions.requests is not None:
            self.actions.requests.select(None)
        windows.allow_activation(int(self.window.winId()), allowed=False)
        self.render()
        if restore and self.menu_target:
            self.observations.focus(self.menu_target)

    def select(self, index: int) -> None:
        if self.expanded is not None and self.expanded.selected != index:
            self.expanded = replace(self.expanded, selected=index)
            self.render()

    def pick(self, index: int) -> None:
        if self.expanded is not None:
            self.settle_menu(island_menu.choose(self.expanded, shown(self.expanded)[index].entry))

    def key(self, press: island_menu.Press) -> None:
        if self.expanded is not None:
            self.settle_menu(island_menu.press(self.expanded, press))

    def deactivated(self) -> None:
        """Another window took the keyboard: the menu closes without taking it back."""
        self.close_menu(restore=False)

    def settle_menu(self, outcome: island_menu.Outcome) -> None:
        match outcome:
            case Menu() as menu:
                self.expanded = menu
                self.render()
            case Chosen(choice=choice):
                self.close_menu(restore=restores_focus(choice))
                self.run(choice)
            case Applied(choice=choice):
                self.run(choice)
                self.render()
            case Dismissed.ESCAPE:
                self.close_menu(restore=True)
            case _:
                assert_never(outcome)

    def run(self, choice: island_menu.Choice) -> None:
        match choice:
            case ToolChoice(tool=tool):
                self.actions.tool(tool, self.menu_target)
            case Command.CANVAS:
                self.actions.work()
            case Command.FEED:
                self.actions.agent()
            case Command.RECORD:
                self.actions.record("start")
            case Command.STOP_RECORDING:
                self.actions.record("stop")
            case Command.AUTOMATIC_RECORDING:
                self.actions.record("automatic")
            case Command.STOP_AGENT:
                self.actions.stop()
            case Command.KEYMAP:
                self.actions.keyboard()
            case Command.OVERLAY:
                self.actions.overlay()
            case Command.TASKBAR:
                self.toggle_taskbar()
            case Command.NOTIFICATIONS:
                self.notification_settings()
            case Command.ALL_CONTROLS:
                self.actions.menu()
            case Volume(level=level):
                self.volume(level)
            case TrayChoice(slot=slot):
                self.tray(slot, Click.LEFT)
            case _:
                assert_never(choice)

    def volume(self, level: float) -> None:
        """The status observer's worker applies it; the slider follows at once rather than at the next reading."""
        if self.status_service is None:
            return
        self.status_service.set_volume(level)
        self.system = replace(self.system, volume=level)
        self.render()

    def overlay_changed(self, *, enabled: bool) -> None:
        if self.overlay_enabled != enabled:
            self.overlay_enabled = enabled
            self.render()

    def dictation(self, *, active: bool) -> None:
        if self.dictating != active:
            self.dictating = active
            self.render()

    def job_changed(self, job: Job | None) -> None:
        if self.job is not job:
            self.job = job
            self.render()

    def agent_changed(self, agent: Agent | None) -> None:
        if self.agent != agent:
            self.agent = agent
            self.render()

    def inbox_changed(self, count: int) -> None:
        if not self.closed and self.inbox != count:
            self.inbox = count
            self.render()

    def recording_changed(self, recording: RecordingState) -> None:
        if self.recording != recording:
            self.recording = recording
            self.render()

    def automatic_changed(self, status: AutomaticStatus) -> None:
        if self.automatic_recording is not status:
            self.automatic_recording = status
            self.render()

    def layer(self, text: str | None) -> None:
        self.current_layer = text
        self.render()

    def layout(self, *, enabled: bool) -> None:
        self.layout_enabled = enabled
        self.render()

    def observed(self) -> Observed:
        return Observed(
            self.agent,
            self.job,
            self.recording,
            self.ambient,
            self.system,
            self.inbox,
            keyboard(enabled=self.layout_enabled, layer=self.current_layer),
            dictating=self.dictating,
        )

    def render(self) -> None:
        """Retarget the capsules at what the bar should show now; frames carry them there."""
        if self.closed:
            return
        if self.expanded is not None:
            self.expanded = self.menu()
        menu = self.expanded
        request = self.request
        opened = Expansion.MENU if menu is not None else Expansion.REQUEST if request is not None else None
        self.views = island(self.observed(), hovered=self.hovered, expanded=opened)
        shown = tuple(
            Shown(
                view,
                self.window.measure_request(request)
                if request is not None and view.key is Key.ISLAND
                else expansion(menu, self.window.measure(view))
                if menu is not None and view.key is Key.STATUS
                else self.window.measure(view),
            )
            for view in self.views
        )
        self.motion = retarget(self.motion, shown, animate=self.visible and self.observations.motion())
        listening = self.dictating
        if listening and not self.audio_timer.isActive():
            self.window.samples.extend(0.0 for _ in range(len(self.window.samples)))
            self.window.wave_from = tuple(self.window.samples)
            self.window.wave_progress = 1.0
            self.sampled_at = None
            self.audio_timer.start()
        elif not listening:
            self.audio_timer.stop()
        if self.audio_meter is not None:
            self.audio_meter.listen(enabled=listening)
        self.window.setVisible(self.visible)
        self.paint_frames()

    def draw(self) -> None:
        width = QtGui.QGuiApplication.primaryScreen().geometry().width()
        metrics = Metrics(width, top=TOP)
        framed = frozendict((each.key, each) for each in snap(frame(placed(self.motion), metrics), self.window.devicePixelRatioF()))
        match self.preference:
            case appearance.Contrast():
                contrast = True
            case appearance.Material.GLASS | appearance.Material.SOLID:
                contrast = False
            case _:
                assert_never(self.preference)
        drawn = tuple(
            Drawn(
                moving.view,
                moving.content,
                moving.previous,
                moving.fade.value,
                self.style(moving.view.tint, moving.content.height),
                framed[moving.key],
            )
            for moving in self.motion.capsules
            if moving.key in framed
        )
        # The window keeps the room a capsule is heading for, so it resizes only as an expansion starts and settles.
        reach = max((max(moving.height.value, moving.height.target) for moving in self.motion.capsules), default=float(HEIGHT))
        self.window.present(
            Presented(
                drawn,
                reach,
                self.expanded,
                frost=self.frost,
                contrast=contrast,
                glass=self.preference is appearance.Material.GLASS,
                request=self.request,
                shell_look=self.style(Tint.NONE, HEIGHT),
            )
        )
        # A closed menu keeps the last locations: a clicked application anchors its flyout where its icon was.
        if self.tray_host is not None and self.expanded is not None:
            self.tray_host.locate(self.window.tray_locations())

    def style(self, tint: Tint, height: float) -> Look:
        pane = desktop_ui.components.appearance.Menu(self.frost) if height > HEIGHT else desktop_ui.components.appearance.Capsule(self.frost)
        return look(self.preference, pane, tint)

    def spinning(self) -> bool:
        def spinner(part: object) -> bool:
            match part:
                case Spinner() | Marker.DOTS:
                    return True
                case _:
                    return False

        menu_spinner = self.expanded is not None and self.agent is not None and not self.agent.waiting
        return menu_spinner or any(spinner(part) for view in self.views for slot in view.slots for part in slot)

    def paint_frames(self) -> None:
        if self.closed:
            return
        now, animate = self.observations.clock(), self.visible and self.observations.motion()
        # A frame after the loop was idle starts the motion now, rather than from the last frame.
        elapsed = now - (self.last_frame if self.last_frame is not None else now)
        self.motion = advance(self.motion, elapsed) if animate else finish(self.motion)
        spinning = animate and self.spinning()
        waving = animate and self.dictating and self.expanded is None
        self.window.wave_progress = min(1.0, max(0.0, (now - self.sampled_at) / 0.05)) if waving and self.sampled_at is not None else 1.0
        self.window.spin_angle = (90 - now * 300) % 360 if spinning else 90.0
        self.draw()
        moving = not settled(self.motion)
        if self.spinning() or waving:
            for key, capsule in self.window.capsules.items():
                if key in (Key.ISLAND, Key.STATUS, Key.AGENT, Key.JOB):
                    capsule.update_indicators()
        running = moving or spinning or waving
        self.last_frame = now if running else None
        self.resolution.update(active=running)
        self.loop.watch(visible=running)

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
        self.poll_shell()
        if now >= self.next_power:
            self.next_power = now + 15
            self.power = self.observations.power()
        if self.status_service is not None:
            with suppress(queue.Empty):
                self.system = self.status_service.results.get_nowait()
        self.ambient = Ambient(self.observations.local_time().strftime("%H:%M"), self.power)
        self.sample_bounds = self.window.bounds(Key.ISLAND) or self.window.bounds(Key.STATUS)
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
        if not self.closed and self.dictating:
            # Begin at the last painted interpolation, including if a sample
            # arrives early. The bounded history stays with its Qt paint owner.
            self.window.wave_from = tuple(self.window.trace())
            self.window.samples.append(level(self.audio_meter.level() if self.audio_meter is not None else None))
            self.sampled_at = self.observations.clock()
            self.window.wave_progress = 0.0 if self.visible and self.observations.motion() else 1.0
            capsule = self.window.capsules.get(Key.ISLAND)
            if capsule is not None and any(Marker.WAVE in slot for view in self.views for slot in view.slots):
                capsule.update_indicators()

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
        if self.notification_service is not None:
            self.notification_service.close()
        self.materials.close()
        if self.tray_host is not None:
            self.tray_host.close()
        if self.application_service is not None:
            self.application_service.close()
        try:
            if self.keys is not None:
                self.keys.close()
            self.taskbar.close()
            if self.worker is not None:
                self.worker.join(timeout=6)
        finally:
            if self.controls is not None:
                self.controls.destroy()
            self.resolution.update(active=False)
            self.window.dispose()
            self.loop.close()
