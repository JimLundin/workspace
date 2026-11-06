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
from desktop_ui.ui_spec import SpecError
from desktop_ui.ui_spec_watch import SpecWatch

prepare()


def install(folder: Path, text: str) -> None:
    """Replace the module whole, as the keeper's install does, which drops a watch on the file.

    A scanner may hold a just-written file in Temp for a moment, so the replace retries briefly.
    """
    partial = folder / "sizes.py.partial"
    partial.write_text(text, encoding="utf-8")
    deadline = time.monotonic() + 2
    while True:
        try:
            partial.replace(folder / "sizes.py")
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
    # applies; or a spec that fails its checks is applied instead of reported.
    install(tmp_path, "HEIGHT = 34\n")

    def load() -> str:
        text = (tmp_path / "sizes.py").read_text(encoding="utf-8")
        if "-" in text:
            raise SpecError("sizes.py: capsule: height must be at least 1")
        return text

    applied: list[str] = []
    problems: list[str] = []
    watch = SpecWatch(tmp_path, load, load(), applied.append, problems.append)
    try:
        install(tmp_path, "HEIGHT = 36\n")
        assert until(lambda: len(applied) == 1)
        assert applied[0] == "HEIGHT = 36\n"
        install(tmp_path, "HEIGHT = -6\n")
        assert until(lambda: len(problems) == 1)
        assert "height" in problems[0] and len(applied) == 1
        install(tmp_path, "HEIGHT = 38\n")
        assert until(lambda: len(applied) == 2)
        assert applied[1] == "HEIGHT = 38\n"
    finally:
        watch.close()
