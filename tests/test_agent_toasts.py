"""A saved monitor hint is usable only when every coordinate is valid."""

import sys
import unittest
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("The toast owner binds Windows APIs")

from assistant.agent_toasts import saved_monitor
from winapi.shapes import Rect


def test_a_saved_negative_monitor_hint_is_used(tmp_path: Path) -> None:
    path = tmp_path / "agent-panel.json"
    path.write_text('{"x": -1000, "y": 30, "width": 430, "height": 690}')
    assert saved_monitor(path) == Rect(-1000, 30, -570, 720)


def test_missing_or_invalid_coordinates_use_the_default_monitor(tmp_path: Path) -> None:
    path = tmp_path / "agent-panel.json"
    assert saved_monitor(path) is None
    for data in (
        "{",
        "[]",
        '{"x": true, "y": 0, "width": 430, "height": 690}',
        '{"x": 0, "y": 0, "width": 0, "height": 690}',
        '{"x": 0, "y": 0, "width": 430}',
    ):
        path.write_text(data, encoding="utf-8")
        assert saved_monitor(path) is None
