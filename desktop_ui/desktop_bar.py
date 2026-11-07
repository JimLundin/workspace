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
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import assert_never
lazy import os

lazy from PySide6 import QtCore, QtGui

from desktop_ui.qt_runtime import prepare
lazy import desktop_ui.components.appearance
lazy import usage
lazy import winapi.ambient
lazy from config import APPS, DARK_WHEN_IDLE_MINUTES
lazy from contracts.meeting_detection import AutomaticStatus
lazy from contracts.recording_state import RecordingAction, RecordingState
lazy from contracts.status import Job
lazy from desktop_ui import island_menu, island_moment, ui_spec
lazy from desktop_ui.agent_progress import Phase, coalesced, hint, stable_phases
lazy from desktop_ui.ambient import Ambient, SystemStatus
lazy from desktop_ui.application_observer import EMPTY_ARRANGEMENT, ApplicationObserver, Arrangement
lazy from desktop_ui.audio_meter import AudioMeter
lazy from desktop_ui.away_screens import AwayScreens
lazy from desktop_ui.bar_status import StatusObserver
lazy from desktop_ui.components.appearance import Look, look
lazy from desktop_ui.components.meaning import Tint
lazy from desktop_ui.desktop_pager import pager
lazy from desktop_ui.island_layout import Content, Metrics, expansion, frame, snap
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
)
lazy from desktop_ui.island_model import Action, Agent, CapsuleView, Expansion, Key, Marker, Observed, Spinner, capture, island, order
lazy from desktop_ui.island_moment import Asked, Inbox, Notice, Notices, Row
lazy from desktop_ui.island_motion import IslandMotion, Shown, advance, finish, placed, retarget, settled
lazy from desktop_ui.island_surface import BarWindow, Drawn, Presented, expanded
lazy from desktop_ui.key_hint_overlay import KeyHintOverlay
lazy from desktop_ui.key_hints import hints
lazy from desktop_ui.navigation import AppKey, CycleApp, Order, Placing, ShowWindow, Source
lazy from desktop_ui.overlay_desktop import NativeOverlayDesktop
lazy from desktop_ui.qt_ui import EventLoop, application
lazy from desktop_ui.request_panel import RequestActions
lazy from desktop_ui.shell_controls import TaskbarControl
lazy from desktop_ui.shell_items import EMPTY_SHELF, Application, Item, Pinned, PinnedApp, Shelf
lazy from desktop_ui.ui_spec_watch import SpecWatch
lazy from desktop_ui.window_layout import App, Program, WorkspaceView
lazy from protocol import Installed, Tool
lazy from usage import Detail
lazy from winapi import appearance, inputs, session, shell, system_notices, windows
lazy from winapi.machine_status import Power, PowerUnavailable, Speakers
lazy from winapi.notifications import NotificationObserver
lazy from winapi.shapes import Rect
lazy from winapi.tray_host import Click, TrayHost

prepare()


@dataclass(frozen=True, slots=True)
class BarActions:
    work: Callable[[], None]
    stop: Callable[[], None]
    record: Callable[[RecordingAction], None]
    keyboard: Callable[[], None]
    overlay: Callable[[], None]
    menu: Callable[[], None]
    problem: Callable[[str], None]
    inbox: Callable[[], None] = field(kw_only=True)
    open_item: Callable[[str], None] = field(kw_only=True)  # The canvas, at one of its items.
    tool: Callable[[Tool], None] = lambda tool: None
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
    spec_folder: Path = ui_spec.FOLDER
    """The spec modules the bar watches and re-imports while it runs."""


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
        "arrangement",
        "audio_meter",
        "audio_timer",
        "automatic_recording",
        "away_screens",
        "choices",
        "chord_held",
        "closed",
        "controls",
        "dictating",
        "errors",
        "frost",
        "hints",
        "hovered",
        "inbox",
        "job",
        "last_frame",
        "layout_enabled",
        "loop",
        "materials",
        "menu_target",
        "motion",
        "next_material",
        "next_power",
        "notices",
        "notification_access",
        "notification_observation",
        "notification_service",
        "observations",
        "opened",
        "overlay_enabled",
        "power",
        "preference",
        "recording",
        "resolution",
        "sample_bounds",
        "sampled_at",
        "spec_watch",
        "specs",
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
        self.applications: Shelf = EMPTY_SHELF
        self.arrangement: Arrangement = EMPTY_ARRANGEMENT
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
        self.chord_held = False  # Either keyboard is holding its Apps key.
        self.layout_enabled = True
        self.hints: KeyHintOverlay | None = None
        self.inbox = self.menu_target = 0
        self.notices = Notices()
        self.choices: tuple[Phase, ...] = ()  # The session's phases, for a question opened from the island.
        self.hovered: Key | None = None
        # What the person opened, and the window that had the keyboard before it opened.
        self.opened: Menu | Phase | Inbox | None = None
        self.views: tuple[CapsuleView, ...] = ()
        # Reassigned each frame; the bar mutates no motion or view record.
        self.motion = IslandMotion()
        self.last_frame: float | None = None
        self.resolution = appearance.TimerResolution()
        self.errors: queue.Queue[str] = queue.Queue()
        self.taskbar = TaskbarControl()
        self.controls: shell.AppWindow | None = None
        self.away_screens: AwayScreens | None = None
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
        self.specs = ui_spec.bar_specs(reload=False)
        self.window = BarWindow(self.loop, self, self.specs.sizes)
        self.spec_watch = SpecWatch(self.observations.spec_folder, ui_spec.bar_specs, self.specs, self.respec, self.errors.put)
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
        """The 100 ms desktop observation tick and the 50 ms microphone trace while dictating."""
        tick, audio = QtCore.QTimer(self.window), QtCore.QTimer(self.window)
        tick.setInterval(100)
        tick.timeout.connect(self.tick)
        audio.setInterval(50)
        audio.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        audio.timeout.connect(self.sample_audio)
        return tick, audio

    def start_shell(self) -> None:
        """The production desktop: notifications, system status, shell controls and taskbar recovery."""
        self.notification_service = NotificationObserver.start()
        self.status_service = StatusObserver.start()
        self.controls = shell.AppWindow.create("workspace shell controls", self.message)
        self.away_screens = AwayScreens(self.record_usage)
        try:
            session.subscribe(self.controls.handle)
        except OSError as error:
            self.errors.put(f"Screens can't go dark when locked: {error}")
        self.tray_host = TrayHost.start()
        self.application_service = ApplicationObserver.start(self.errors.put)
        self.hints = KeyHintOverlay(NativeOverlayDesktop())
        self.worker = threading.Thread(target=self.start_taskbar, name="taskbar recovery", daemon=True)
        self.worker.start()

    def start_taskbar(self) -> None:
        try:
            self.taskbar.start()
        except OSError as error:
            self.errors.put(str(error))

    def message(self, hwnd: int, message: int, wparam: int, lparam: int) -> int | None:
        if self.away_screens is not None:
            self.away_screens.message(message, wparam)
        return None

    def record_usage(self, feature: str, details: Mapping[str, Detail]) -> None:
        with suppress(OSError):
            usage.record("assistant", feature, details)

    def toggle_taskbar(self) -> None:
        try:
            self.taskbar.toggle()
        except OSError as error:
            self.actions.problem(str(error))

    def poll_shell(self) -> None:
        if self.tray_host is None:
            return
        sections = self.window.shell_sections
        previous = (sections.app_snapshot, sections.pager_view)
        self.window.show_tray(self.tray_host.poll())  # The tick's render rebuilds an open menu's tray cells.
        if self.application_service is not None:
            with suppress(queue.Empty):
                self.arrangement = self.application_service.results.get_nowait()
                self.applications = self.arrangement.shelf
        self.window.shell_sections.applications((self.applications, self.observations.foreground()))
        arrangement = self.arrangement
        self.window.shell_sections.desktops(pager(arrangement.placed, arrangement.current, chord=self.chord_held), self.navigate, self.app_click)
        # Changed apps or pager targets must also publish section geometry when the island is still,
        # or a pager that loses its hints keeps its wider capsule.
        if previous != (sections.app_snapshot, sections.pager_view):
            self.window.presentation = None
        if self.chord_held:
            self.show_hints()

    def app_click(self, app: App, click: Click) -> None:
        """A pager icon: go to the app, cycling its windows or starting it; right-click lists its windows."""
        match app:
            case WorkspaceView.CANVAS:
                if click is Click.LEFT:
                    self.close_menu(restore=False)
                    self.actions.work()
            case PinnedApp():
                self.application_click(next((slot for slot in self.applications.pinned if slot.app is app), Pinned(app, ())), click)
            case Program(exe=exe):
                running = next((each for each in self.applications.running if each.identity == exe), None)
                if running is not None and click is Click.RIGHT:
                    self.application_click(running, click)
                elif click is not Click.RIGHT:
                    self.close_menu(restore=False)
                    # A configured app key also starts the app when it isn't running.
                    key = next((each for each in APPS if isinstance(each.target, Installed) and each.target.exe.lower() == exe), None)
                    self.navigate(AppKey(key, Source.TOOLBAR) if key is not None else CycleApp(app, Source.TOOLBAR))
            case _:
                assert_never(app)

    def application_click(self, item: Item, click: Click) -> None:
        self.close_menu(restore=False)
        match item:
            case Pinned(windows=windows) | Application(windows=windows) if windows and click is Click.RIGHT:
                chosen = shell.show_menu(int(self.window.winId()), tuple(shell.MenuItem(window.handle, window.title) for window in windows))
                if chosen:
                    self.navigate(ShowWindow(chosen, Source.TOOLBAR))
            case Pinned(app=app):
                self.navigate(CycleApp(app, Source.TOOLBAR))
            case Application(identity=identity):
                self.navigate(CycleApp(Program(identity), Source.TOOLBAR))

    def navigate(self, order: Order) -> None:
        """The application observer owns windows and desktops; it carries out every navigation."""
        if self.application_service is not None:
            self.application_service.order(order)

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
            case Action.OPEN_QUESTION:
                self.open_question()
            case Action.OPEN_INBOX:
                self.actions.inbox()
            case Action.OPEN_NOTICE:
                notice = island_moment.shown(self.notices)
                if notice is not None:
                    self.choose(notice)
            case Action.DISMISS_NOTICE:
                notice = island_moment.shown(self.notices)
                if notice is not None:
                    self.notices = island_moment.read(self.notices, frozenset({notice.identity}))
                    self.render()
            case Action.OPEN_CANVAS:
                self.actions.work()
            case Action.STOP_RECORDING:
                self.actions.record("stop")
            case _:
                assert_never(action)

    def hover(self, key: Key | None) -> None:
        if self.hovered is not key:
            self.hovered = key
            self.notices = island_moment.hover(self.notices, inside=key is Key.ISLAND, now=self.observations.clock())
            self.render()

    def menu(self) -> Menu:
        """The menu for what's happening now, keeping the current selection."""
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
                    placement_paused=self.arrangement.paused,
                    dark_when_away=DARK_WHEN_IDLE_MINUTES if self.away_screens is not None and self.away_screens.setting.enabled else None,
                    sound=sound,
                    tray=tuple(entry.tip or "Tray application" for entry in self.window.tray),
                ),
                self.specs.controls,
            )
        )
        if not isinstance(self.opened, Menu):
            return menu
        return replace(menu, selected=self.opened.selected)

    def request_actions(self) -> RequestActions | None:
        return self.actions.requests

    def requests_changed(self, choices: tuple[Phase, ...]) -> None:
        request = self.opened if isinstance(self.opened, Phase) else None
        choices = tuple(coalesced(stable_phases(choices, (request,) if request is not None else ())))
        self.choices = choices
        if request is not None:
            current = next((phase for phase in choices if phase.key == request.key), None)
            if current is None:
                self.close_menu(restore=False)
            elif current != request:
                self.opened = current
                if self.actions.requests is not None:
                    self.actions.requests.select(current.request)
                self.render()

    def notices_changed(self, current: tuple[Notice, ...]) -> None:
        self.notices = island_moment.observe(self.notices, current, self.observations.clock())
        self.render()

    def open_question(self) -> None:
        """ "Needs you" opens the session's own waiting question, wherever else the bell has news."""
        phase = next((phase for phase in self.choices if hint(phase.turn)), None)
        if phase is not None:
            self.open_request(phase)
        else:
            self.actions.inbox()

    def open_inbox(self, questions: tuple[Phase, ...]) -> bool:
        """The bell's list, or straight to the one question when nothing else waits; False with nothing to show."""
        listed = island_moment.rows(questions, self.notices)
        match listed:
            case ():
                return False
            case (Asked(phase=phase),):
                self.open_request(phase)
            case _:
                self.notices = island_moment.read(self.notices, frozenset(row.identity for row in listed if isinstance(row, Notice)))
                self.expand(Inbox(listed))
        return True

    def choose(self, row: Row) -> None:
        """A question opens in the island; a notice opens its canvas item and counts as read."""
        match row:
            case Asked(phase=phase):
                self.open_request(phase)
            case Notice(identity=identity, target=target):
                self.notices = island_moment.read(self.notices, frozenset({identity}))
                self.close_menu(restore=False)
                if target is not None:
                    self.actions.open_item(target)
                else:
                    self.actions.work()
                self.render()

    def open_request(self, phase: Phase) -> None:
        if self.closed:
            return
        self.expand(phase)
        actions = self.actions.requests
        if actions is not None:
            actions.select(phase.request)

    def open_menu(self) -> None:
        """The island expands into the menu and takes the keyboard from the window that had it."""
        if self.closed:
            return
        if self.actions.requests is not None:
            self.actions.requests.select(None)
        self.opened = None
        self.expand(self.menu())

    def expand(self, opened: Menu | Phase | Inbox) -> None:
        """Take the keyboard from the window that had it, then morph open."""
        if self.opened is None:
            self.menu_target = self.observations.foreground()
        self.opened = opened
        windows.allow_activation(int(self.window.winId()), allowed=True)
        self.window.activateWindow()
        self.window.setFocus()
        self.render()

    def close_menu(self, *, restore: bool) -> None:
        if self.opened is None:
            return
        self.opened = None
        if self.actions.requests is not None:
            self.actions.requests.select(None)
        windows.allow_activation(int(self.window.winId()), allowed=False)
        self.render()
        if restore and self.menu_target:
            self.observations.focus(self.menu_target)

    def select(self, index: int) -> None:
        if isinstance(self.opened, Menu) and self.opened.selected != index:
            self.opened = replace(self.opened, selected=index)
            self.render()

    def pick(self, index: int) -> None:
        if isinstance(self.opened, Menu):
            self.settle_menu(island_menu.choose(self.opened, self.opened.cells[index].entry))

    def key(self, press: island_menu.Press) -> None:
        if isinstance(self.opened, Menu):
            self.settle_menu(island_menu.press(self.opened, press))

    def deactivated(self) -> None:
        """Another window took the keyboard: the menu closes without taking it back."""
        self.close_menu(restore=False)

    def settle_menu(self, outcome: island_menu.Outcome) -> None:
        match outcome:
            case Menu() as menu:
                self.opened = menu
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
                self.actions.tool(tool)
            case Command.CANVAS:
                self.actions.work()
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
            case Command.PLACEMENT:
                self.navigate(Placing.TOGGLE_PAUSE)
            case Command.DARK_WHEN_AWAY:
                if self.away_screens is not None:
                    self.away_screens.toggle()
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

    def layout(self, *, enabled: bool) -> None:
        if enabled != self.layout_enabled:
            self.layout_enabled = enabled
            self.render()

    def chord(self, *, held: bool) -> None:
        self.chord_held = held
        self.show_hints()

    def show_hints(self) -> None:
        """The hints follow the window in front, which can change while the chord is held."""
        if self.hints is None:
            return
        world = self.arrangement.world
        if not self.chord_held or world is None:
            self.hints.show((), self.preference)
            return
        self.hints.show(hints(replace(world, foreground=self.observations.foreground())), self.preference)

    def observed(self) -> Observed:
        asking = self.agent is not None and self.agent.waiting
        moment = island_moment.moment(dictating=self.dictating, asking=asking, notices=self.notices)
        return Observed(
            self.agent,
            self.job,
            self.recording,
            self.ambient,
            self.system,
            self.inbox,
            plain_keyboard=not self.layout_enabled,
            dictating=self.dictating,
            unread=island_moment.unread(self.notices),
            notice=moment if isinstance(moment, Notice) else None,
        )

    def measure(self, view: CapsuleView, opened: Menu | Phase | Inbox | None) -> Content:
        match opened:
            case Phase() if view.key is Key.ISLAND:
                return self.window.measure_request(opened)
            case Inbox(rows=rows) if view.key is Key.ISLAND:
                return self.window.measure_inbox(rows)
            case Menu() if view.key is Key.STATUS:
                return expansion(opened, self.window.measure(view), self.specs.sizes.menu)
            case _:
                return self.window.measure(view)

    def render(self) -> None:
        """Retarget the capsules at what the bar should show now; frames carry them there."""
        if self.closed:
            return
        if isinstance(self.opened, Menu):
            self.opened = self.menu()
        # A notice waits while dictation, a question or anything the person opened holds the island.
        asking = self.agent is not None and self.agent.waiting
        blocked = self.dictating or asking or self.opened is not None
        self.notices = island_moment.advance(self.notices, blocked=blocked, now=self.observations.clock())
        opened = self.opened
        match opened:
            case Menu():
                expanded: Expansion | None = Expansion.MENU
            case Phase():
                expanded = Expansion.REQUEST
            case Inbox():
                expanded = Expansion.INBOX
            case None:
                expanded = None
            case _:
                assert_never(opened)
        self.views = island(self.observed(), self.specs.island, hovered=self.hovered, expanded=expanded)
        shown = tuple(Shown(view, self.measure(view, opened)) for view in self.views)
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
        bar = self.specs.sizes.bar
        metrics = Metrics(width, bar.top, bar.gap, bar.edge)
        framed = frozendict(
            (each.key, each)
            for each in snap(
                frame(placed(self.motion, self.specs.sizes.capsule.height), metrics, order(self.specs.island)), self.window.devicePixelRatioF()
            )
        )
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
        reach = max(
            (max(moving.height.value, moving.height.target) for moving in self.motion.capsules), default=float(self.specs.sizes.capsule.height)
        )
        self.window.present(
            Presented(
                drawn,
                reach,
                self.opened,
                sizes=self.specs.sizes,
                frost=self.frost,
                contrast=contrast,
                glass=self.preference is appearance.Material.GLASS,
                shell_look=self.style(Tint.NONE, self.specs.sizes.capsule.height),
            )
        )
        # A closed menu keeps the last locations: a clicked application anchors its flyout where its icon was.
        if self.tray_host is not None and isinstance(self.opened, Menu):
            self.tray_host.locate(self.window.tray_locations())

    def style(self, tint: Tint, height: float) -> Look:
        pane = (
            desktop_ui.components.appearance.Menu(self.frost)
            if expanded(height, self.specs.sizes)
            else desktop_ui.components.appearance.Capsule(self.frost)
        )
        return look(self.preference, pane, tint)

    def spinning(self) -> bool:
        def spinner(part: object) -> bool:
            match part:
                case Spinner() | Marker.DOTS:
                    return True
                case _:
                    return False

        menu_spinner = isinstance(self.opened, Menu) and self.agent is not None and not self.agent.waiting
        return menu_spinner or any(spinner(part) for view in self.views for slot in view.slots for part in slot)

    def paint_frames(self) -> None:
        if self.closed:
            return
        now, animate = self.observations.clock(), self.visible and self.observations.motion()
        # A frame after the loop was idle starts the motion now, rather than from the last frame.
        elapsed = now - (self.last_frame if self.last_frame is not None else now)
        self.motion = advance(self.motion, elapsed) if animate else finish(self.motion)
        spinning = animate and self.spinning()
        waving = animate and self.dictating and self.opened is None
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
        if self.away_screens is not None:
            self.away_screens.poll(recording=self.recording.capturing)
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

    def respec(self, specs: ui_spec.Specs) -> None:
        """An edited spec checked: lay the bar out again with it."""
        self.specs = specs
        self.window.use(specs.sizes)
        self.render()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.spec_watch.close()
        self.timer.stop()
        self.audio_timer.stop()
        if self.hints is not None:
            self.hints.close()
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
            self.taskbar.close()
            if self.worker is not None:
                self.worker.join(timeout=6)
        finally:
            if self.away_screens is not None:
                self.away_screens.close()
            if self.controls is not None:
                session.unsubscribe(self.controls.handle)
                self.controls.destroy()
            self.resolution.update(active=False)
            self.window.dispose()
            self.loop.close()
