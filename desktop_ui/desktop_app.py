"""The desktop: Workspace's bar, canvas views, tray, key map and window placement.

It runs without the assistant and the assistant without it. The keyboard sends
it the requests it owns (app keys, window keys, the inbox, the switcher) and its
indicator, key and chord messages, to its own hidden window; tools the assistant
owns go there as `contracts.desktop_link` commands over the link. What the
assistant publishes (its session, work, canvas, voice and recording) arrives
the same way and is shown here.
"""

import contextlib
import os
import queue
import subprocess
import threading
import traceback
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final, assert_never

import components
import diagnostics
import launch
import usage
from cell import Cell
from config import APPS
from contracts.desktop_link import (
    Record,
    UseTool,
    WireError,
    from_assistant,
)
from desktop_ui import desktop_controls
from desktop_ui.assistant_port import UNAVAILABLE, AssistantPort, LinkedAssistant
from desktop_ui.desktop_control import (
    AssistantSaid,
    Beep,
    Chord,
    Connection,
    Controlled,
    DesktopState,
    Effect,
    Event,
    Flash,
    Fold,
    Indicate,
    Indicated,
    Launch,
    LayoutReported,
    LayoutShown,
    Log,
    MenuChosen,
    MenuRequested,
    Navigate,
    OpenInbox,
    OpenLogs,
    OpenUsage,
    OverlayEnabled,
    OverlayToggled,
    PressedKeys,
    Problem,
    Quit,
    RecordUse,
    RestoreTray,
    Send,
    ShowCanvas,
    ShowKeymap,
    ShowMenu,
    ShowOverlay,
    ShowViews,
    SpecLoaded,
    SwitchWindows,
    ToggleLayout,
    ToggleTaskbar,
    TrayNotify,
    TrayShow,
    transition,
    tray_state,
)
from desktop_ui.navigation import Source, SwitcherPick
from desktop_ui.overlay import OverlayState, load_enabled, save_enabled
from desktop_ui.qt_runtime import prepare
from desktop_ui.report import write_report
from desktop_ui.tray import Tray
from desktop_ui.ui import Ui, Views
from desktop_ui.ui_spec import SpecError
from link.client import Client, Status
from protocol import (
    WM_CHORD,
    WM_INDICATOR,
    WM_KEY_STATE,
    WM_LAYOUT_STATE,
    WM_QUERY_LAYOUT_STATE,
    WM_REQUEST,
    WM_WINDOWS_KEY_TAP,
    Tool,
)
from usage import DIRECTORY
from winapi import screen, shell, system, windows
from winapi.shapes import Rect

prepare()

LOCK_NAME: Final = "Local\\workspace-desktop"
LOG: Final = DIRECTORY / "desktop.log"
WM_TRAY: Final = system.WM_APP + 20
WM_SHOW_MENU: Final = 0x8056
WM_EVENTS: Final = system.WM_APP + 22
"""Any thread -> Qt thread: events are waiting in the inbox."""


def log(text: str) -> None:
    diagnostics.append(LOG, text)


def indicator_area() -> Rect:
    """Where the layer indicator goes: the bottom of the main monitor."""
    monitors = screen.monitors()
    return next((m.work for m in monitors if m.primary), monitors[0].work)


@dataclass(frozen=True, slots=True)
class Offline:
    """The assistant when the desktop runs outside the keeper: never reachable."""

    def send(self, command: object) -> bool:
        return False


def window_event(message: int, wparam: int, lparam: int) -> Event | None:
    """What a message to the control window reports."""
    if message == shell.TASKBAR_CREATED:
        return RestoreTray()
    if message == WM_SHOW_MENU or (message == WM_TRAY and lparam in (system.WM_LBUTTONUP, system.WM_RBUTTONUP)):
        return MenuRequested()
    if message in (WM_KEY_STATE, WM_REQUEST, desktop_controls.WM_TOOL_CHOSEN):
        return Controlled(desktop_controls.control_event(desktop_controls.WindowInput(message, wparam, lparam), APPS))
    if message == WM_INDICATOR:
        return Indicated(wparam)
    if message == WM_LAYOUT_STATE:
        return LayoutReported(wparam)
    if message == WM_CHORD:
        return Chord(held=bool(wparam))
    if message == WM_WINDOWS_KEY_TAP:
        return ToggleTaskbar()
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


def received(inbox: Inbox, frame: bytes) -> None:
    """Link thread: the assistant's message, for the Qt thread."""
    try:
        message = from_assistant(frame)
    except WireError as error:
        log(f"Refused a frame from the assistant: {error}")
        return
    inbox.report(AssistantSaid(message))


@dataclass(frozen=True, slots=True)
class DesktopApp:
    """The desktop's views and tray, and the Qt-thread fold of their events into effects."""

    inbox: Inbox
    ui: Ui
    assistant: AssistantPort
    tray: Tray
    state: Cell[DesktopState]

    @classmethod
    def compose(cls, ui: Ui, assistant: AssistantPort, inbox: Inbox) -> DesktopApp:
        state = Cell(DesktopState(overlay=OverlayState(enabled=load_enabled())))
        app = cls(inbox, ui, assistant, Tray.add(inbox.window.handle, WM_TRAY), state)
        ui.desktop_overlay(enabled=state.get().overlay.enabled)
        inbox.connect(app.handle)
        return app

    def start(self) -> None:
        """Qt thread: the bar and the canvas's controller, then the layout's state, then readiness."""
        report, state = self.inbox.report, self.state
        self.ui.desktop(
            record=lambda action: report(Send(Record(action))),
            stop=lambda: report(Send(UseTool(Tool.STOP))),
            overlay=lambda: report(OverlayToggled()),
            menu=lambda: report(MenuRequested()),
            audio_level=lambda: state.get().level,
            tool=lambda tool: report(Controlled(desktop_controls.ChosenTool(tool))),
        )
        self.ui.work_window().prepare()
        if (layout := windows.find(components.LAYOUT.window.title)) is not None:
            system.post_message(layout, WM_QUERY_LAYOUT_STATE, 0, 0)
        self.perform(TrayShow(tray_state(state.get().shown)))

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
            case Fold(event):
                yield event
            case Send(command):
                if not self.assistant.send(command):
                    yield Problem(UNAVAILABLE)
            case RestoreTray() | TrayNotify() | TrayShow() | Log() | Beep():
                self._tray(effect)
            case ShowViews() | Navigate() | OpenInbox() | SwitchWindows() | Chord() | ToggleTaskbar() | ShowKeymap() | ShowCanvas():
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

    def _views(self, effect: ShowViews | Navigate | OpenInbox | SwitchWindows | Chord | ToggleTaskbar | ShowKeymap | ShowCanvas) -> None:
        match effect:
            case ShowViews(message):
                self.ui.show(message)
            case Navigate(order):
                self.ui.navigate(order)
            case OpenInbox():
                self.ui.open_inbox()
            case SwitchWindows():
                self._switch_windows()
            case Chord(held):
                self.ui.desktop_chord(held=held)
            case ToggleTaskbar():
                self.ui.toggle_taskbar()
            case ShowKeymap():
                self.ui.show_keymap()
            case ShowCanvas():
                self.ui.show_canvas()
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
        self.ui.close_windows()
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


def run(*, window: components.Window = components.DESKTOP.window, lock_name: str = LOCK_NAME, views: Views | None = None) -> None:
    """Blocks until the desktop quits; a test names its own `window`, `lock_name` and `views`."""
    screen.use_physical_pixels()  # before any window exists
    lock = system.create_lock(lock_name)
    if lock is None:
        return
    try:
        published = components.endpoint("assistant")
        inbox = Inbox.open(window)

        def status(change: Status) -> None:
            inbox.report(Connection(change))

        client = Client(published, lambda frame: received(inbox, frame), status) if published is not None else None
        port: AssistantPort = LinkedAssistant(client) if client is not None else Offline()
        ui = Ui.start(port, views=views, on_problem=lambda message: inbox.report(Problem(message)))
        app = DesktopApp.compose(ui, port, inbox)
        ui.post(lambda _: app.start())
        if client is not None:
            client.start()
        try:
            ui.run()
        finally:
            if client is not None:
                client.close()
    finally:
        system.release_lock(lock)
