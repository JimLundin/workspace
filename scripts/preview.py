"""Restartable real toolbar/feed views, with sample data and inert callbacks."""

import argparse
import inspect
import json
import os
import queue
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter, ValidationError
lazy from PySide6 import QtCore, QtWidgets
lazy from PySide6.QtCore import Qt

from assistant.qt_runtime import prepare
from runtime import activate
lazy from assistant.agent_session import Answer, StreamState, Succeeded, ToolActivity
lazy from assistant.agent_toasts import AgentToasts
lazy from assistant.agent_window import AgentWindow
lazy from assistant.desktop_bar import BarActions, DesktopBar
lazy from assistant.feed_triage import Assessment, Board
lazy from assistant.icons import State
lazy from assistant.panel import PanelPreferences
lazy from assistant.qt_ui import application
lazy from assistant.recording_state import RecordingState
lazy from winapi import screen
lazy from winapi.shapes import Rect

prepare()

SCENARIOS = ('Idle', 'Agent working', 'Recording', 'Keyboard mode', 'Needs input', 'Transcribing', 'Dictating')


@dataclass(frozen=True, slots=True)
class Choice:
    scenario: int = 1

    def __post_init__(self) -> None:
        if not 0 <= self.scenario < len(SCENARIOS):
            raise ValueError('Choose a known preview scenario.')


@dataclass(frozen=True, slots=True)
class Files:
    session: Path
    state: Path


@dataclass(frozen=True, slots=True)
class Options:
    surface: Literal['toolbar', 'feed', 'both'] = 'both'
    session: Path | None = None
    state: Path | None = None
    duration: float | None = None


CHOICE = TypeAdapter[Choice](Choice)
OPTIONS = TypeAdapter[Options](Options)


class PreviewBar(DesktopBar):
    """Keep the real menu's native-only actions inside the sample adapter too."""

    __slots__ = ()

    def toggle_taskbar(self) -> None:
        self.actions.problem('Windows taskbar')

    def notification_settings(self) -> None:
        self.actions.problem('Windows notification settings')


class Preview:
    """UI-thread owner. Sample actions never reach production effect owners."""

    __slots__ = ('agent', 'bar', 'closed', 'control', 'feed', 'files', 'jobs', 'root', 'selector', 'status', 'timer')

    def __init__(self, surface: Literal['toolbar', 'feed', 'both'], files: Files) -> None:
        screen.use_physical_pixels()
        self.closed = False
        self.files = files
        self.root = application()
        self.control = QtWidgets.QDialog()
        self.control.setWindowTitle('Workspace UI preview · sample data')
        self.control.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.control.finished.connect(self.root.quit)
        layout = QtWidgets.QVBoxLayout(self.control)
        layout.addWidget(QtWidgets.QLabel('Sample data · saves restart these views automatically'))
        self.selector = QtWidgets.QComboBox()
        self.selector.addItems(SCENARIOS)
        layout.addWidget(self.selector)
        self.status = QtWidgets.QLabel('Actions stay in this preview.')
        layout.addWidget(self.status)
        close = QtWidgets.QPushButton('Close preview')
        close.clicked.connect(self.root.quit)
        layout.addWidget(close)
        self.control.resize(440, 160)
        self.jobs: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self.feed: AgentToasts | None = None
        self.agent: AgentWindow | None = None
        self.bar: DesktopBar | None = None
        self.timer = QtCore.QTimer(self.control)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.tick)
        try:
            if surface in ('feed', 'both'):
                self.agent = AgentWindow(lambda: self.action('Stop'), post=self.jobs.put, create_view=self.build_feed,
                                         on_submit=self.submitted, on_problem=self.action)
                self.drain()
                if not self.agent.ready.is_set():
                    raise RuntimeError('The preview feed did not initialize.')
            if surface in ('toolbar', 'both'):
                actions = BarActions(lambda: self.action('Agent'), lambda: self.action('Work'), lambda: self.action('Stop'),
                                     lambda action: self.action('Recording: ' + action), lambda: self.action('Keyboard'),
                                     lambda: self.action('Overlay'), lambda: self.action('Menu'), self.action,
                                     inbox=lambda: self.action('Inbox'))
                self.bar = PreviewBar(actions, native_shell=False)
                self.bar.visible = True
                for index, pill in enumerate(self.bar.pills):
                    pill.setWindowTitle(f'Workspace preview toolbar {index}')
            try:
                choice = CHOICE.validate_json(files.state.read_bytes())
            except (OSError, ValidationError):
                choice = Choice()
            self.selector.setCurrentIndex(choice.scenario)
            self.selector.currentIndexChanged.connect(self.select)
            self.select(choice.scenario)
            self.control.show()
            self.timer.start()
        except BaseException:
            self.close()
            raise

    def build_feed(self, agent: AgentWindow) -> AgentToasts:
        self.feed = AgentToasts(self.root, agent, preferences=PanelPreferences(Rect(40, 200, 440, 900)), remember=False)
        return self.feed

    def action(self, text: str) -> None:
        self.status.setText('Preview action: ' + text)

    def submitted(self, text: str) -> None:
        self.action('Sample reply: ' + text)

    def drain(self) -> None:
        while True:
            try:
                self.jobs.get_nowait()()
            except queue.Empty:
                return

    def select(self, index: int) -> None:
        if self.closed:
            return
        self.files.state.write_bytes(CHOICE.dump_json(Choice(index)))
        recording = RecordingState(phase='recording', seconds=125) if index == 2 else RecordingState()
        if self.bar is not None:
            self.bar.recording_changed(recording)
            self.bar.layout(index != 3)
            states = (State.READY, State.AGENT, State.READY, State.READY, State.NEEDS_INPUT, State.WORKING, State.LISTENING)
            self.bar.state(states[index])
        if self.agent is not None:
            self.agent.reset()
            self.agent.triage(Board(enabled=True, items=(
                Assessment('preview-budget', (), 'Review the sample budget', 'Check **the totals** in `FY27`.',
                           'Compare the two sample sheets.', '', 2, time.time()),
                Assessment('preview-brief', (), 'Prepare the Friday brief', 'A fictional teammate asks for a short summary.',
                           'Draft three points for review.', '', 1, time.time()),
            )))
            self.agent.begin('Review the sample workbook', lambda: self.action('Stop'))
            publish = self.agent.updates()
            publish(ToolActivity('preview-tool', 'run_powershell', 'Write-Output "sample result"', time.time(),
                                 Succeeded('The sample workbook has 12 rows.')))
            publish(Answer('preview-reply', 'The **sample totals** are ready for review.', time.time(), StreamState.COMPLETE))
            self.agent.finish()
            self.agent.show(focus=False)
            self.drain()
        self.status.setText('Sample state: ' + SCENARIOS[index])

    def tick(self) -> None:
        if self.closed:
            return
        self.drain()
        if (self.files.session / 'stop').exists():
            self.root.quit()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        if self.agent is not None:
            self.agent.close()
            self.drain()
        if self.bar is not None:
            self.bar.close()
        self.control.close()
        self.control.deleteLater()
        self.root.processEvents()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def run(options: Options, files: Files) -> None:
    preview = Preview(options.surface, files)
    try:
        preview.root.processEvents()
        ready: dict[str, int | str] = {'pid': os.getpid(), 'surface': options.surface}
        (files.session / 'ready.json').write_text(json.dumps(ready), encoding='utf-8')
        if options.duration is not None:
            QtCore.QTimer.singleShot(round(options.duration * 1000), preview.root.quit)
        preview.root.exec()
    finally:
        preview.close()
        (files.session / 'closed').touch()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--surface', choices=('toolbar', 'feed', 'both'), default='both')
    parser.add_argument('--session', type=Path)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--duration', type=float, help='bounded smoke run in seconds')
    observed: dict[str, object] = dict(inspect.getmembers(parser.parse_args()))
    options = OPTIONS.validate_python(observed)
    if options.duration is not None and options.duration <= 0:
        parser.error('--duration must be positive')
    activate()
    with tempfile.TemporaryDirectory(prefix='workspace-preview-') as folder:
        session = options.session if options.session is not None else Path(folder)
        run(options, Files(session, options.state if options.state is not None else session / 'state.json'))


if __name__ == '__main__':
    main()
