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
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass, replace
from typing import Final, assert_never

import components
import launch
import usage
from config import APPS
from contracts.desktop_link import (
    MicLevel,
    Notify,
    Record,
    RecordingChanged,
    SessionChanged,
    ToDesktop,
    UseTool,
    VoiceChanged,
    WireError,
    from_assistant,
)
from contracts.recording_state import RecordingAction
from contracts.status import State
from desktop_ui import desktop_controls
from desktop_ui.assistant_port import UNAVAILABLE, AssistantPort, LinkedAssistant
from desktop_ui.keymap import indicator_text
from desktop_ui.navigation import AppKey, Order, Source, SwitcherPick, keyed
from desktop_ui.overlay import OverlayState, load_enabled, save_enabled
from desktop_ui.qt_runtime import prepare
from desktop_ui.report import write_report
from desktop_ui.tray import Tray
from desktop_ui.ui import Ui, Views
from desktop_ui.ui_spec import SpecError
from link.client import Client, Status
from miryoku.layout import Layer
from protocol import (
    WM_CHORD,
    WM_INDICATOR,
    WM_KEY_STATE,
    WM_LAYOUT_STATE,
    WM_QUERY_LAYOUT_STATE,
    WM_REQUEST,
    WM_WINDOWS_KEY_TAP,
    App,
    LayoutState,
    Request,
    Side,
    Tool,
    decode_indicator,
    owner,
)
from usage import DIRECTORY
from winapi import screen, shell, system, windows
from winapi.shapes import Rect

prepare()

LOCK_NAME: Final = "Local\\workspace-desktop"
LOG: Final = DIRECTORY / "desktop.log"
WM_TRAY: Final = system.WM_APP + 20
WM_SHOW_MENU: Final = 0x8056


def log(text: str) -> None:
    """The desktop's own log: problems and crashes (there's no console under pythonw)."""
    with contextlib.suppress(OSError):
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as file:
            file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


def indicator_area() -> Rect:
    """Where the layer indicator goes: the bottom of the main monitor."""
    monitors = screen.monitors()
    return next((m.work for m in monitors if m.primary), monitors[0].work)


@dataclass(frozen=True, slots=True)
class Offline:
    """The assistant when the desktop runs outside the keeper: never reachable."""

    def send(self, command: object) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class Shown:
    """What the assistant last published that the tray and its menu read."""

    state: State = State.LAYOUT_OFF
    capturing: bool = False
    agent_running: bool = False
    connected: bool = False


class DesktopApp:
    __slots__ = ("assistant", "layout", "level", "overlay", "shown", "tray", "tray_spec", "ui", "window")

    def __init__(self, ui: Ui, assistant: AssistantPort, *, window: components.Window = components.DESKTOP.window) -> None:
        self.ui, self.assistant = ui, assistant
        self.window = shell.AppWindow.create(window.title, self.on_message, class_name=window.window_class)
        self.tray = Tray.add(self.window.handle, WM_TRAY)
        self.tray_spec: desktop_controls.TraySpec = desktop_controls.tray(reload=False)
        self.overlay = OverlayState(enabled=load_enabled())
        self.layout: LayoutState | None = None
        self.shown = Shown()
        self.level: float | None = None
        """The microphone's latest level from the assistant, for the bar's trace."""
        self.ui.desktop_overlay(enabled=self.overlay.enabled)

    def start(self) -> None:
        """Qt thread: the bar and the canvas's controller, then the layout's state, then readiness."""
        self.ui.desktop(
            record=self.record,
            stop=lambda: self.use(Tool.STOP),
            overlay=self.toggle_overlay,
            menu=self.request_menu,
            audio_level=lambda: self.level,
            tool=self.choose_tool,
        )
        self.ui.work_window().prepare()
        if (layout := windows.find(components.LAYOUT.window.title)) is not None:
            system.post_message(layout, WM_QUERY_LAYOUT_STATE, 0, 0)
        self.show_tray()
        components.ready()

    # ---- the assistant -----------------------------------------------------------------

    def received(self, frame: bytes) -> None:
        """Link thread: the assistant's message, shown on the Qt thread."""
        try:
            message = from_assistant(frame)
        except WireError as error:
            log(f"Refused a frame from the assistant: {error}")
            return
        self.ui.post(lambda _: self.show(message))

    def status(self, status: Status) -> None:
        """Link thread: the assistant came or went."""
        self.ui.post(lambda _: self.connection(status))

    def connection(self, status: Status) -> None:
        match status:
            case Status.CONNECTED:
                self.shown = replace(self.shown, connected=True)
            case Status.DISCONNECTED:
                self.shown = replace(self.shown, connected=False, agent_running=False)
                self.level = None
            case _:
                assert_never(status)
        self.show_tray()

    def show(self, message: ToDesktop) -> None:
        """Qt thread: what the tray reads, then the views."""
        match message:
            case SessionChanged(session=session):
                self.shown = replace(self.shown, agent_running=session.busy)
            case VoiceChanged(state=state):
                self.shown = replace(self.shown, state=state)
            case RecordingChanged(recording=recording):
                self.shown = replace(self.shown, capturing=recording.capturing)
            case MicLevel(level=level):
                self.level = level
            case Notify(title=title, text=text, warning=warning):
                if warning:
                    system.beep(system.MB_ICONEXCLAMATION)
                self.tray.notify(title, text, warning=warning)
            case _:
                pass
        self.ui.show(message)
        self.show_tray()

    def use(self, tool: Tool) -> None:
        """A tool the assistant owns, chosen here; while it's down, say so."""
        if not self.assistant.send(UseTool(tool)):
            self.problem(UNAVAILABLE)

    def record(self, action: RecordingAction) -> None:
        if not self.assistant.send(Record(action)):
            self.problem(UNAVAILABLE)

    def problem(self, message: str) -> None:
        log(message)
        system.beep(system.MB_ICONEXCLAMATION)
        self.tray.notify("Workspace", message, warning=True)

    def show_tray(self) -> None:
        shown = self.shown
        self.tray.show(State.RECORDING if shown.capturing else shown.state if shown.connected else State.LAYOUT_OFF)

    # ---- the keyboard ------------------------------------------------------------------

    def handle(self, request: Request) -> None:
        """A request the desktop owns: an app key, a window key, the inbox or the switcher."""
        match request:
            case App():
                self.used(f"app:{request.name}", AppKey(request, Source.KEY))
            case Tool.OPEN_INBOX:
                self.ui.open_inbox()
            case Tool.WINDOW_SWITCHER:
                self.switch_windows()
            case Tool():
                self.used(request.name.lower(), keyed(request))
            case _:
                assert_never(request)

    def used(self, feature: str, order: Order | None) -> None:
        if order is not None:
            self.ui.navigate(order)
        with contextlib.suppress(OSError):
            usage.record("desktop", feature, {})

    def choose_tool(self, tool: Tool) -> None:
        """Marshal menu choices from the bar to this window's thread."""
        system.post_message(self.window.handle, desktop_controls.WM_TOOL_CHOSEN, tool.value, 0)

    def switch_windows(self) -> None:
        def focus(handle: int) -> None:
            self.ui.navigate(SwitcherPick(handle, Source.KEY))

        def collect() -> None:
            own = os.getpid()
            self.ui.switch_windows(tuple(w for w in windows.windows() if windows.process_id(w.handle) != own), focus)

        threading.Thread(target=collect, name="window list", daemon=True).start()

    def show_overlay(self, work: Rect) -> None:
        self.ui.show_keyboard_overlay(self.overlay.layer, self.overlay.title, work, visible=self.overlay.visible, pressed=self.overlay.pressed)

    def display_overlay(self, change: desktop_controls.OverlayChange) -> None:
        self.overlay = replace(self.overlay, enabled=change.enabled)
        self.show_overlay(indicator_area())
        self.ui.desktop_overlay(enabled=change.enabled)

    def persist_overlay(self, change: desktop_controls.OverlayChange) -> None:
        save_enabled(enabled=change.enabled)

    def toggle_overlay(self) -> None:
        change = desktop_controls.OverlayChange(enabled=not self.overlay.enabled)
        if (problem := desktop_controls.change_overlay(change, self)) is not None:
            self.problem(problem)

    def layout_changed(self, value: int) -> None:
        with contextlib.suppress(ValueError):
            self.layout = LayoutState(value)
        on = self.layout is LayoutState.ON
        work = indicator_area()
        if self.layout is not LayoutState.QUIT:
            self.ui.flash("Layout on" if on else "Layout off", work)
        self.ui.desktop_layout(enabled=on)
        self.overlay = self.overlay.set_layout(on=on)
        self.ui.show_pressed_keys(self.overlay.pressed, reset=True)
        self.show_overlay(work)

    def on_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> int | None:
        try:
            if message == shell.TASKBAR_CREATED:
                self.tray.restore()
                return 0
            if message == WM_SHOW_MENU or (message == WM_TRAY and lparam in (system.WM_LBUTTONUP, system.WM_RBUTTONUP)):
                self.menu()
                return 0
            if message in (WM_KEY_STATE, WM_REQUEST, desktop_controls.WM_TOOL_CHOSEN):
                self.control(desktop_controls.control_event(desktop_controls.WindowInput(message, wparam, lparam), APPS))
                return 0
            if message == WM_INDICATOR:
                index, locked, caps_word = decode_indicator(wparam)
                layer = next((layer for layer in Layer if layer.value == index), None)
                work = indicator_area()
                self.ui.indicate(indicator_text(layer, locked=locked, caps_word=caps_word), work)
                self.overlay = self.overlay.indicate(layer, locked=locked, caps_word=caps_word)
                self.show_overlay(work)
                return 0
            if message == WM_LAYOUT_STATE:
                self.layout_changed(wparam)
                return 0
            if message == WM_CHORD:
                self.ui.desktop_chord(held=bool(wparam))
                return 0
            if message == WM_WINDOWS_KEY_TAP:
                self.ui.toggle_taskbar()
                return 0
            if message == system.WM_CLOSE:  # the keeper asks, or Quit Workspace
                self.quit()
                return 0
        except Exception:
            log(traceback.format_exc())
        return None

    def control(self, action: desktop_controls.ControlAction | None) -> None:
        match action:
            case desktop_controls.PhysicalKey(scancode=scancode, down=down):
                self.overlay = self.overlay.key(scancode, down=down)
                self.ui.show_pressed_keys(self.overlay.pressed, reset=action.reset)
            case desktop_controls.FeatureRequest(request=request, down=down):
                if down and owner(request) is Side.DESKTOP:
                    self.handle(request)
            case desktop_controls.ChosenTool(tool=tool):
                match owner(tool):
                    case Side.DESKTOP:
                        self.handle(tool)
                    case Side.ASSISTANT:
                        self.use(tool)
                    case _:
                        assert_never(owner(tool))
            case None:
                pass
            case _:
                assert_never(action)

    # ---- the tray menu -----------------------------------------------------------------

    def request_menu(self) -> None:
        system.post_message(self.window.handle, WM_SHOW_MENU, 0, 0)

    def menu(self) -> None:
        state = desktop_controls.MenuState(
            layout=self.layout, overlay_enabled=self.overlay.enabled, agent_running=self.shown.agent_running, capturing=self.shown.capturing
        )
        try:
            self.tray_spec = desktop_controls.tray()
        except SpecError as error:
            self.problem(f"The tray menu kept its last good spec: {error}")
        match shell.show_menu(self.window.handle, desktop_controls.menu_items(state, self.tray_spec)):
            case desktop_controls.Menu.TOGGLE_LAYOUT.value:
                if not desktop_controls.toggle_layout(Native()):
                    self.problem("Couldn't reach the layout. Try Start layout or Restart layout.")
            case desktop_controls.Menu.RESTART_LAYOUT.value:
                launched("restart", "layout")
            case desktop_controls.Menu.RESTART_ASSISTANT.value:
                launched("restart", "assistant")
            case desktop_controls.Menu.RESTART_DESKTOP.value:
                # The launcher closes this program and starts it again; the assistant keeps working meanwhile.
                launched("restart", "desktop")
            case desktop_controls.Menu.OVERLAY.value:
                self.toggle_overlay()
            case desktop_controls.Menu.KEYMAP.value:
                self.ui.show_keymap()
            case desktop_controls.Menu.AGENT.value:
                self.use(Tool.AGENT_TYPED)
            case desktop_controls.Menu.WORK.value:
                self.ui.show_canvas()
            case desktop_controls.Menu.TASKBAR.value:
                self.ui.toggle_taskbar()
            case desktop_controls.Menu.STOP_AGENT.value:
                self.use(Tool.STOP)
            case desktop_controls.Menu.MEETING.value:
                self.use(Tool.MEETING_TOGGLE)
            case desktop_controls.Menu.TRANSCRIPTS.value:
                self.record("folder")
            case desktop_controls.Menu.USAGE.value:
                os.startfile(write_report())
            case desktop_controls.Menu.LOGS.value:
                DIRECTORY.mkdir(parents=True, exist_ok=True)
                os.startfile(DIRECTORY)
            case desktop_controls.Menu.QUIT.value:
                # The launcher asks every program to quit, this one last.
                launched("stop")
            case _:
                pass

    def quit(self) -> None:
        """Close the views and the tray."""
        try:
            self.ui.close_desktop()
        except OSError as error:
            log(str(error))
        self.ui.close_windows()
        self.tray.remove()
        self.window.destroy()
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
        app: DesktopApp | None = None

        def received(frame: bytes) -> None:
            if app is not None:
                app.received(frame)

        def status(change: Status) -> None:
            if app is not None:
                app.status(change)

        client = Client(published, received, status) if published is not None else None
        port: AssistantPort = LinkedAssistant(client) if client is not None else Offline()
        ui = Ui(port, views=views, on_problem=lambda message: app.problem(message) if app is not None else log(message))
        app = DesktopApp(ui, port, window=window)
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
