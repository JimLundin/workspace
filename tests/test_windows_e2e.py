"""End to end on Windows: the real layout process, real key presses, a real window.

It presses physical keys with SendInput, so it takes over the keyboard for a few
seconds; that's why it only runs when asked: `WORKSPACE_E2E=1 pytest tests/test_windows_e2e.py`.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
import unittest
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if sys.platform != "win32" or os.environ.get("WORKSPACE_E2E") != "1":
    raise unittest.SkipTest("end-to-end tests run on Windows, with WORKSPACE_E2E=1")

import ctypes  # noqa: E402

from assistant.qt import QtCore, QtWidgets  # noqa: E402
from assistant.qt_ui import application  # noqa: E402
from assistant.shell_controls import WindowsKeyObserver  # noqa: E402
from protocol import (  # noqa: E402
    LAYOUT_WINDOW,
    MAGIC,
    WM_QUIT_LAYOUT,
)
from winapi import inputs, shell, system, windows  # noqa: E402 (Windows only)
from winapi._core import fn, kernel32  # noqa: E402

_GetModuleHandle = fn(kernel32, 'GetModuleHandleW', ctypes.c_void_p, ctypes.c_wchar_p)
_GetProcAddress = fn(kernel32, 'GetProcAddress', ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
UNDER_WINE = bool(_GetProcAddress(_GetModuleHandle('ntdll.dll'), b'wine_get_version'))
"""Wine garbles typed Unicode text (KEYEVENTF_UNICODE) into native text boxes; real Windows doesn't."""

SCANCODES = {
    "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07, "8": 0x09, "9": 0x0A,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14, "i": 0x17, "o": 0x18,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "k": 0x25, "l": 0x26, ";": 0x27,
    "c": 0x2E, "v": 0x2F, ".": 0x34, "/": 0x35,
}  # fmt: skip


def wait_for(condition: Callable[[], bool], pump: Callable[[], None], seconds: float = 5) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pump()
        if condition():
            return True
        time.sleep(0.02)
    return False


def layout_running() -> bool:
    lock = system.create_lock("Local\\miryoku")
    if lock is None:
        return True
    system.release_lock(lock)
    return False


def focus_fixture(handle: int) -> None:
    # Establish native-test focus permission without a click, cursor movement or key press.
    inputs._send([inputs.INPUT(0, inputs.INPUT_UNION(mi=inputs.MOUSEINPUT()))])  # pyright: ignore[reportPrivateUsage]
    assert windows.focus(handle), 'Windows refused fixture focus; no keys sent.'
    assert windows.foreground() == handle


@contextmanager
def layout() -> Generator[None]:
    assert wait_for(lambda: not layout_running(), lambda: None), "a layout from before is still running"
    process = subprocess.Popen([sys.executable, "-m", "miryoku"], cwd=ROOT)
    assert wait_for(lambda: windows.find(LAYOUT_WINDOW) is not None, lambda: None), "the layout didn't start"
    time.sleep(0.3)
    try:
        yield
    finally:
        if (hwnd := windows.find(LAYOUT_WINDOW)) is not None:
            system.post_message(hwnd, WM_QUIT_LAYOUT, 0, 0)
        process.wait(timeout=5)


@contextmanager
def text_box() -> Generator[tuple[QtWidgets.QWidget, QtWidgets.QLineEdit]]:
    app = application()
    root = QtWidgets.QWidget()
    root.setGeometry(300, 300, 500, 80)
    layout = QtWidgets.QVBoxLayout(root)
    entry = QtWidgets.QLineEdit()
    layout.addWidget(entry)
    root.show()
    root.activateWindow()
    entry.setFocus()
    app.processEvents()
    try:
        focus_fixture(int(root.winId()))
        yield root, entry
    finally:
        root.hide()
        root.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)



def tap(*names: str) -> None:
    for name in names:
        inputs.send_scancodes([(SCANCODES[name], True), (SCANCODES[name], False)], extra=0)
        time.sleep(0.03)


def test_layout_types_colemak_dh_and_expands_snippets() -> None:
    with layout(), text_box() as (_root, entry):
        tap("2", "3", "4", "5")  # top row moved up: q w f p
        tap("q", "w", "e", "r")  # home row taps: a r s t
        assert wait_for(lambda: entry.text() == "qwfparst", QtWidgets.QApplication.processEvents), entry.text()
        tap(";", ";", "r", "l", "a")  # , , t h x: a snippet
        if UNDER_WINE:  # the trigger is erased; what's typed instead can't be checked here
            assert wait_for(lambda: len(entry.text()) > len("qwfparst") and "," not in entry.text(),
                            QtWidgets.QApplication.processEvents), entry.text()
        else:
            assert wait_for(lambda: entry.text() == "qwfparstThanks!", QtWidgets.QApplication.processEvents), entry.text()
            assert windows.foreground() == int(_root.winId()), 'Fixture lost focus; no text sent.'
            inputs.type_text(' voice input', MAGIC)
            assert wait_for(lambda: entry.text() == 'qwfparstThanks! voice input', QtWidgets.QApplication.processEvents), entry.text()


def input_response(body: bytes) -> int | str:
    value: object = json.loads(body)
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and len(value) <= 1024:
        return value
    raise ValueError('Invalid native input-fixture response.')


def test_taskbar_observer_keeps_keyboard_responsive_while_creator_waits() -> None:
    assert not layout_running(), 'Preserve a running keyboard layout.'
    fixture = subprocess.Popen([sys.executable, '-m', 'tests.test_windows_e2e', '--input-fixture'], cwd=ROOT,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    stream = fixture.stdout
    assert stream is not None
    responses: queue.Queue[int | str] = queue.Queue(maxsize=128)
    def read() -> None:
        for line in stream:
            responses.put_nowait(input_response(line))
    reader = threading.Thread(target=read, name='native input observations', daemon=True)
    reader.start()
    handle = responses.get(timeout=8)
    assert isinstance(handle, int)
    owner = shell.AppWindow('Workspace input-check owner', lambda _h, _m, _w, _l: None)
    observer: WindowsKeyObserver | None = None
    sender: threading.Thread | None = None
    try:
        focus_fixture(handle)
        inputs.type_text('x', MAGIC)
        assert responses.get(timeout=2) == 'x'
        observer = WindowsKeyObserver(owner.handle)
        def send() -> None:
            inputs.type_text('y', MAGIC)
        sender = threading.Thread(target=send, name='native input sender', daemon=True)
        started = time.monotonic()
        sender.start()
        # The independent text field keeps pumping while the toolbar's creator waits.
        try:
            response = responses.get(timeout=.2)
        except queue.Empty as error:
            raise AssertionError('Typing stalled behind the taskbar hook.') from error
        assert response == 'xy'
        assert time.monotonic() - started < .2, 'Typing stalled behind the taskbar hook.'
    finally:
        if observer is not None:
            observer.close()
        owner.destroy()
        if sender is not None:
            sender.join(timeout=2)
        system.post_message(handle, system.WM_CLOSE, 0, 0)
        try:
            fixture.wait(timeout=5)
        except subprocess.TimeoutExpired:
            fixture.terminate()  # This test owns the disposable input process.
            fixture.wait(timeout=3)
        reader.join(timeout=2)
        for pipe in (fixture.stdout, fixture.stderr):
            if pipe is not None:
                pipe.close()


def test_mapped_typing_and_unicode_dictation_reach_a_real_console(tmp_path: Path) -> None:
    result = tmp_path / 'console-input.json'
    conhost = Path(os.environ['WINDIR']) / 'System32' / 'conhost.exe'
    console = subprocess.Popen([str(conhost), sys.executable, '-m', 'tests.test_windows_e2e', '--console-fixture', str(result)], cwd=ROOT)
    handle: int | None = None
    try:
        assert wait_for(lambda: windows.find('Workspace disposable console input') is not None, lambda: None)
        handle = windows.find('Workspace disposable console input')
        assert handle is not None
        with layout():
            focus_fixture(handle)
            tap('2', '3', '4', '5', 'q', 'w', 'e', 'r')
            assert windows.foreground() == handle, 'Console fixture lost focus; no text sent.'
            transcript = 'Workspace transcription validation. ' * 15
            inputs.type_text(' ' + transcript, MAGIC)
            assert windows.foreground() == handle, 'Console fixture lost focus after dictation.'
            tap('2', '3', '4', '5', 'q', 'w', 'e', 'r')
            inputs.type_text('\n', MAGIC)
            assert wait_for(result.exists, lambda: None)
            assert json.loads(result.read_text(encoding='utf-8')) == 'qwfparst ' + transcript + 'qwfparst'
        console.wait(timeout=5)
    finally:
        if console.poll() is None:
            if handle is not None:
                system.post_message(handle, system.WM_CLOSE, 0, 0)
            try:
                console.wait(timeout=5)
            except subprocess.TimeoutExpired:
                console.terminate()  # This test owns the disposable console host.
                console.wait(timeout=3)


if __name__ == '__main__' and '--input-fixture' in sys.argv:
    app = application()
    app.setQuitOnLastWindowClosed(True)
    entry = QtWidgets.QLineEdit()
    entry.setWindowTitle('Workspace independent keyboard input fixture')
    entry.resize(480, 80)
    def changed(text: str) -> None:
        print(json.dumps(text), flush=True)
    entry.textChanged.connect(changed)
    entry.show()
    entry.setFocus()
    app.processEvents()
    print(json.dumps(int(entry.winId())), flush=True)
    app.exec()

if __name__ == '__main__' and '--console-fixture' in sys.argv:
    set_title = fn(kernel32, 'SetConsoleTitleW', ctypes.c_int, ctypes.c_wchar_p)
    if not set_title('Workspace disposable console input'):
        raise OSError('Could not name the disposable console.')
    # Read a line as data; this fixture never evaluates or executes the input.
    Path(sys.argv[-1]).write_text(json.dumps(input()), encoding='utf-8')
