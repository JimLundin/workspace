"""A saved monitor hint is usable only when every coordinate is valid."""

from pathlib import Path

from assistant.panel import PanelPreferences, load_preferences
from winapi.shapes import Rect


def test_panel_loads_a_saved_negative_monitor_hint(tmp_path: Path) -> None:
    path = tmp_path / "agent-panel.json"
    path.write_text('{"x": -1000, "y": 30, "width": 430, "height": 690}')
    assert load_preferences(path) == PanelPreferences(Rect(-1000, 30, -570, 720))


def test_missing_or_invalid_coordinates_use_the_default_monitor(tmp_path: Path) -> None:
    path = tmp_path / "agent-panel.json"
    assert load_preferences(path) == PanelPreferences()
    for data in (
        "{",
        "[]",
        '{"x": true, "y": 0, "width": 430, "height": 690}',
        '{"x": 0, "y": 0, "width": 0, "height": 690}',
        '{"x": 0, "y": 0, "width": 430}',
    ):
        path.write_text(data, encoding="utf-8")
        assert load_preferences(path) == PanelPreferences()
