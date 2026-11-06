"""Live spec reload through a real Qt file watcher on a real folder."""

import sys
import time
import unittest
from collections.abc import Callable
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("Windows spec reload")

from desktop_ui.qt_runtime import prepare
from desktop_ui.qt_ui import application
from desktop_ui.ui_spec import SHIPPED, Sizes, sizes
from desktop_ui.ui_spec_watch import SpecWatch

prepare()

TOKENS = (SHIPPED / "tokens.toml").read_text(encoding="utf-8")


def install(folder: Path, text: str) -> None:
    """Replace the file whole, as the keeper's install does, which drops a watch on the file.

    A scanner may hold a just-written file in Temp for a moment, so the replace retries briefly.
    """
    partial = folder / "tokens.toml.partial"
    partial.write_text(text, encoding="utf-8")
    deadline = time.monotonic() + 2
    while True:
        try:
            partial.replace(folder / "tokens.toml")
            return
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def until(condition: Callable[[], bool], seconds: float = 5.0) -> bool:
    app = application()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_installed_edits_apply_and_a_broken_one_keeps_the_last_good_spec(tmp_path: Path) -> None:
    # Defects: a replaced file is no longer watched, so the second install never
    # applies; or a spec that fails validation is half-applied instead of reported.
    install(tmp_path, TOKENS)
    applied: list[Sizes] = []
    problems: list[str] = []
    watch = SpecWatch(tmp_path, sizes, sizes(tmp_path), applied.append, problems.append)
    try:
        install(tmp_path, TOKENS.replace("height = 34", "height = 36"))
        assert until(lambda: len(applied) == 1)
        assert applied[0].capsule.height == 36
        install(tmp_path, TOKENS.replace("gap = 6 ", "gap = -6 "))
        assert until(lambda: len(problems) == 1)
        assert "bar.gap" in problems[0] and len(applied) == 1
        install(tmp_path, TOKENS.replace("height = 34", "height = 38"))
        assert until(lambda: len(applied) == 2)
        assert applied[1].capsule.height == 38
    finally:
        watch.close()
