"""The worker's machine is constructed without a microphone or assistant UI."""

import subprocess
import sys
import unittest
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows machine ownership")


def test_machine_import_and_construction_do_not_load_ui_or_audio() -> None:
    program = """
import os
import sys
from assistant.machine import NativeDesktop, WinMachine
from winapi import windows

owner = windows.create_hidden("workspace machine construction fixture")
try:
    machine = WinMachine(NativeDesktop(owner))
    assert windows.process_id(owner) == os.getpid()
    machine.close_background()
    for name in ("assistant.app", "assistant.desktop", "desktop_ui.ui", "winapi.audio",
                 "winapi.recording", "tkinter", "PySide6"):
        assert name not in sys.modules, name
finally:
    windows.destroy(owner)
assert not windows.exists(owner)
print("Constructed without UI or audio.")
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Constructed without UI or audio."
