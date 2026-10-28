"""Native shell behavior with isolated views and controlled Windows boundaries."""

import ctypes
import sys
import threading
import time
import unittest
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows desktop shell")

lazy from PySide6 import QtCore, QtGui, QtWidgets
lazy from PySide6.QtTest import QTest

from assistant.ambient import Battery, Speakers, SystemStatus, Weather, Wifi
from assistant.bar_surface import painter_path
from assistant.desktop_bar import BarActions, BarObservations, DesktopBar
from assistant.icons import State
from assistant.qt_runtime import prepare
from assistant.qt_ui import application
from assistant.recording_state import RecordingState
from assistant.shell_controls import TaskbarControl, WindowsKeyDispatch, WindowsKeyEffects
from protocol import LAYOUT_MAGIC, Tool
from winapi import inputs, keyboard_language, system
lazy from assistant.notifications import Tone
lazy from assistant.qt_ui import EventLoop
lazy from assistant.window_switcher import WindowSwitcher
lazy from winapi import appearance
lazy from winapi.shapes import Window

prepare()


def test_floating_bar_shows_only_active_controls_and_retracts(tmp_path: Path) -> None:
    app = application()
    invoked: list[str] = []
    actions = BarActions(lambda: invoked.append("agent"), lambda: invoked.append("work"), lambda: invoked.append("agent-stop"),
                         invoked.append, lambda: invoked.append("keyboard"), lambda: None, lambda: invoked.append("menu"), invoked.append,
                         inbox=lambda: invoked.append("inbox"))
    bar = DesktopBar(actions, native_shell=False)
    try:
        width = bar.window.width()
        assert bar.status.text() == bar.ambient.text and bar.stop.isHidden()
        assert not bar.capture.presented and not bar.keycaps.presented
        assert len([button for button in bar.window.findChildren(QtWidgets.QToolButton) if not button.isHidden()]) == 1
        bar.state(State.AGENT)
        assert not bar.stop.isHidden() and bar.stop.geometry().right() < bar.window.width()
        bar.stop.click()
        bar.recording_changed(RecordingState(phase="recording", seconds=125))
        bar.state(State.LISTENING)
        assert not bar.status.text() and "Listening" in bar.status.accessibleName() and bar.record.text() == "02:05"
        assert not bar.record_stop.isHidden() and not bar.stop.isHidden()
        bar.record_stop.click()
        bar.layout(False)
        assert bar.keyboard.text() == "Colemak"
        bar.keyboard.click()
        assert invoked == ["agent-stop", "stop", "keyboard"]
        bar.recording_changed(RecordingState(phase="saved"))
        bar.layout(True)
        bar.state(State.READY)
        assert bar.window.width() == width
        assert bar.view is not None and bar.view.capture is None and bar.view.keyboard is None
        bar.open_menu()
        assert [action.text() for action in bar.menu.actions() if not action.isSeparator()] == [
            "Your work feed", "Work and meetings", "Record a meeting", "Keyboard map", "Keyboard overlay",
            "Windows taskbar", "Switch windows · Apps + Esc", "Copy latest transcript",
            "Windows notification settings",
            "Window tiling", "All Workspace controls…",
        ]
        bar.menu.close()
        bar.window.grab().save(str(tmp_path / "floating-bar.png"))
    finally:
        bar.close()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        app.processEvents()


def test_toolbar_groups_keep_their_actions_and_dividers_between_functions() -> None:
    # Defects: readouts/padding open unrelated controls, a divider splits a
    # function from its Stop, or one group's button calls another function.
    app = application()
    invoked: list[str] = []
    actions = BarActions(lambda: invoked.append('agent'), lambda: invoked.append('meeting'), lambda: invoked.append('stop'),
                         lambda action: invoked.append('record-' + action), lambda: invoked.append('keyboard'),
                         lambda: None, lambda: invoked.append('controls'), lambda _: None, inbox=lambda: invoked.append('inbox'))
    bar = DesktopBar(actions, native_shell=False)
    try:
        assert bar.status.focusPolicy() is QtCore.Qt.FocusPolicy.NoFocus
        assert bar.status.cursor().shape() is QtCore.Qt.CursorShape.ArrowCursor
        QTest.mouseClick(bar.status, QtCore.Qt.MouseButton.LeftButton)
        QTest.mouseClick(bar.window, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(1, 1))
        assert not bar.menu.isVisible() and not invoked
        bar.menu_button.click()
        assert bar.menu.isVisible()
        bar.menu.close()
        assert not bar.controls_divider.isHidden() and bar.inbox_divider.isHidden()
        bar.state(State.AGENT)
        bar.inbox_changed(1)
        assert not bar.inbox_divider.isHidden()
        row = bar.window.row
        assert row.indexOf(bar.menu_button) < row.indexOf(bar.controls_divider) < row.indexOf(bar.status)
        assert row.indexOf(bar.status) + 1 == row.indexOf(bar.stop)
        assert row.indexOf(bar.stop) < row.indexOf(bar.inbox_divider) < row.indexOf(bar.inbox)
        bar.stop.click()
        bar.inbox.click()
        bar.recording_changed(RecordingState(phase='recording'))
        bar.record.click()
        bar.record_stop.click()
        # Defect: the shared control reserves caption space for an empty label.
        for button in (bar.menu_button, bar.stop, bar.record_stop):
            assert button.width() == button.height() == 24
            assert button.toolButtonStyle() is QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        for button in (bar.inbox, bar.record):
            assert button.toolButtonStyle() is QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + button.iconSize().width()
        bar.layer('NAV')
        bar.keyboard.click()
        assert invoked == ['stop', 'inbox', 'meeting', 'record-stop', 'keyboard']
        bar.inbox_changed(0)
        assert bar.inbox_divider.isHidden() and bar.inbox.isHidden()
        assert bar.inbox.sizeHint().width() == 24
        assert bar.inbox.toolButtonStyle() is QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
    finally:
        bar.close()
        app.processEvents()


class TaskbarDesktop:
    """Own the fixture Explorer visibility catalog, including simulated restarts."""

    def __init__(self) -> None:
        self.shown = {101: True}

    def taskbars(self) -> tuple[int, ...]:
        return tuple(self.shown)

    def visible(self, hwnd: int) -> bool:
        return self.shown[hwnd]

    def taskbar_visible(self, hwnd: int, *, show: bool) -> None:
        self.shown[hwnd] = show


class RecoveryGuard:
    """Own the fixture recovery process's readiness and exit observation."""

    def __init__(self, *, ready: bool = True) -> None:
        self.handshake = ready
        self.code: int | None = None
        self.closed = False

    def ready(self) -> bool:
        return self.handshake

    def poll(self) -> int | None:
        return self.code

    def close(self) -> None:
        self.closed = True
        self.code = 0


def test_taskbar_is_rehidden_after_explorer_reappears_and_restored_on_close() -> None:
    desktop, guard = TaskbarDesktop(), RecoveryGuard()
    control = TaskbarControl(desktop, lambda: guard)
    control.start()
    control.enforce()
    assert desktop.shown == {101: False}
    desktop.shown[101] = True
    desktop.shown[202] = True  # Explorer restart or a secondary monitor.
    control.enforce()
    assert desktop.shown == {101: False, 202: False}
    control.toggle()
    assert all(desktop.shown.values())
    control.toggle()
    assert not any(desktop.shown.values())
    control.close()
    assert all(desktop.shown.values()) and guard.closed
    control.enforce()
    assert all(desktop.shown.values())


def test_lost_recovery_guard_restores_taskbar_instead_of_leaving_it_hidden() -> None:
    desktop, guard = TaskbarDesktop(), RecoveryGuard()
    control = TaskbarControl(desktop, lambda: guard)
    control.start()
    control.enforce()
    guard.code = 1
    with unittest.TestCase().assertRaises(OSError):
        control.enforce()
    assert desktop.shown == {101: True}
    assert not control.ready
    control.close()


def test_taskbars_are_never_hidden_without_the_recovery_handshake() -> None:
    """Detect acquiring shell ownership after a failed recovery startup."""
    desktop, guard = TaskbarDesktop(), RecoveryGuard(ready=False)
    control = TaskbarControl(desktop, lambda: guard)
    with unittest.TestCase().assertRaisesRegex(OSError, 'recovery could not start'):
        control.start()
    control.enforce()
    assert desktop.shown == {101: True} and guard.closed


class LanguageDesktop:
    """Own changing foreground observations and language requests in this scenario."""

    def __init__(self) -> None:
        self.observations = iter(((11, 0xF002041D), (22, 0x4090409), (22, 0x4090409)))
        self.loads: tuple[str, ...] = ()
        self.activations: tuple[int, ...] = ()
        self.requests: tuple[tuple[int, int], ...] = ()

    def load(self, identity: str) -> int:
        self.loads += (identity,)
        return 0x4090409 if identity == '00000409' else 0xF002041D

    def colemak(self) -> str:
        return 'd001041d'

    def activate(self, layout: int) -> None:
        self.activations += (layout,)

    def foreground(self) -> tuple[int, int]:
        return next(self.observations)

    def request(self, hwnd: int, layout: int) -> None:
        self.requests += ((hwnd, layout),)


def test_keyboard_language_rechecks_each_foreground_and_both_toggle_states() -> None:
    desktop = LanguageDesktop()
    languages = keyboard_language.KeyboardLanguages(desktop)
    languages.enforce(True)
    languages.enforce(True)
    languages.enforce(False)
    assert desktop.loads == ('00000409', 'd001041d')
    assert desktop.activations == (0x4090409, 0xF002041D)
    assert desktop.requests == ((11, 0x4090409), (22, 0xF002041D))


def test_windows_key_observer_preserves_input_and_ignores_other_injected_keys() -> None:
    toggled: list[int] = []
    forwarded: list[tuple[int, int, int]] = []

    def forward(code: int, message: int, pointer: int) -> int:
        forwarded.append((code, message, pointer))
        return 123

    # Read real native structures; only delivery to the next hook and Qt is inert.
    dispatch = WindowsKeyDispatch(99, WindowsKeyEffects(forward=forward, toggle=toggled.append))
    for extra, flags, expected in ((0, inputs.LLKHF_INJECTED, 0), (0, 0, 1), (LAYOUT_MAGIC, inputs.LLKHF_INJECTED, 2)):
        event = inputs.KBDLLHOOKSTRUCT(0x5B, 0x5B, flags, 0, extra)
        pointer = ctypes.addressof(event)
        for message in (system.WM_KEYDOWN, system.WM_KEYUP):
            assert dispatch.observe(0, message, pointer) == 123
            assert forwarded[-1] == (0, message, pointer)
        assert toggled == [99] * expected
    assert dispatch.observe(-1, system.WM_KEYDOWN, 0) == 123
    assert dispatch.observe(0, 0, 0) == 123
    assert len(forwarded) == 8 and toggled == [99, 99]


def test_toolbar_respects_contrast_and_releases_only_its_composition_owner() -> None:
    app = application()
    actions = BarActions(lambda: None, lambda: None, lambda: None, lambda action: None,
                         lambda: None, lambda: None, lambda: None, lambda message: None, inbox=lambda: None)
    bar = DesktopBar(actions, native_shell=False,
                     observations=BarObservations(material=lambda: appearance.Contrast("#000000", "#ffff00")))
    other_view = EventLoop(app, lambda: None)
    try:
        assert not bar.window.glass
        assert bar.window.colors.surface == "#000000" and bar.window.ink.foreground == "#ffff00"
        assert other_view.composition is bar.loop.composition
        bar.close()
        if other_view.composition is not None:
            assert not other_view.composition.closed
    finally:
        bar.close()
        other_view.close()


def test_menu_button_opens_controls_and_audio_trace_only_moves_during_capture() -> None:
    app = application()
    agent: list[str] = []
    actions = BarActions(lambda: agent.append("opened"), lambda: None, lambda: None, lambda action: None,
                         lambda: None, lambda: None, lambda: None, lambda message: None, inbox=lambda: None)
    level = [.25]
    bar = DesktopBar(actions, native_shell=False, audio_level=lambda: level[0],
                     observations=BarObservations(power=lambda: Battery(73, False, False)))
    try:
        # This interaction checks rendered geometry; retain real Qt layout while
        # disabling native shell observers, as in the adjacent spinner fixture.
        bar.visible = True
        bar.render(animate=False)
        assert not bar.audio_timer.isActive()
        assert "73%" in bar.status.text() and "Workspace" not in bar.status.text()
        bar.menu_button.click()
        assert bar.menu.isVisible()
        bar.menu.actions()[0].trigger()
        assert agent == ["opened"]
        bar.menu.close()
        bar.weather = Weather(-3.2, 71, True)
        bar.tick()
        assert "-3°" in bar.status.text()
        assert bar.status.width() >= bar.status.sizeHint().width()
        bar.state(State.LISTENING)
        assert bar.audio_timer.isActive()
        deadline = time.monotonic() + 1
        while bar.status.samples[-1] == 0 and time.monotonic() < deadline:
            bar.sample_audio()
            app.processEvents()
            time.sleep(.005)
        assert bar.status.samples[-1] > 0
        level[0] = 0
        deadline = time.monotonic() + 1
        while bar.status.samples[-1] > 0 and time.monotonic() < deadline:
            bar.sample_audio()
            app.processEvents()
            time.sleep(.005)
        assert bar.status.samples[-1] == 0
        trace = tuple(bar.status.samples)
        bar.state(State.WORKING)
        assert not bar.audio_timer.isActive() and bool(bar.status.processing)
        assert "Transcribing" in bar.status.toolTip()
        bar.sample_audio()
        bar.recording_changed(RecordingState(phase="recording"))
        assert tuple(bar.status.samples) == trace and bool(bar.status.processing)
        bar.state(State.READY)
        assert not bool(bar.status.listening) and not bool(bar.status.processing)
        assert bar.status.text() == bar.ambient.text
    finally:
        bar.close()
        app.processEvents()


def test_transcription_animates_a_compact_spinner_and_stops_after_completion() -> None:
    # Defects: requiring a prior listening frame, showing a frozen waveform,
    # failing to repaint under work, ignoring reduced motion, or leaving a timer running.
    app = application()
    motion = [True]
    actions = BarActions(lambda: None, lambda: None, lambda: None, lambda action: None,
                         lambda: None, lambda: None, lambda: None, lambda message: None, inbox=lambda: None)
    bar = DesktopBar(actions, native_shell=False,
                     observations=BarObservations(motion=lambda: motion[0]))
    bar.visible = True
    try:
        bar.render(animate=False)
        bar.state(State.WORKING)
        assert bool(bar.status.processing) and not bool(bar.status.listening)
        assert bar.loop.timer.isActive() and not bar.audio_timer.isActive()
        bar.status.pulse(10, animate=True)
        first = bar.status.grab().toImage()
        bar.status.pulse(10.3, animate=True)
        assert bar.status.grab().toImage() != first, "Transcription painted a stationary indicator."
        compact = bar.status.sizeHint().width()
        bar.status.capture(listening=True, processing=False)
        assert bar.status.sizeHint().width() == compact + 81, "The spinner retained the waveform's empty space."
        bar.status.capture(listening=False, processing=True)
        motion[0] = False
        bar.paint_frames()
        angle = bar.status.spin_angle
        bar.paint_frames()
        assert bar.status.spin_angle == angle and not bar.loop.timer.isActive()
        assert bool(bar.status.processing) and not bar.status.text()
        assert bar.status.width() == bar.status.height() == 24
        assert "Transcribing" in bar.status.accessibleName()
        motion[0] = True
        bar.state(State.READY)
        bar.paint_frames()
        assert not bool(bar.status.processing) and not bar.loop.timer.isActive()
    finally:
        bar.close()
        app.processEvents()


def test_full_plugged_in_battery_keeps_charger_and_reclaims_percentage_width() -> None:
    # Defect: text policy hides the number but drawing/layout keeps its old width
    # or drops the independent charger symbol.
    app = application()
    power = [Battery(95, True, True)]
    actions = BarActions(lambda: None, lambda: None, lambda: None, lambda action: None,
                         lambda: None, lambda: None, lambda: None, lambda message: None, inbox=lambda: None)
    bar = DesktopBar(actions, native_shell=False, observations=BarObservations(power=lambda: power[0]))
    try:
        width = bar.status.sizeHint().width()
        percent_width = bar.status.fontMetrics().horizontalAdvance("95%")
        power[0] = Battery(96, True, True)
        bar.next_power = 0
        bar.tick()
        assert bool(bar.status.plugged_in) and "Charger connected" in bar.status.accessibleName()
        assert bar.status.text() == bar.ambient.clock
        assert bar.status.sizeHint().width() == width - percent_width
        power[0] = Battery(96, False, False)
        bar.next_power = 0
        bar.tick()
        assert not bool(bar.status.plugged_in) and "96%" in bar.status.text()
    finally:
        bar.close()
        app.processEvents()


def test_slow_native_audio_level_does_not_block_the_waveform_ui() -> None:
    app = application()
    entered, released = threading.Event(), threading.Event()
    caller = threading.current_thread()
    readers: list[threading.Thread] = []

    def level() -> float:
        readers.append(threading.current_thread())
        entered.set()
        released.wait(.25)
        return .25

    actions = BarActions(lambda: None, lambda: None, lambda: None, lambda action: None,
                         lambda: None, lambda: None, lambda: None, lambda message: None, inbox=lambda: None)
    bar = DesktopBar(actions, native_shell=False, audio_level=level)
    try:
        bar.state(State.LISTENING)
        started = time.monotonic()
        bar.sample_audio()
        assert time.monotonic() - started < .025, "A slow driver blocked a waveform frame."
        assert entered.wait(.5), "Listening must start observing the microphone."
        assert readers and all(reader is not caller for reader in readers), "Native audio observation belongs off Qt's thread."
        released.set()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and bar.status.samples[-1] == 0:
            bar.sample_audio()
            app.processEvents()
            time.sleep(.005)
        assert bar.status.samples[-1] > 0, "The native sample did not reach the waveform."
    finally:
        released.set()
        bar.close()
        app.processEvents()


def test_bar_attaches_to_screen_edge_and_status_icons_remain_visible_during_dictation() -> None:
    app = application()
    actions = BarActions(lambda: None, lambda: None, lambda: None, lambda action: None,
                         lambda: None, lambda: None, lambda: None, lambda message: None, inbox=lambda: None)
    bar = DesktopBar(actions, native_shell=False)
    try:
        assert bar.window.y() == app.primaryScreen().geometry().top()
        assert bar.window.attached
        assert bar.window.height() == 28 and bar.status.height() == 24
        resting_width = bar.status.sizeHint().width()
        status = SystemStatus(Speakers.AUDIBLE, Wifi.DISCONNECTED)
        bar.status.system_changed(status)
        assert bar.status.sizeHint().width() > resting_width
        assert "Speakers unmuted" in bar.status.accessibleName() and "Wi-Fi disconnected" in bar.status.accessibleName()
        bar.state(State.LISTENING)
        assert bar.status.system.alerts == ("speaker-on", "wifi-off")
        assert "Speakers unmuted" in bar.status.accessibleName()
        bar.state(State.WORKING)
        assert bar.status.system.alerts == ("speaker-on", "wifi-off")
        bar.state(State.READY)
        bar.status.system_changed(SystemStatus(Speakers.MUTED, Wifi.CONNECTED))
        assert bar.status.sizeHint().width() == resting_width
        assert "Speakers unmuted" not in bar.status.accessibleName()
    finally:
        bar.close()
        app.processEvents()


def test_tiling_menu_keeps_the_window_captured_before_the_popup() -> None:
    app = application()
    invoked: list[tuple[Tool, int]] = []
    actions = BarActions(lambda: None, lambda: None, lambda: None, lambda action: None,
                         lambda: None, lambda: None, lambda: None, lambda message: None,
                         lambda tool, hwnd: invoked.append((tool, hwnd)), inbox=lambda: None)
    foreground = [42]
    bar = DesktopBar(actions, native_shell=False, observations=BarObservations(foreground=lambda: foreground[0]))
    try:
        bar.open_menu()
        submenu = next(action.menu() for action in bar.menu.actions() if action.text() == "Window tiling")
        assert isinstance(submenu, QtWidgets.QMenu)
        foreground[0] = 999
        next(action for action in submenu.actions() if action.text() == "Float or tile the active window").trigger()
        assert invoked == [(Tool.TILE_FLOAT, 42)]
    finally:
        bar.close()
        app.processEvents()


def test_segments_slide_from_above_join_at_rest_and_reverse_without_jumping() -> None:
    app = application()
    actions = BarActions(lambda: None, lambda: None, lambda: None, lambda action: None,
                         lambda: None, lambda: None, lambda: None, lambda message: None, inbox=lambda: None)
    now = 1000.0
    bar = DesktopBar(actions, native_shell=False, observations=BarObservations(clock=lambda: now, motion=lambda: True))
    try:
        bar.timer.stop()
        bar.visible = True
        bar.render(animate=True)
        bar.recording_changed(RecordingState(phase="recording"))
        bar.layer("NAV")
        assert all(pill.y() < pill.anchor.y() for pill in bar.pills)
        assert all(pill.height() == 28 for pill in bar.pills)
        now += .08
        bar.paint_frames()
        assert all(0 < pill.alpha < 1 for pill in bar.pills)
        bar.recording_changed(RecordingState(phase="saved"))
        now += .04
        bar.paint_frames()
        before = bar.capture.y(), bar.capture.alpha
        bar.recording_changed(RecordingState(phase="recording"))
        assert (bar.capture.y(), bar.capture.alpha) == before
        now += .17
        bar.paint_frames()
        assert all(pill.alpha == 1 and pill.y() == pill.anchor.y() for pill in bar.pills)
        assert bar.window.joined_left and bar.window.joined_right
        assert bar.capture.joined_left and bar.keycaps.joined_right
        assert bar.window.x() + bar.window.width() - 6 == bar.capture.x() + 6
        shape = bar.capture.shape()
        assert shape is not None
        mask = painter_path(shape.fill)
        assert mask.contains(QtCore.QPointF(6.25, 3))
        assert not mask.contains(QtCore.QPointF(6.25, 20))
        bar.recording_changed(RecordingState(phase="saved"))
        now += .17
        bar.paint_frames()
        assert not bar.capture.isVisible() and not bar.window.joined_right
    finally:
        bar.close()
        app.processEvents()


def test_reduced_motion_is_immediate_and_the_screen_edge_has_no_stroke() -> None:
    app = application()
    actions = BarActions(lambda: None, lambda: None, lambda: None, lambda action: None,
                         lambda: None, lambda: None, lambda: None, lambda message: None, inbox=lambda: None)
    bar = DesktopBar(actions, native_shell=False, observations=BarObservations(motion=lambda: False))
    try:
        bar.visible = True
        bar.render(animate=False)
        bar.recording_changed(RecordingState(phase="recording"))
        assert bar.capture.alpha == 1 and bar.capture.y() == bar.capture.anchor.y()
        assert not bar.loop.timer.isActive()
        bar.recording_changed(RecordingState(phase="saved"))
        assert bar.capture.alpha == 0 and not bar.capture.isVisible()
        bar.window.material(Tone.REPLY, appearance.Material.SOLID)
        image = bar.window.grab().toImage()
        assert image.pixelColor(image.width() // 2, 0) == QtGui.QColor(bar.window.colors.surface)
    finally:
        bar.close()
        app.processEvents()


def test_window_switcher_search_navigation_and_activation() -> None:
    app = application()
    focused: list[int] = []
    picker = WindowSwitcher((Window(1, 'Editor · current', 'editor.exe', False),
                             Window(2, 'Planning board', 'browser.exe', False),
                             Window(3, 'Archived planning', 'browser.exe', True)), focused.append)
    try:
        assert picker.items.currentRow() == 1  # F6 defaults to the previous window.
        picker.search.setText('planning browser')
        assert picker.items.count() == 2
        key = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Down, QtCore.Qt.KeyboardModifier.NoModifier)
        assert picker.eventFilter(picker.search, key)
        assert picker.items.currentRow() == 1
        picker.activate()
        assert focused == [3]
        picker.filter('no such window')
        picker.activate()
        assert focused == [3]
    finally:
        picker.close()
        app.processEvents()
