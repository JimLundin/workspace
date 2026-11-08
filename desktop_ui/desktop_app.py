"""The desktop: Workspace's bar, tray, key map, window placement, dictation and meetings.

The keyboard sends every request and its indicator, key, chord and layout
messages to the desktop's hidden control window. Dictation and meetings
(`desktop_ui.voice`) are called here on the Qt thread; what their workers
report arrives as events in the same inbox and is shown here.
"""

import contextlib
import os
import queue
import subprocess
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final, assert_never

import components
import diagnostics
import launch
import usage
from assistant.llm import settings_from
from cell import Cell
from config import APPS
from desktop_ui import desktop_controls
from desktop_ui.desktop_control import (
    Beep,
    Chord,
    Controlled,
    DesktopState,
    Effect,
    Event,
    ExpireCapture,
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
    OpenUsage,
    OverlayEnabled,
    OverlayToggled,
    PressedKeys,
    Problem,
    Quit,
    Record,
    RecordUse,
    RestoreTray,
    ShowActivity,
    ShowIdle,
    ShowKeymap,
    ShowMenu,
    ShowOverlay,
    ShowVoice,
    SpecLoaded,
    SwitchWindows,
    ToggleLayout,
    ToggleMeeting,
    ToggleTaskbar,
    TrayNotify,
    TrayShow,
    UseLayout,
    VoiceShown,
    transition,
)
from desktop_ui.navigation import Source, SwitcherPick
from desktop_ui.overlay import OverlayState, load_enabled, save_enabled
from desktop_ui.qt_runtime import prepare
from desktop_ui.report import write_report
from desktop_ui.tray import Tray
from desktop_ui.ui import Ui
from desktop_ui.ui_spec import SpecError
from desktop_ui.voice import Voice
from protocol import (
    WM_CHORD,
    WM_INDICATOR,
    WM_KEY_STATE,
    WM_LAYOUT_STATE,
    WM_QUERY_LAYOUT_STATE,
    WM_REQUEST,
    WM_WINDOWS_KEY_TAP,
)
from usage import DIRECTORY
from winapi import screen, shell, system, windows
from winapi.shapes import Rect

prepare()

LOCK_NAME: Final = "Local\\workspace-desktop"
LOG: Final = DIRECTORY / "desktop.log"
WM_TRAY: Final = system.WM_APP + 20
WM_EVENTS: Final = system.WM_APP + 22
"""Any thread -> Qt thread: events are waiting in the inbox."""
CAPTURE_TIMER_MS: Final = 1000
"""How often the control window checks a voice capture against its time limit."""


def log(text: str) -> None:
    diagnostics.append(LOG, text)


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
        return Controlled(desktop_controls.control_event(desktop_controls.WindowInput(message, wparam, lparam), APPS))
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
class DesktopApp:
    """The desktop's views, tray, dictation and meetings, and the Qt-thread fold of their events into effects."""

    inbox: Inbox
    ui: Ui
    voice: Voice
    tray: Tray
    state: Cell[DesktopState]

    @classmethod
    def compose(cls, ui: Ui, voice: Voice, inbox: Inbox) -> DesktopApp:
        state = Cell(DesktopState(overlay=OverlayState(enabled=load_enabled())))
        app = cls(inbox, ui, voice, Tray.add(inbox.window.handle, WM_TRAY), state)
        ui.desktop_overlay(enabled=state.get().overlay.enabled)
        inbox.connect(app.handle)
        return app

    def start(self) -> None:
        """Qt thread: the bar, the capture timer and the workers, then the layout's state, then readiness."""
        report = self.inbox.report
        self.ui.desktop(
            record=lambda action: report(Record(action)),
            overlay=lambda: report(OverlayToggled()),
            menu=lambda: report(MenuRequested()),
            audio_level=self.voice.level,
            tool=lambda tool: report(Controlled(desktop_controls.ChosenTool(tool))),
        )
        system.set_window_timer(self.inbox.window.handle, CAPTURE_TIMER_MS)
        self.voice.start()
        if (layout := windows.find(components.LAYOUT.window.title)) is not None:
            system.post_message(layout, WM_QUERY_LAYOUT_STATE, 0, 0)
        self.handle(ShowIdle())

    # ---- the fold ----------------------------------------------------------------------

    def handle(self, event: Event) -> None:
        """Qt thread: fold `event`, perform its effects in order, and fold what they report."""
        state, effects = transition(self.state.get(), event)
        self.state.set(state)
        for effect in effects:
            for reported in self.perform(effect):
                self.handle(reported)

    def perform(self, effect: Effect) -> Iterator[Event]:
        """Carry out `effect`; what it reports back (a menu choice, a refusal) is folded next."""
        match effect:
            case ShowVoice() | ShowIdle() | HandleKey() | UseLayout() | ExpireCapture() | Record() | ToggleMeeting():
                yield from self._voice(effect)
            case RestoreTray() | TrayNotify() | TrayShow() | Log() | Beep():
                self._tray(effect)
            case ShowActivity() | Navigate() | SwitchWindows() | Chord() | ToggleTaskbar() | ShowKeymap():
                self._views(effect)
            case ShowOverlay() | OverlayEnabled() | Flash() | LayoutShown() | PressedKeys() | Indicate() | ToggleLayout():
                yield from self._keys(effect)
            case ShowMenu():
                yield from self._menu(effect)
            case RecordUse() | Launch() | OpenUsage() | OpenLogs():
                self._launch(effect)
            case Quit():
                self.quit()
            case _:
                assert_never(effect)

    def _voice(self, effect: ShowVoice | ShowIdle | HandleKey | UseLayout | ExpireCapture | Record | ToggleMeeting) -> Iterator[Event]:
        voice = self.voice
        try:
            match effect:
                case ShowVoice(shown):
                    yield VoiceShown(voice.shown(shown))
                case ShowIdle():
                    yield VoiceShown(voice.idle())
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
            yield Problem(str(error))

    def _tray(self, effect: RestoreTray | TrayNotify | TrayShow | Log | Beep) -> None:
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
            case _:
                assert_never(effect)

    def _views(self, effect: ShowActivity | Navigate | SwitchWindows | Chord | ToggleTaskbar | ShowKeymap) -> None:
        match effect:
            case ShowActivity(change):
                self.ui.show_activity(change)
            case Navigate(order):
                self.ui.navigate(order)
            case SwitchWindows():
                self._switch_windows()
            case Chord(held):
                self.ui.desktop_chord(held=held)
            case ToggleTaskbar():
                self.ui.toggle_taskbar()
            case ShowKeymap():
                self.ui.show_keymap()
            case _:
                assert_never(effect)

    def _keys(self, effect: ShowOverlay | OverlayEnabled | Flash | LayoutShown | PressedKeys | Indicate | ToggleLayout) -> Iterator[Event]:
        match effect:
            case ShowOverlay(overlay):
                self.ui.show_keyboard_overlay(overlay.layer, overlay.title, indicator_area(), visible=overlay.visible, pressed=overlay.pressed)
            case OverlayEnabled(enabled):
                self.ui.desktop_overlay(enabled=enabled)
                try:
                    save_enabled(enabled=enabled)
                except OSError:
                    yield Problem("The overlay changed, but its setting couldn't be saved.")
            case Flash(text):
                self.ui.flash(text, indicator_area())
            case LayoutShown(enabled):
                self.ui.desktop_layout(enabled=enabled)
            case PressedKeys(pressed, reset):
                self.ui.show_pressed_keys(pressed, reset=reset)
            case Indicate(text):
                self.ui.indicate(text, indicator_area())
            case ToggleLayout():
                if not desktop_controls.toggle_layout(Native()):
                    yield Problem("Couldn't reach the layout. Try Start layout or Restart layout.")
            case _:
                assert_never(effect)

    def _launch(self, effect: RecordUse | Launch | OpenUsage | OpenLogs) -> None:
        match effect:
            case RecordUse(feature):
                with contextlib.suppress(OSError):
                    usage.record("desktop", feature, {})
            case Launch(command, names):
                launched(command, *names)
            case OpenUsage():
                os.startfile(write_report())
            case OpenLogs():
                DIRECTORY.mkdir(parents=True, exist_ok=True)
                os.startfile(DIRECTORY)
            case _:
                assert_never(effect)

    def _menu(self, effect: ShowMenu) -> Iterator[Event]:
        spec = effect.spec
        try:
            spec = desktop_controls.tray()
            yield SpecLoaded(spec)
        except SpecError as error:
            yield Problem(f"The tray menu kept its last good spec: {error}")
        shown = spec if spec is not None else desktop_controls.tray(reload=False)
        yield MenuChosen(shell.show_menu(self.inbox.window.handle, desktop_controls.menu_items(effect.state, shown)))

    def _switch_windows(self) -> None:
        ui = self.ui

        def focus(handle: int) -> None:
            ui.navigate(SwitcherPick(handle, Source.KEY))

        def collect() -> None:
            own = os.getpid()
            ui.switch_windows(tuple(w for w in windows.windows() if windows.process_id(w.handle) != own), focus)

        threading.Thread(target=collect, name="window list", daemon=True).start()

    def quit(self) -> None:
        """Close the views and the tray."""
        try:
            self.ui.close_desktop()
        except OSError as error:
            log(str(error))
        self.tray.remove()
        self.inbox.window.destroy()
        self.ui.close()


@dataclass(frozen=True, slots=True)
class Native:
    """The layout's window, for toggling it from the tray."""

    def find_window(self, title: str) -> int | None:
        return windows.find(title)

    # Match HWND, message and both payload fields of the native wire contract.
    def post(self, handle: int, message: int, wparam: int, lparam: int) -> bool:
        return system.post_message(handle, message, wparam, lparam)


def launched(command: str, *names: str) -> None:
    """Run the launcher on its own, so it outlives this program when it restarts or stops the desktop."""
    subprocess.Popen([str(launch.pythonw()), str(launch.ROOT / "launch.py"), command, *names], cwd=launch.ROOT, creationflags=launch.DETACHED)


def run() -> None:
    """Blocks until the desktop quits."""
    screen.use_physical_pixels()  # before any window exists
    lock = system.create_lock(LOCK_NAME)
    if lock is None:
        return
    try:
        inbox = Inbox.open(components.DESKTOP.window)
        voice = Voice.open(settings_from(os.environ, components.endpoint("gateway")), inbox.window.handle, inbox.report, log)
        ui = Ui.start(lambda message: inbox.report(Problem(message)))
        app = DesktopApp.compose(ui, voice, inbox)
        ui.post(lambda _: app.start())
        try:
            ui.run()
        finally:
            voice.close(log)
    finally:
        system.release_lock(lock)
