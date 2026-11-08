"""A restartable real toolbar, with sample data and inert callbacks."""

import argparse
import inspect
import json
import os
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError
lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import Qt

from cell import Cell
from desktop_ui.bar_events import AgentShown, DictationShown, JobShown, RecordingShown
from desktop_ui.qt_runtime import prepare
lazy from contracts.recording_state import RecordingState
lazy from contracts.status import Job
lazy from desktop_ui.desktop_bar import BarActions, DesktopBar
lazy from desktop_ui.island_model import Agent
lazy from desktop_ui.island_moment import Notice
lazy from desktop_ui.qt_ui import application
lazy from winapi import screen

prepare()

SCENARIOS = ("Idle", "Agent working", "Recording", "Needs input", "Transcribing", "Dictating", "Everything at once", "Agent reply")


WORKING: Final = Agent("Comparing both sheets", waiting=False, steps=("Read file", "Checking the plans", "PowerShell"))


@dataclass(frozen=True, slots=True)
class Choice:
    scenario: int = 1

    def __post_init__(self) -> None:
        if not 0 <= self.scenario < len(SCENARIOS):
            raise ValueError("Choose a known preview scenario.")


@dataclass(frozen=True, slots=True)
class Files:
    session: Path
    state: Path


@dataclass(frozen=True, slots=True)
class Options:
    session: Path | None = None
    state: Path | None = None
    duration: float | None = None


CHOICE = TypeAdapter[Choice](Choice)
OPTIONS = TypeAdapter[Options](Options)


@dataclass(frozen=True, slots=True)
class _Previewing:
    bar: DesktopBar | None = None
    closed: bool = False


@dataclass(frozen=True, slots=True)
class Preview:
    """UI-thread owner. Sample actions never reach production effect owners."""

    files: Files
    root: QtWidgets.QApplication
    control: QtWidgets.QDialog
    selector: QtWidgets.QComboBox
    status: QtWidgets.QLabel
    timer: QtCore.QTimer
    _previewing: Cell[_Previewing] = field(default_factory=lambda: Cell(_Previewing()), init=False, repr=False)

    @classmethod
    def open(cls, files: Files) -> Preview:
        screen.use_physical_pixels()
        root = application()
        control = QtWidgets.QDialog()
        control.setWindowTitle("Workspace UI preview · sample data")
        control.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        control.finished.connect(root.quit)
        layout = QtWidgets.QVBoxLayout(control)
        layout.addWidget(QtWidgets.QLabel("Sample data · saves restart these views automatically"))
        selector = QtWidgets.QComboBox()
        selector.addItems(SCENARIOS)
        layout.addWidget(selector)
        status = QtWidgets.QLabel("Actions stay in this preview.")
        layout.addWidget(status)
        close = QtWidgets.QPushButton("Close preview")
        close.clicked.connect(root.quit)
        layout.addWidget(close)
        control.resize(440, 160)
        timer = QtCore.QTimer(control)
        timer.setInterval(50)
        preview = cls(files, root, control, selector, status, timer)
        timer.timeout.connect(preview.tick)
        try:
            actions = BarActions(
                lambda: preview.action("Work"),
                lambda: preview.action("Stop"),
                lambda action: preview.action("Recording: " + action),
                lambda: preview.action("Keyboard"),
                lambda: preview.action("Overlay"),
                lambda: preview.action("Menu"),
                preview.action,
                inbox=lambda: preview.action("Inbox"),
                open_item=lambda identity: preview.action("Open canvas at " + identity),
            )
            # The real menu's native-only actions stay inside the sample adapter too.
            sampled = replace(
                actions,
                taskbar=lambda: preview.action("Windows taskbar"),
                notification_settings=lambda: preview.action("Windows notification settings"),
            )
            bar = DesktopBar.open(sampled, native_shell=False)
            preview._previewing.set(_Previewing(bar))
            bar.show(visible=True)
            bar.window.setWindowTitle("Workspace preview toolbar")
            try:
                choice = CHOICE.validate_json(files.state.read_bytes())
            except OSError, ValidationError:
                choice = Choice()
            selector.setCurrentIndex(choice.scenario)
            selector.currentIndexChanged.connect(preview.select)
            preview.select(choice.scenario)
            control.show()
            timer.start()
        except BaseException:
            preview.close()
            raise
        return preview

    @property
    def bar(self) -> DesktopBar | None:
        return self._previewing.get().bar

    def action(self, text: str) -> None:
        self.status.setText("Preview action: " + text)

    def select(self, index: int) -> None:
        previewing = self._previewing.get()
        if previewing.closed:
            return
        self.files.state.write_bytes(CHOICE.dump_json(Choice(index)))
        recording = RecordingState(phase="recording", seconds=125) if index in (2, 6) else RecordingState()
        if (bar := previewing.bar) is not None:
            bar.handle(RecordingShown(recording))
            asking = Agent("Which sheet should the reply cover?", waiting=True)
            bar.handle(AgentShown(WORKING if index in (1, 6) else asking if index == 3 else None))
            bar.handle(JobShown(Job.TRANSCRIBING if index in (4, 6) else None))
            bar.handle(DictationShown(index in (5, 6)))
            if index == 7:
                # A fresh identity announces the sample again each time it is chosen.
                at = time.time()
                text = "Revenue is up 4% against the approved figures; travel is 12% over the Q3 forecast."
                bar.notices_changed((Notice(f"reply:preview:{at}", "Compare the budget sheets", text, None, at),))
        self.status.setText("Sample state: " + SCENARIOS[index])

    def tick(self) -> None:
        if self._previewing.get().closed:
            return
        if (self.files.session / "stop").exists():
            self.root.quit()

    def close(self) -> None:
        previewing = self._previewing.get()
        if previewing.closed:
            return
        self._previewing.set(replace(previewing, closed=True))
        self.timer.stop()
        if previewing.bar is not None:
            previewing.bar.close()
        self.control.close()
        self.control.deleteLater()
        self.root.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def run(options: Options, files: Files) -> None:
    preview = Preview.open(files)
    try:
        preview.root.processEvents()
        ready: dict[str, int | str] = {"pid": os.getpid()}
        (files.session / "ready.json").write_text(json.dumps(ready), encoding="utf-8")
        if options.duration is not None:
            QtCore.QTimer.singleShot(round(options.duration * 1000), preview.root.quit)
        preview.root.exec()
    finally:
        preview.close()
        (files.session / "closed").touch()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--duration", type=float, help="bounded smoke run in seconds")
    observed: dict[str, object] = dict(inspect.getmembers(parser.parse_args()))
    options = OPTIONS.validate_python(observed)
    if options.duration is not None and options.duration <= 0:
        parser.error("--duration must be positive")
    with tempfile.TemporaryDirectory(prefix="workspace-preview-") as folder:
        session = options.session if options.session is not None else Path(folder)
        run(options, Files(session, options.state if options.state is not None else session / "state.json"))


if __name__ == "__main__":
    main()
