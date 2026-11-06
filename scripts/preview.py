"""A restartable real toolbar, with sample data and inert callbacks."""

import argparse
import inspect
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError
lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.qt_runtime import prepare
from runtime import activate
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


class PreviewBar(DesktopBar):
    """Keep the real menu's native-only actions inside the sample adapter too."""

    __slots__ = ()

    def toggle_taskbar(self) -> None:
        self.actions.problem("Windows taskbar")

    def notification_settings(self) -> None:
        self.actions.problem("Windows notification settings")


class Preview:
    """UI-thread owner. Sample actions never reach production effect owners."""

    __slots__ = ("bar", "closed", "control", "files", "root", "selector", "status", "timer")

    def __init__(self, files: Files) -> None:
        screen.use_physical_pixels()
        self.closed = False
        self.files = files
        self.root = application()
        self.control = QtWidgets.QDialog()
        self.control.setWindowTitle("Workspace UI preview · sample data")
        self.control.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.control.finished.connect(self.root.quit)
        layout = QtWidgets.QVBoxLayout(self.control)
        layout.addWidget(QtWidgets.QLabel("Sample data · saves restart these views automatically"))
        self.selector = QtWidgets.QComboBox()
        self.selector.addItems(SCENARIOS)
        layout.addWidget(self.selector)
        self.status = QtWidgets.QLabel("Actions stay in this preview.")
        layout.addWidget(self.status)
        close = QtWidgets.QPushButton("Close preview")
        close.clicked.connect(self.root.quit)
        layout.addWidget(close)
        self.control.resize(440, 160)
        self.bar: DesktopBar | None = None
        self.timer = QtCore.QTimer(self.control)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)
        try:
            actions = BarActions(
                lambda: self.action("Work"),
                lambda: self.action("Stop"),
                lambda action: self.action("Recording: " + action),
                lambda: self.action("Keyboard"),
                lambda: self.action("Overlay"),
                lambda: self.action("Menu"),
                self.action,
                inbox=lambda: self.action("Inbox"),
                open_item=lambda identity: self.action("Open canvas at " + identity),
            )
            self.bar = PreviewBar(actions, native_shell=False)
            self.bar.visible = True
            self.bar.window.setWindowTitle("Workspace preview toolbar")
            try:
                choice = CHOICE.validate_json(files.state.read_bytes())
            except OSError, ValidationError:
                choice = Choice()
            self.selector.setCurrentIndex(choice.scenario)
            self.selector.currentIndexChanged.connect(self.select)
            self.select(choice.scenario)
            self.control.show()
            self.timer.start()
        except BaseException:
            self.close()
            raise

    def action(self, text: str) -> None:
        self.status.setText("Preview action: " + text)

    def select(self, index: int) -> None:
        if self.closed:
            return
        self.files.state.write_bytes(CHOICE.dump_json(Choice(index)))
        recording = RecordingState(phase="recording", seconds=125) if index in (2, 6) else RecordingState()
        if self.bar is not None:
            self.bar.recording_changed(recording)
            asking = Agent("Which sheet should the reply cover?", waiting=True)
            self.bar.agent_changed(WORKING if index in (1, 6) else asking if index == 3 else None)
            self.bar.job_changed(Job.TRANSCRIBING if index in (4, 6) else None)
            self.bar.dictation(active=index in (5, 6))
            if index == 7:
                # A fresh identity announces the sample again each time it is chosen.
                at = time.time()
                text = "Revenue is up 4% against the approved figures; travel is 12% over the Q3 forecast."
                self.bar.notices_changed((Notice(f"reply:preview:{at}", "Compare the budget sheets", text, None, at),))
        self.status.setText("Sample state: " + SCENARIOS[index])

    def tick(self) -> None:
        if self.closed:
            return
        if (self.files.session / "stop").exists():
            self.root.quit()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        if self.bar is not None:
            self.bar.close()
        self.control.close()
        self.control.deleteLater()
        self.root.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def run(options: Options, files: Files) -> None:
    preview = Preview(files)
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
    activate()
    with tempfile.TemporaryDirectory(prefix="workspace-preview-") as folder:
        session = options.session if options.session is not None else Path(folder)
        run(options, Files(session, options.state if options.state is not None else session / "state.json"))


if __name__ == "__main__":
    main()
