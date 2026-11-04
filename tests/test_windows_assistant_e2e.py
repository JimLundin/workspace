"""End to end on Windows: the real assistant (which starts the real layout), real
key presses, real windows; a fake AI endpoint plays the model.

It takes over the keyboard for half a minute, so it only runs when
asked: `WORKSPACE_E2E=1 pytest tests/test_windows_assistant_e2e.py`. The microphone
isn't tested (test machines rarely have one).
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from tests.fake_endpoint import FakeEndpoint, fake_endpoint
from tests.test_agent import calls, says

if sys.platform != "win32" or os.environ.get("WORKSPACE_E2E") != "1":
    raise unittest.SkipTest("end-to-end tests run on Windows, with WORKSPACE_E2E=1")

lazy from PySide6 import QtCore, QtWidgets

from components import ASSISTANT, CATALOGUE, read_marker
from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application
from protocol import MAGIC
from winapi import inputs, screen, system, windows
from winapi.shapes import Rect

prepare()

ROOT = Path(__file__).resolve().parent.parent
TAB, DELETE, SPACE = 0x2F, 0x34, 0x2E  # the Tools, Apps and Nav thumbs (physical V, . and C)
AGENT_TYPED, MINIMIZE = 0x26, 0x21  # physical L, F


def wait_for(condition: Callable[[], bool], pump: Callable[[], None], seconds: float = 10) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pump()
        if condition():
            return True
        time.sleep(0.05)
    return False


def lit(area: Rect) -> bool:
    """Something is drawn there (the test screen is otherwise black)."""
    return any(screen.capture(area, area.width, area.height))


def chord(thumb: int, key: int) -> None:
    """Hold a layer thumb past the tapping term, tap a key on that layer."""
    inputs.send_scancodes([(thumb, True)], extra=0)
    time.sleep(0.3)
    inputs.send_scancodes([(key, True), (key, False)], extra=0)
    time.sleep(0.05)
    inputs.send_scancodes([(thumb, False)], extra=0)


def type_ascii(text: str) -> None:
    """Plain letters and spaces as virtual keys, tagged so the layout passes them through."""
    for vk in [0x20 if c == " " else ord(c.upper()) for c in text] + [0x0D]:
        for flags in (0, inputs.KEYEVENTF_KEYUP):
            inputs.send_key(vk, inputs.scancode_for(vk), flags, MAGIC)


@contextmanager
def workspace(endpoint: FakeEndpoint, home: Path, live: Path = ROOT) -> Generator[None]:
    """Workspace as the user starts it: the keeper, running layout, assistant, and automation
    from `live`. Logs and state go under `home` (it's LOCALAPPDATA)."""
    env = {
        **os.environ,
        "OPENAI_BASE_URL": endpoint.url,
        "OPENAI_API_KEY": "k",
        "WORKSPACE_MODEL_SMALL": "chat",
        "LOCALAPPDATA": str(home),
    }
    process = subprocess.Popen([sys.executable, str(live / "keeper.py")], cwd=live, env=env)
    try:
        assert wait_for(lambda: both_ready(home), lambda: None, 30), "Workspace didn't start"
        time.sleep(0.5)
        yield
    finally:
        if (hwnd := windows.find(ASSISTANT.window.title)) is not None:
            system.post_message(hwnd, system.WM_CLOSE, 0, 0)  # as Quit in the tray menu: the keeper stops everything
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait()


def both_ready(home: Path) -> bool:
    state = home / "workspace" / "keeper"
    return all(read_marker(entry.marker(state)) is not None for entry in CATALOGUE.values())


@contextmanager
def text_box(text: str) -> Generator[tuple[QtWidgets.QWidget, QtWidgets.QLineEdit]]:
    app = application()
    root = QtWidgets.QWidget()
    root.setGeometry(300, 300, 500, 80)
    layout = QtWidgets.QVBoxLayout(root)
    entry = QtWidgets.QLineEdit(text)
    layout.addWidget(entry)
    root.show()
    root.activateWindow()
    entry.setFocus()
    app.processEvents()
    try:
        yield root, entry
    finally:
        root.hide()
        root.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def logs(home: Path) -> str:
    folder = home / "workspace"
    return "\n".join(f"--- {p.name}\n{p.read_text(encoding='utf-8', errors='replace')[-3000:]}" for p in sorted(folder.glob("*")) if p.is_file())


def test_the_workspace_end_to_end() -> None:
    home = Path(tempfile.mkdtemp())
    try:
        run_everything(home)
    except AssertionError:
        print(logs(home))
        raise


def run_everything(home: Path) -> None:
    keeper = application()  # This process keeps answering native window messages.
    with fake_endpoint() as endpoint, workspace(endpoint, home):
        in_a_text_box()
        agent(endpoint, home, keeper.processEvents)
    used = (home / "workspace" / "usage.jsonl").read_text(encoding="utf-8")
    for feature in ('"minimize"', '"agent_typed"'):
        assert feature in used, feature


def in_a_text_box() -> None:
    with text_box("hello") as (root, _entry):
        # The layer indicator: shown while Nav is held, without taking the keyboard.
        frame = int(root.winId())
        work = next(m.work for m in screen.monitors() if m.primary)
        middle = work.left + work.width // 2
        bottom = Rect(middle - 40, work.bottom - 60, middle + 40, work.bottom - 30)
        inputs.send_scancodes([(SPACE, True)], extra=0)
        assert wait_for(lambda: lit(bottom), QtWidgets.QApplication.processEvents), "no indicator"
        assert windows.foreground() == frame, "the indicator took the focus"
        inputs.send_scancodes([(SPACE, False)], extra=0)
        assert wait_for(lambda: not lit(bottom), QtWidgets.QApplication.processEvents), "the indicator stayed"

        # Window keys: minimize the window, which placement then leaves alone.
        chord(DELETE, MINIMIZE)
        assert wait_for(lambda: windows.is_minimized(frame), QtWidgets.QApplication.processEvents), root.geometry()
        windows.show(frame, windows.SW_RESTORE)


def agent(endpoint: FakeEndpoint, home: Path, pump: Callable[[], None]) -> None:
    """A typed task, a tool call, a final answer, all in the journal."""
    endpoint.replies = [calls(("list_directory", {"path": "C:\\"})), says("C: has folders.")]
    chord(TAB, AGENT_TYPED)
    assert wait_for(lambda: any(w.title == "Workspace · Agent" for w in windows.windows()), pump)
    wait_for(lambda: False, pump, 0.3)
    type_ascii("look at c")
    journal = home / "workspace" / "agent.jsonl"
    assert wait_for(lambda: journal.exists() and "list_directory" in journal.read_text(encoding="utf-8"), pump), "no journal"
    assert any(w.title == "Workspace · Agent" for w in windows.windows())
