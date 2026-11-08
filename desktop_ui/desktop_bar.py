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
from collections.abc import Callable, Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import assert_never
lazy import os

lazy from PySide6 import QtCore, QtGui

from cell import Cell
from desktop_ui.qt_runtime import prepare
lazy import desktop_ui.components.appearance
lazy import usage
lazy import winapi.ambient
lazy from config import APPS
lazy from contracts.recording_state import RecordingAction
lazy from desktop_ui import island_menu, island_moment, ui_spec
lazy from desktop_ui.agent_progress import Phase
lazy from desktop_ui.ambient import Ambient, SystemStatus
lazy from desktop_ui.application_observer import ApplicationObserver, Arrangement
lazy from desktop_ui.audio_meter import AudioMeter
lazy from desktop_ui.away_screens import AwayScreens
lazy from desktop_ui.bar_events import (
    Act,
    AllControls,
    BarAction,
    BarModel,
    Chose,
    ClickTray,
    Closing,
    Deactivated,
    Effect,
    Event,
    Expand,
    Framed,
    Hovered,
    InboxRequested,
    Keyboard,
    MenuKey,
    Navigate,
    NoticesShown,
    NotificationSettings,
    Opened,
    OpenInbox,
    Opening,
    OpenItem,
    Overlay,
    PaintDue,
    Picked,
    Pressed,
    Record,
    Release,
    Render,
    Rerender,
    Respecced,
    Retargeted,
    Sampled,
    SampleDue,
    Selected,
    SelectRequest,
    SetVolume,
    ShowHints,
    Stop,
    TickDue,
    Ticked,
    ToggleAway,
    ToggleTaskbar,
    TrayClicked,
    TrayShown,
    UseSizes,
    UseTool,
    Visibility,
    VolumeSet,
    Work,
    inbox_rows,
    menu,
    next_frame,
    transition,
)
lazy from desktop_ui.bar_status import StatusObserver
lazy from desktop_ui.components.appearance import Look, look
lazy from desktop_ui.components.meaning import Tint
lazy from desktop_ui.desktop_pager import pager
lazy from desktop_ui.island_layout import Content, Metrics, expansion, frame, snap
lazy from desktop_ui.island_menu import (
    Menu,
)
lazy from desktop_ui.island_model import Action, CapsuleView, Expansion, Key, Marker, Observed, island, order
lazy from desktop_ui.island_moment import Inbox, Notice, Row
lazy from desktop_ui.island_motion import IslandMotion, Shown, placed, retarget
lazy from desktop_ui.island_surface import BarWindow, Drawn, Presented, expanded
lazy from desktop_ui.key_hint_overlay import KeyHintOverlay
lazy from desktop_ui.key_hints import hints
lazy from desktop_ui.navigation import AppKey, CycleApp, Order, ShowWindow, Source
lazy from desktop_ui.overlay_desktop import NativeOverlayDesktop
lazy from desktop_ui.qt_ui import EventLoop, application
lazy from desktop_ui.request_panel import RequestActions
lazy from desktop_ui.shell_controls import TaskbarControl
lazy from desktop_ui.shell_items import Application, Item, Pinned, PinnedApp, Shelf
lazy from desktop_ui.ui_spec_watch import SpecWatch
lazy from desktop_ui.window_layout import App, Program, WorkspaceView
lazy from protocol import Installed, Tool
lazy from usage import Detail
lazy from winapi import appearance, inputs, session, shell, system_notices, windows
lazy from winapi.machine_status import Power, PowerUnavailable
lazy from winapi.notifications import NotificationObserver
lazy from winapi.tray_host import Click, Entry, TrayHost

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
    taskbar: Callable[[], None] | None = field(default=None, kw_only=True)
    """Toggle the taskbar; None toggles the real one."""
    notification_settings: Callable[[], None] | None = field(default=None, kw_only=True)
    """Open notification settings; None opens Windows' own."""


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


@dataclass(frozen=True, slots=True)
class _Shell:
    """The production desktop's native owners: notifications, system status, shell controls and taskbar recovery."""

    notifications: NotificationObserver
    status: StatusObserver
    controls: shell.AppWindow
    away: AwayScreens
    tray: TrayHost
    applications: ApplicationObserver
    hints: KeyHintOverlay
    worker: threading.Thread


@dataclass(frozen=True, slots=True)
class _Reporter:
    """What the bar window, its loop and timers report, delivered to the bar once it exists.

    They are made before the bar, so `deliver` holds it once it does: the Qt-boundary
    binding. Each call becomes an event, stamped with the bar's clock where it matters.
    """

    deliver: Cell[Callable[[Event], None] | None]
    clock: Callable[[], float]
    requests: RequestActions | None

    def report(self, event: Event) -> None:
        if (handle := self.deliver.get()) is not None:
            handle(event)

    def press(self, action: Action) -> None:
        self.report(Pressed(action))

    def hover(self, key: Key | None) -> None:
        self.report(Hovered(key, self.clock()))

    def select(self, index: int) -> None:
        self.report(Selected(index))

    def pick(self, index: int) -> None:
        self.report(Picked(index))

    def volume(self, level: float) -> None:
        self.report(VolumeSet(level))

    def tray(self, slot: int, click: Click) -> None:
        self.report(TrayClicked(slot, click))

    def key(self, press: island_menu.Press) -> None:
        self.report(MenuKey(press))

    def deactivated(self) -> None:
        self.report(Deactivated())

    def request_actions(self) -> RequestActions | None:
        return self.requests

    def choose(self, row: Row) -> None:
        self.report(Chose(row))

    def render(self) -> None:
        self.report(Rerender())


@dataclass(frozen=True, slots=True)
class DesktopBar:
    """The bar's native owners and window, and the fold of everything reported to it into what it shows."""

    actions: BarActions
    observations: BarObservations
    reporter: _Reporter
    taskbar: TaskbarControl
    shell: _Shell | None
    audio_meter: AudioMeter | None
    errors: queue.Queue[str]
    loop: EventLoop
    materials: appearance.FrostSampler
    resolution: appearance.TimerResolution
    window: BarWindow
    spec_watch: SpecWatch[ui_spec.Specs]
    timer: QtCore.QTimer
    """The 100 ms desktop observation tick."""
    audio_timer: QtCore.QTimer
    """The 50 ms microphone trace while dictating."""
    _model: Cell[BarModel]

    # Actions, native-shell lifetime, audio ownership and desktop observations
    # are separate composition dependencies rather than UI options.
    @classmethod
    def open(
        cls,
        actions: BarActions,
        *,
        native_shell: bool = True,
        audio_level: Callable[[], float | None] | None = None,
        observations: BarObservations | None = None,
    ) -> DesktopBar:
        observed = BarObservations() if observations is None else observations
        deliver: Cell[Callable[[Event], None] | None] = Cell(None)
        reporter = _Reporter(deliver, observed.clock, actions.requests)
        errors: queue.Queue[str] = queue.Queue()
        specs = ui_spec.bar_specs(reload=False)
        loop = EventLoop.start(application(), lambda: reporter.report(PaintDue()))
        window = BarWindow(loop, reporter, specs.sizes)
        spec_watch = SpecWatch[ui_spec.Specs].start(
            observed.spec_folder, ui_spec.bar_specs, specs, lambda changed: reporter.report(Respecced(changed)), errors.put
        )
        tick, audio = QtCore.QTimer(window), QtCore.QTimer(window)
        tick.setInterval(100)
        tick.timeout.connect(lambda: reporter.report(TickDue()))
        audio.setInterval(50)
        audio.setTimerType(QtCore.Qt.TimerType.PreciseTimer)
        audio.timeout.connect(lambda: reporter.report(SampleDue()))
        model = BarModel(
            specs,
            visible=native_shell,
            preference=observed.material(),
            ambient=Ambient(observed.local_time().strftime("%H:%M"), PowerUnavailable.UNKNOWN),
        )
        bar = cls(
            actions,
            observed,
            reporter,
            TaskbarControl(),
            None,
            None,
            errors,
            loop,
            appearance.FrostSampler(),
            appearance.TimerResolution(),
            window,
            spec_watch,
            tick,
            audio,
            Cell(model),
        )
        try:
            bar = replace(bar, audio_meter=AudioMeter.start(audio_level) if audio_level is not None else None)
            if native_shell:
                bar = replace(bar, shell=bar._start_shell())
            deliver.set(bar.handle)
            bar.timer.start()
            bar.handle(Rerender())
            bar.handle(TickDue())
        except BaseException:
            bar.close()
            raise
        return bar

    def _start_shell(self) -> _Shell:
        notifications = NotificationObserver.start()
        status = StatusObserver.start()
        away = AwayScreens.start(_record_usage)

        def message(_hwnd: int, message: int, wparam: int, _lparam: int) -> int | None:
            away.message(message, wparam)
            return None

        controls = shell.AppWindow.create("workspace shell controls", message)
        try:
            session.subscribe(controls.handle)
        except OSError as error:
            self.errors.put(f"Screens can't go dark when locked: {error}")
        worker = threading.Thread(target=self._start_taskbar, name="taskbar recovery", daemon=True)
        built = _Shell(
            notifications,
            status,
            controls,
            away,
            TrayHost.start(),
            ApplicationObserver.start(self.errors.put),
            KeyHintOverlay(NativeOverlayDesktop()),
            worker,
        )
        worker.start()
        return built

    def _start_taskbar(self) -> None:
        try:
            self.taskbar.start()
        except OSError as error:
            self.errors.put(str(error))

    # ---- what the model says ------------------------------------------------------------

    @property
    def model(self) -> BarModel:
        return self._model.get()

    @property
    def visible(self) -> bool:
        return self.model.visible

    @property
    def opened(self) -> Opened | None:
        return self.model.opened

    @property
    def system(self) -> SystemStatus:
        return self.model.system

    @property
    def ambient(self) -> Ambient:
        return self.model.ambient

    @property
    def motion(self) -> IslandMotion:
        return self.model.motion

    @property
    def closed(self) -> bool:
        return self.model.closed

    def menu(self) -> Menu:
        return menu(self.model)

    # ---- the fold ----------------------------------------------------------------------

    def handle(self, event: Event) -> None:
        """Qt thread: fold `event` into the model and perform its effects in order."""
        if self.model.closed and not isinstance(event, Closing):
            return
        model, effects = transition(self.model, event)
        self._model.set(model)
        for effect in effects:
            for reported in self._perform(effect):
                self.handle(reported)

    def _perform(self, effect: Effect) -> Iterator[Event]:
        match effect:
            case Render():
                yield self._retargeted()
                yield PaintDue()
            case Expand(opened, remember):
                target = self.observations.foreground() if remember else None
                windows.allow_activation(int(self.window.winId()), allowed=True)
                self.window.activateWindow()
                self.window.setFocus()
                yield Opening(opened, target)
            case Release(target):
                windows.allow_activation(int(self.window.winId()), allowed=False)
                if target:
                    self.observations.focus(target)
            case SelectRequest(request):
                if self.actions.requests is not None:
                    self.actions.requests.select(request)
            case Act(action):
                self._act(action)
            case Navigate(order):
                if self.shell is not None:
                    self.shell.applications.order(order)
            case ToggleTaskbar() | ToggleAway() | NotificationSettings() | SetVolume() | ClickTray() | ShowHints():
                self._shell_effect(effect)
            case UseSizes(sizes):
                self.window.use(sizes)
            case PaintDue():
                yield from self._paint()
            case TickDue():
                yield from self._tick()
            case SampleDue():
                yield from self._sample_audio()
            case _:
                assert_never(effect)

    def _act(self, action: BarAction) -> None:
        match action:
            case Work():
                self.actions.work()
            case Stop():
                self.actions.stop()
            case Record(action=recording):
                self.actions.record(recording)
            case OpenInbox():
                self.actions.inbox()
            case OpenItem(target):
                self.actions.open_item(target)
            case Keyboard():
                self.actions.keyboard()
            case Overlay():
                self.actions.overlay()
            case AllControls():
                self.actions.menu()
            case UseTool(tool):
                self.actions.tool(tool)
            case _:
                assert_never(action)

    def _shell_effect(self, effect: ToggleTaskbar | ToggleAway | NotificationSettings | SetVolume | ClickTray | ShowHints) -> None:
        match effect:
            case ToggleTaskbar():
                self.toggle_taskbar()
            case ToggleAway():
                if self.shell is not None:
                    self.shell.away.toggle()
            case NotificationSettings():
                if self.actions.notification_settings is not None:
                    self.actions.notification_settings()
                else:
                    os.startfile("ms-settings:notifications")
            case SetVolume(level):
                if self.shell is not None:
                    self.shell.status.set_volume(level)
            case ClickTray(slot, click):
                entries = self.window.tray
                if self.shell is not None and slot < len(entries):
                    self.shell.tray.click(entries[slot], click, inputs.cursor_position())
            case ShowHints():
                self._show_hints()
            case _:
                assert_never(effect)

    def toggle_taskbar(self) -> None:
        if self.actions.taskbar is not None:
            self.actions.taskbar()
            return
        try:
            self.taskbar.toggle()
        except OSError as error:
            self.actions.problem(str(error))

    def _show_hints(self) -> None:
        """The hints follow the window in front, which can change while the chord is held."""
        if self.shell is None:
            return
        model = self.model
        world = model.arrangement.world
        if not model.chord_held or world is None:
            self.shell.hints.show((), model.preference)
            return
        self.shell.hints.show(hints(replace(world, foreground=self.observations.foreground())), model.preference)

    # ---- measuring and painting ----------------------------------------------------------

    def _observed(self, model: BarModel) -> Observed:
        asking = model.agent is not None and model.agent.waiting
        moment = island_moment.moment(dictating=model.dictating, asking=asking, notices=model.notices)
        return Observed(
            model.agent,
            model.job,
            model.recording,
            model.ambient,
            model.system,
            model.inbox,
            plain_keyboard=not model.layout_enabled,
            dictating=model.dictating,
            unread=island_moment.unread(model.notices),
            notice=moment if isinstance(moment, Notice) else None,
        )

    def _measure(self, model: BarModel, view: CapsuleView, opened: Opened | None) -> Content:
        match opened:
            case Phase() if view.key is Key.ISLAND:
                return self.window.measure_request(opened)
            case Inbox(rows=rows) if view.key is Key.ISLAND:
                return self.window.measure_inbox(rows)
            case Menu() if view.key is Key.STATUS:
                return expansion(opened, self.window.measure(view), model.specs.sizes.menu)
            case _:
                return self.window.measure(view)

    def _retargeted(self) -> Event:
        """Retarget the capsules at what the bar should show now; frames carry them there."""
        model = self.model
        opened = menu(model) if isinstance(model.opened, Menu) else model.opened
        # A notice waits while dictation, a question or anything the person opened holds the island.
        asking = model.agent is not None and model.agent.waiting
        notices = island_moment.advance(model.notices, blocked=model.dictating or asking or opened is not None, now=self.observations.clock())
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
        current = replace(model, notices=notices, opened=opened)
        views = island(self._observed(current), model.specs.island, hovered=model.hovered, expanded=expanded)
        shown = tuple(Shown(view, self._measure(model, view, opened)) for view in views)
        motion = retarget(model.motion, shown, animate=self.visible and self.observations.motion())
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
        self.window.setVisible(self.visible)
        return Retargeted(views, motion, notices, opened)

    def _draw(self, model: BarModel) -> None:
        width = QtGui.QGuiApplication.primaryScreen().geometry().width()
        bar = model.specs.sizes.bar
        metrics = Metrics(width, bar.top, bar.gap, bar.edge)
        framed = frozendict(
            (each.key, each)
            for each in snap(
                frame(placed(model.motion, model.specs.sizes.capsule.height), metrics, order(model.specs.island)), self.window.devicePixelRatioF()
            )
        )
        match model.preference:
            case appearance.Contrast():
                contrast = True
            case appearance.Material.GLASS | appearance.Material.SOLID:
                contrast = False
            case _:
                assert_never(model.preference)
        drawn = tuple(
            Drawn(
                moving.view,
                moving.content,
                moving.previous,
                moving.fade.value,
                _style(model, moving.view.tint, moving.content.height),
                framed[moving.key],
            )
            for moving in model.motion.capsules
            if moving.key in framed
        )
        # The window keeps the room a capsule is heading for, so it resizes only as an expansion starts and settles.
        reach = max(
            (max(moving.height.value, moving.height.target) for moving in model.motion.capsules), default=float(model.specs.sizes.capsule.height)
        )
        self.window.present(
            Presented(
                drawn,
                reach,
                model.opened,
                sizes=model.specs.sizes,
                frost=model.frost,
                contrast=contrast,
                glass=model.preference is appearance.Material.GLASS,
                shell_look=_style(model, Tint.NONE, model.specs.sizes.capsule.height),
            )
        )
        # A closed menu keeps the last locations: a clicked application anchors its flyout where its icon was.
        if self.shell is not None and isinstance(model.opened, Menu):
            self.shell.tray.locate(self.window.tray_locations())

    def _paint(self) -> Iterator[Event]:
        model = self.model
        now = self.observations.clock()
        drawn = next_frame(model, now, animate=self.visible and self.observations.motion())
        self.window.wave_progress = drawn.wave_progress
        self.window.spin_angle = drawn.spin_angle
        self._draw(replace(model, motion=drawn.motion))
        if drawn.indicators:
            for key, capsule in self.window.capsules.items():
                if key in (Key.ISLAND, Key.STATUS, Key.AGENT, Key.JOB):
                    capsule.update_indicators()
        self.resolution.update(active=drawn.running)
        self.loop.watch(visible=drawn.running)
        yield Framed(drawn.motion, now if drawn.running else None)

    def _tick(self) -> Iterator[Event]:
        try:
            self.taskbar.enforce()
        except OSError as error:
            self.errors.put(str(error))
        while not self.errors.empty():
            self.actions.problem(self.errors.get_nowait())
        model = self.model
        if self.shell is not None:
            self._poll_notifications(self.shell)
            self.shell.away.poll(recording=model.recording.capturing)
        now = self.observations.clock()
        applications, arrangement = self._poll_shell(model)
        power, next_power = (self.observations.power(), now + 15) if now >= model.next_power else (model.power, model.next_power)
        system = model.system
        if self.shell is not None:
            with suppress(queue.Empty):
                system = self.shell.status.results.get_nowait()
        sample_bounds = self.window.bounds(Key.ISLAND) or self.window.bounds(Key.STATUS)
        # Small glass takes its scheme from the desktop beside the island.
        frost = next((sample.frost for sample in self.materials.read() if sample.bounds == sample_bounds), model.frost)
        preference, next_material = model.preference, model.next_material
        if now >= model.next_material:
            preference, next_material = self.observations.material(), now + 0.75
            if preference is appearance.Material.GLASS and sample_bounds is not None:
                self.materials.submit((sample_bounds,))
        # Each tick re-measures, so a growing timer pushes its neighbours out.
        yield Ticked(
            system,
            power,
            next_power,
            Ambient(self.observations.local_time().strftime("%H:%M"), power),
            preference,
            frost,
            next_material,
            sample_bounds,
            applications,
            arrangement,
            taskbar_revealed=self.taskbar.revealed,
            dark_when_away=self.shell.away.setting.enabled if self.shell is not None else None,
            tray_tips=tuple(entry.tip or "Tray application" for entry in self.window.tray),
        )

    def _poll_shell(self, model: BarModel) -> tuple[Shelf, Arrangement]:
        if self.shell is None:
            return model.applications, model.arrangement
        sections = self.window.shell_sections
        previous = (sections.app_snapshot, sections.pager_view)
        self.window.show_tray(self.shell.tray.poll())  # The tick's render rebuilds an open menu's tray cells.
        arrangement = model.arrangement
        with suppress(queue.Empty):
            arrangement = self.shell.applications.results.get_nowait()
        applications = arrangement.shelf if arrangement is not model.arrangement else model.applications
        sections.applications((applications, self.observations.foreground()))
        sections.desktops(pager(arrangement.placed, arrangement.current, chord=model.chord_held), self.navigate, self.app_click)
        # Changed apps or pager targets must also publish section geometry when the island is still,
        # or a pager that loses its hints keeps its wider capsule.
        if previous != (sections.app_snapshot, sections.pager_view):
            self.window.presentation = None
        if model.chord_held:
            self._show_hints()
        return applications, arrangement

    def _poll_notifications(self, built: _Shell) -> None:
        with suppress(queue.Empty):
            observed = built.notifications.results.get_nowait()
            match observed:
                case system_notices.Observed():
                    self.actions.notices(observed)
                case system_notices.Unavailable():
                    pass

    def _sample_audio(self) -> Iterator[Event]:
        model = self.model
        if not model.dictating:
            return
        # Begin at the last painted interpolation, including if a sample
        # arrives early. The bounded history stays with its Qt paint owner.
        self.window.wave_from = tuple(self.window.trace())
        self.window.samples.append(level(self.audio_meter.level() if self.audio_meter is not None else None))
        self.window.wave_progress = 0.0 if self.visible and self.observations.motion() else 1.0
        capsule = self.window.capsules.get(Key.ISLAND)
        if capsule is not None and any(Marker.WAVE in slot for view in model.views for slot in view.slots):
            capsule.update_indicators()
        yield Sampled(self.observations.clock())

    def app_click(self, app: App, click: Click) -> None:
        """A pager icon: go to the app, cycling its windows or starting it; right-click lists its windows."""
        match app:
            case WorkspaceView.CANVAS:
                if click is Click.LEFT:
                    self.close_menu(restore=False)
                    self.actions.work()
            case PinnedApp():
                self._application_click(next((slot for slot in self.model.applications.pinned if slot.app is app), Pinned(app, ())), click)
            case Program(exe=exe):
                running = next((each for each in self.model.applications.running if each.identity == exe), None)
                if running is not None and click is Click.RIGHT:
                    self._application_click(running, click)
                elif click is not Click.RIGHT:
                    self.close_menu(restore=False)
                    # A configured app key also starts the app when it isn't running.
                    key = next((each for each in APPS if isinstance(each.target, Installed) and each.target.exe.lower() == exe), None)
                    self.navigate(AppKey(key, Source.TOOLBAR) if key is not None else CycleApp(app, Source.TOOLBAR))
            case _:
                assert_never(app)

    def _application_click(self, item: Item, click: Click) -> None:
        self.close_menu(restore=False)
        match item:
            case Pinned(windows=listed) | Application(windows=listed) if listed and click is Click.RIGHT:
                chosen = shell.show_menu(int(self.window.winId()), tuple(shell.MenuItem(window.handle, window.title) for window in listed))
                if chosen:
                    self.navigate(ShowWindow(chosen, Source.TOOLBAR))
            case Pinned(app=app):
                self.navigate(CycleApp(app, Source.TOOLBAR))
            case Application(identity=identity):
                self.navigate(CycleApp(Program(identity), Source.TOOLBAR))

    # ---- what others tell the bar ------------------------------------------------------

    def render(self) -> None:
        self.handle(Rerender())

    def show(self, *, visible: bool) -> None:
        """Show or hide the bar; hidden, it lays out without animating."""
        self.handle(Visibility(visible))

    def show_tray(self, entries: tuple[Entry, ...]) -> None:
        """The tray icons the menu lists."""
        self.window.show_tray(entries)
        self.handle(TrayShown(tuple(entry.tip or "Tray application" for entry in entries)))

    def navigate(self, order: Order) -> None:
        """The application observer owns windows and desktops; it carries out every navigation."""
        self.handle(Navigate(order))

    def hover(self, key: Key | None) -> None:
        self.handle(Hovered(key, self.observations.clock()))

    def deactivated(self) -> None:
        self.handle(Deactivated())

    def close_menu(self, *, restore: bool) -> None:
        self.handle(Pressed(Action.CLOSE_MENU) if restore else Deactivated())

    def open_inbox(self, questions: tuple[Phase, ...]) -> bool:
        """The bell's list, or straight to the one question when nothing else waits; False with nothing to show."""
        if not inbox_rows(self.model, questions):
            return False
        self.handle(InboxRequested(questions))
        return True

    def notices_changed(self, current: tuple[Notice, ...]) -> None:
        self.handle(NoticesShown(current, self.observations.clock()))

    def close(self) -> None:
        if self.model.closed:
            return
        self.handle(Closing())
        self.spec_watch.close()
        self.timer.stop()
        self.audio_timer.stop()
        if self.audio_meter is not None:
            self.audio_meter.close()
        self.materials.close()
        built = self.shell
        if built is not None:
            built.hints.close()
            built.status.close()
            built.notifications.close()
            built.tray.close()
            built.applications.close()
        try:
            self.taskbar.close()
            if built is not None:
                built.worker.join(timeout=6)
        finally:
            if built is not None:
                built.away.close()
                session.unsubscribe(built.controls.handle)
                built.controls.destroy()
            self.resolution.update(active=False)
            self.window.dispose()
            self.loop.close()


def _record_usage(feature: str, details: Mapping[str, Detail]) -> None:
    with suppress(OSError):
        usage.record("assistant", feature, details)


def _style(model: BarModel, tint: Tint, height: float) -> Look:
    pane = (
        desktop_ui.components.appearance.Menu(model.frost)
        if expanded(height, model.specs.sizes)
        else desktop_ui.components.appearance.Capsule(model.frost)
    )
    return look(model.preference, pane, tint)
