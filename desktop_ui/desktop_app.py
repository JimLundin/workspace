"""The desktop: Workspace's bar, tray, key map, window placement, dictation and meetings.

The keyboard sends every request and its indicator, key, chord and layout
messages to the desktop's hidden control window. Dictation and meetings
(`desktop_ui.voice`) are called here on the Qt thread; what their workers
report arrives as events in the same inbox and is shown here. Qt owns the
process's main thread, and every view is made and changed on it, as its
effects are performed.
"""

import os
import queue
import subprocess
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Final, assert_never

lazy import shiboken6
lazy from PySide6 import QtCore, QtWidgets

import components
import launch
import protocol
import winapi.shapes
from assistant.llm import settings_from
from cell import Cell
from config import APPS
from desktop_ui import bar_events
from desktop_ui.desktop_control import (
    Beep,
    Chord,
    Controlled,
    DesktopState,
    Effect,
    Event,
    ExpireCapture,
    FeatureRequest,
    Flash,
    HandleKey,
    Indicate,
    Indicated,
    Launch,
    LayoutReported,
    LayoutShown,
    Log,
    MenuChosen,
    MenuRequested,
    Navigate,
    OpenLogs,
    OverlayEnabled,
    OverlayToggled,
    PressedKeys,
    Problem,
    Quit,
    Record,
    RestoreTray,
    ShowActivity,
    ShowIdle,
    ShowKeymap,
    ShowMenu,
    ShowOverlay,
    ShowSwitcher,
    ShowVoice,
    SwitchWindows,
    ToggleLayout,
    ToggleMeeting,
    ToggleTaskbar,
    TrayNotify,
    TrayShow,
    UseLayout,
    VoiceShown,
    control_event,
    menu_items,
    transition,
)
from desktop_ui.navigation import ShowWindow
from desktop_ui.overlay import OverlayState, load_enabled, save_enabled
from desktop_ui.qt_runtime import prepare
from desktop_ui.tray import Tray
from desktop_ui.view_publication import log
from desktop_ui.voice import Voice
from protocol import WM_CHORD, WM_INDICATOR, WM_KEY_STATE, WM_LAYOUT_STATE, WM_QUERY_LAYOUT_STATE, WM_REQUEST, WM_WINDOWS_KEY_TAP
from usage import DIRECTORY
from winapi import screen, shell, system, windows
from winapi.shapes import Rect
lazy from desktop_ui.components.appearance import scheme, tokens, tooltip_style
lazy from desktop_ui.components.widgets import near_pointer, show_window
lazy from desktop_ui.desktop_bar import BarActions, DesktopBar
lazy from desktop_ui.keymap_views import KeymapOverlay, KeymapWindow
lazy from desktop_ui.layer_indicator import Indicator
lazy from desktop_ui.qt_ui import application
lazy from desktop_ui.vector_icons import icon
lazy from desktop_ui.window_switcher import WindowSwitcher

prepare()

LOCK_NAME: Final = "Local\\workspace-desktop"
WM_TRAY: Final = system.WM_APP + 20
WM_EVENTS: Final = system.WM_APP + 22
"""Any thread -> Qt thread: events are waiting in the inbox."""
CAPTURE_TIMER_MS: Final = 1000
"""How often the control window checks a voice capture against its time limit."""


def indicator_area() -> Rect:
    """Where the layer indicator goes: the bottom of the main monitor."""
    monitors = screen.monitors()
    return next((m.work for m in monitors if m.primary), monitors[0].work)


def window_event(message: int, wparam: int, lparam: int) -> Event | None:
    """What a message to the control window reports."""
    if message == shell.TASKBAR_CREATED:
        return RestoreTray()
    if message == WM_TRAY and lparam in (system.WM_LBUTTONUP, system.WM_RBUTTONUP):
        return MenuRequested()
    if message in (WM_KEY_STATE, WM_REQUEST):
        return Controlled(control_event(message, wparam, lparam, APPS))
    if message == WM_INDICATOR:
        return Indicated(wparam)
    if message == WM_LAYOUT_STATE:
        return LayoutReported(wparam)
    if message == WM_CHORD:
        return Chord(held=bool(wparam))
    if message == WM_WINDOWS_KEY_TAP:
        return ToggleTaskbar()
    if message == system.WM_TIMER:  # the capture timer, the control window's only timer
        return ExpireCapture(time.monotonic())
    if message == system.WM_CLOSE:  # Quit Workspace, or a test
        return Quit()
    return None


@dataclass(frozen=True, slots=True)
class Inbox:
    """The Qt thread's events: any thread reports one, and the control window's procedure folds them.

    Qt's own loop dispatches the control window's messages, so the procedure is
    where events reach the application. Events reported before `connect` wait
    in the queue; connecting is the one late binding, at that boundary.
    """

    window: shell.AppWindow
    pending: queue.SimpleQueue[Event]
    _handler: Cell[Callable[[Event], None] | None]

    @classmethod
    def open(cls, window: components.Window) -> Inbox:
        pending = queue.SimpleQueue[Event]()
        handler: Cell[Callable[[Event], None] | None] = Cell(None)

        def procedure(hwnd: int, message: int, wparam: int, lparam: int) -> int | None:
            if message == WM_EVENTS:
                _drain(pending, handler)
                return 0
            if (event := window_event(message, wparam, lparam)) is None:
                return None
            pending.put(event)
            system.post_message(hwnd, WM_EVENTS, 0, 0)
            return 0

        return cls(shell.AppWindow.create(window.title, procedure, class_name=window.window_class), pending, handler)

    def report(self, event: Event) -> None:
        """Any thread: queue `event` for the Qt thread."""
        self.pending.put(event)
        system.post_message(self.window.handle, WM_EVENTS, 0, 0)

    def connect(self, handler: Callable[[Event], None]) -> None:
        """Qt thread: fold queued and future events with `handler`."""
        self._handler.set(handler)
        system.post_message(self.window.handle, WM_EVENTS, 0, 0)


def _drain(pending: queue.SimpleQueue[Event], handler: Cell[Callable[[Event], None] | None]) -> None:
    if (handle := handler.get()) is None:
        return
    while True:
        try:
            event = pending.get_nowait()
        except queue.Empty:
            return
        try:
            handle(event)
        except Exception:
            log(traceback.format_exc())


@dataclass(frozen=True, slots=True)
class _Views:
    """The views built so far, on the Qt thread, each made on first use."""

    bar: DesktopBar | None = None
    switcher: WindowSwitcher | None = None
    indicator: Indicator | None = None
    keymap: KeymapWindow | None = None
    overlay: KeymapOverlay | None = None


@dataclass(frozen=True, slots=True, weakref_slot=True)
class DesktopApp:
    """The desktop's views, tray, dictation and meetings, and the Qt-thread fold of their events into effects."""

    root: QtWidgets.QApplication
    inbox: Inbox
    voice: Voice
    tray: Tray
    state: Cell[DesktopState]
    views: Cell[_Views] = field(default_factory=lambda: Cell(_Views()))
    """Replaced only on the Qt thread."""

    @classmethod
    def compose(cls, root: QtWidgets.QApplication, voice: Voice, inbox: Inbox) -> DesktopApp:
        state = Cell(DesktopState(overlay=OverlayState(enabled=load_enabled())))
        app = cls(root, inbox, voice, Tray.add(inbox.window.handle, WM_TRAY), state)
        inbox.connect(app.handle)
        return app

    def start(self) -> None:
        """Qt thread: the bar, the capture timer and the workers, then the layout's state, then readiness."""
        report = self.inbox.report
        try:
            bar = DesktopBar.open(
                BarActions(
                    record=lambda action: report(Record(action)),
                    keyboard=self.show_keymap,
                    overlay=lambda: report(OverlayToggled()),
                    menu=lambda: report(MenuRequested()),
                    problem=lambda message: report(Problem(message)),
                    tool=lambda tool: report(Controlled(FeatureRequest(tool, down=True))),
                ),
                audio_level=self.voice.level,
            )
            self.views.update(lambda views: replace(views, bar=bar))
            bar.handle(bar_events.OverlayShown(self.state.get().overlay.enabled))
        except Exception:
            log(traceback.format_exc())
            report(Problem("The Workspace bar could not start. The tray remains available."))
        system.set_window_timer(self.inbox.window.handle, CAPTURE_TIMER_MS)
        self.voice.start()
        if (layout := windows.find(components.LAYOUT.window.title)) is not None:
            system.post_message(layout, WM_QUERY_LAYOUT_STATE, 0, 0)
        self.handle(ShowIdle())

    @property
    def _bar(self) -> DesktopBar | None:
        return self.views.get().bar

    # ---- the fold ----------------------------------------------------------------------

    def handle(self, event: Event) -> None:
        """Qt thread: fold `event`, perform its effects in order, and fold what they report."""
        state, effects = transition(self.state.get(), event)
        self.state.set(state)
        for effect in effects:
            if (reported := self.perform(effect)) is not None:
                self.handle(reported)

    def perform(self, effect: Effect) -> Event | None:
        """Carry out `effect`; what it reports back (a menu choice, a refusal) is folded next."""
        match effect:
            case ShowVoice() | ShowIdle() | HandleKey() | UseLayout() | ExpireCapture() | Record() | ToggleMeeting():
                return self._voice(effect)
            case RestoreTray() | TrayNotify() | TrayShow() | Log() | Beep() | Launch() | OpenLogs():
                self._shell(effect)
            case ShowActivity() | Navigate() | Chord() | ToggleTaskbar() | LayoutShown():
                if (bar := self._bar) is not None:
                    self._on_bar(bar, effect)
            case SwitchWindows():
                self._list_windows()
            case ShowSwitcher(choices):
                self._show_switcher(choices)
            case ShowKeymap():
                self.show_keymap()
            case ShowOverlay(overlay):
                self._show_overlay(overlay)
            case OverlayEnabled(enabled):
                if (bar := self._bar) is not None:
                    bar.handle(bar_events.OverlayShown(enabled))
                try:
                    save_enabled(enabled=enabled)
                except OSError:
                    return Problem("The overlay changed, but its setting couldn't be saved.")
            case Flash(text):
                self._indicator().flash(text, indicator_area(), 1.2)
            case PressedKeys(pressed, reset):
                if (overlay := self.views.get().overlay) is not None:
                    overlay.set_pressed(pressed, reset=reset)
            case Indicate(text):
                self._indicator().set(text, indicator_area())
            case ToggleLayout():
                layout = windows.find(components.LAYOUT.window.title)
                if layout is None or not system.post_message(layout, protocol.WM_TOGGLE_LAYOUT, 0, 0):
                    return Problem("Couldn't reach the layout. Try Start layout or Restart layout.")
            case ShowMenu(state):
                return MenuChosen(shell.show_menu(self.inbox.window.handle, tuple(menu_items(state))))
            case Quit():
                self.quit()
            case _:
                assert_never(effect)
        return None

    def _shell(self, effect: RestoreTray | TrayNotify | TrayShow | Log | Beep | Launch | OpenLogs) -> None:
        match effect:
            case RestoreTray():
                self.tray.restore()
            case TrayNotify(title, text, warning):
                self.tray.notify(title, text, warning=warning)
            case TrayShow(shown):
                self.tray.show(shown)
            case Log(text):
                log(text)
            case Beep():
                system.beep(system.MB_ICONEXCLAMATION)
            case Launch(command, names):
                launched(command, *names)
            case OpenLogs():
                DIRECTORY.mkdir(parents=True, exist_ok=True)
                os.startfile(DIRECTORY)
            case _:
                assert_never(effect)

    def _on_bar(self, bar: DesktopBar, effect: ShowActivity | Navigate | Chord | ToggleTaskbar | LayoutShown) -> None:
        match effect:
            case ShowActivity(change):
                bar.handle(change)
            case Navigate(order):
                bar.navigate(order)
            case Chord(held):
                bar.handle(bar_events.ChordHeld(held))
            case ToggleTaskbar():
                bar.toggle_taskbar()
            case LayoutShown(enabled):
                bar.handle(bar_events.LayoutShown(enabled))
            case _:
                assert_never(effect)

    def _voice(self, effect: ShowVoice | ShowIdle | HandleKey | UseLayout | ExpireCapture | Record | ToggleMeeting) -> Event | None:
        voice = self.voice
        try:
            match effect:
                case ShowVoice(shown):
                    return VoiceShown(voice.shown(shown))
                case ShowIdle():
                    return VoiceShown(voice.idle())
                case HandleKey(tool, down):
                    voice.dictation.handle(tool, down=down)
                case UseLayout(on):
                    voice.use_layout(on=on)
                case ExpireCapture(at):
                    voice.dictation.expire_capture(at)
                case Record(action):
                    voice.record(action)
                case ToggleMeeting():
                    voice.toggle_meeting()
                case _:
                    assert_never(effect)
        except (OSError, ValueError) as error:
            return Problem(str(error))
        return None

    # ---- the views ---------------------------------------------------------------------

    def show_keymap(self) -> None:
        keymap = self.views.get().keymap
        if keymap is None or not shiboken6.isValid(keymap.window):
            opened = KeymapWindow.open()
            self.views.update(lambda views: replace(views, keymap=opened))
        else:
            show_window(keymap.window, focus=True, target=keymap.canvas)

    def _show_overlay(self, overlay: OverlayState) -> None:
        """A faded key map that follows the current layer without taking keyboard focus."""
        shown = self.views.get().overlay
        if shown is None:
            if not overlay.visible:
                return
            shown = KeymapOverlay.open()
            opened = shown
            self.views.update(lambda views: replace(views, overlay=opened))
        shown.show(overlay.layer, overlay.title, indicator_area(), visible=overlay.visible, pressed=overlay.pressed)

    def _indicator(self) -> Indicator:
        if (indicator := self.views.get().indicator) is None:
            indicator = Indicator.build()
            built = indicator
            self.views.update(lambda views: replace(views, indicator=built))
        return indicator

    def _list_windows(self) -> None:
        """Read the window list off the Qt thread; the switcher shows it when it arrives."""

        def collect() -> None:
            own = os.getpid()
            self.inbox.report(ShowSwitcher(tuple(w for w in windows.windows() if windows.process_id(w.handle) != own)))

        threading.Thread(target=collect, name="window list", daemon=True).start()

    def _show_switcher(self, choices: tuple[winapi.shapes.Window, ...]) -> None:
        shown = self.views.get().switcher
        if shown is not None and shown.isVisible():
            shown.activate()
            return

        def focus(handle: int) -> None:
            if (bar := self._bar) is not None:
                bar.navigate(ShowWindow(handle))

        current = WindowSwitcher(choices, focus)
        self.views.update(lambda views: replace(views, switcher=current))

        def cleared(_: int) -> None:
            if self.views.get().switcher is current:
                self.views.update(lambda views: replace(views, switcher=None))

        current.finished.connect(cleared)
        near_pointer(current, current.width(), current.height())
        show_window(current, focus=True, target=current.search)

    # ---- quitting ----------------------------------------------------------------------

    def close_bar(self) -> None:
        if (bar := self._bar) is not None:
            try:
                bar.close()
            except Exception as error:
                log(f"The Workspace bar did not close cleanly: {error}")
            self.views.update(lambda views: replace(views, bar=None))

    def quit(self) -> None:
        """Close the views and the tray, then end Qt's loop."""
        self.close_bar()
        self.tray.remove()
        self.inbox.window.destroy()
        self.root.quit()


def launched(command: str, *names: str) -> None:
    """Run the launcher on its own, so it outlives this program when it restarts or stops the desktop."""
    subprocess.Popen([str(launch.pythonw()), str(launch.ROOT / "launch.py"), command, *names], cwd=launch.ROOT, creationflags=launch.DETACHED)


def _dispose(root: QtWidgets.QApplication) -> None:
    """Delete every window and the application on the Qt thread, including binding-owned deletions."""
    for window in root.topLevelWidgets():
        window.hide()
        window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    icon.cache_clear()
    shiboken6.delete(root)


def run() -> None:
    """Blocks until the desktop quits."""
    screen.use_physical_pixels()  # before any window exists
    lock = system.create_lock(LOCK_NAME)
    if lock is None:
        return
    try:
        inbox = Inbox.open(components.DESKTOP.window)
        voice = Voice.open(settings_from(os.environ, components.endpoint("gateway")), inbox.window.handle, inbox.report, log)
        root = application()
        root.setStyleSheet(tooltip_style(tokens(scheme())))
        app = DesktopApp.compose(root, voice, inbox)
        QtCore.QTimer.singleShot(0, app.start)
        try:
            try:
                root.exec()
            finally:
                try:
                    app.close_bar()
                finally:
                    _dispose(root)
        finally:
            voice.close(log)
    finally:
        system.release_lock(lock)
