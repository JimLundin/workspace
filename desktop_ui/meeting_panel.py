"""Saved meeting recordings and their transcripts."""

import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final

lazy from PySide6 import QtWidgets
lazy from PySide6.QtCore import Qt

from desktop_ui.qt_runtime import prepare
lazy from assistant.meeting_store import MeetingArchive
lazy from assistant.recording_state import duration
lazy from automation.meetings import Meeting, TranscriptState
lazy from desktop_ui.components.controls import button, label
lazy from desktop_ui.components.widgets import Editor, column, replace_text, row

prepare()

MAX_LISTED: Final = 200
MAX_TRANSCRIPT_BYTES: Final = 4 * 1024 * 1024


class MeetingPanel(QtWidgets.QWidget):
    def __init__(self, archive: MeetingArchive, *, open_file: Callable[[Path], None]) -> None:
        super().__init__()
        self.archive, self.open_file = archive, open_file
        self.meetings: dict[str, Meeting] = {}
        layout = row(self)
        layout.setContentsMargins(16, 16, 16, 16)
        left = QtWidgets.QWidget()
        left.setMaximumWidth(310)
        sources = column(left)
        sources.addWidget(label("Recordings", "title"))
        self.recordings = QtWidgets.QTreeWidget()
        self.recordings.setHeaderLabels(["Recorded", "Length"])
        self.recordings.setRootIsDecorated(False)
        self.recordings.setColumnWidth(0, 215)
        self.recordings.setAccessibleName("Saved meeting recordings")
        self.recordings.currentItemChanged.connect(self.show_transcript)
        sources.addWidget(self.recordings, 1)
        self.status = label("", "muted")
        self.status.setWordWrap(True)
        sources.addWidget(self.status)
        sources.addWidget(button("Refresh recordings", self.refresh))
        layout.addWidget(left, 2)
        right = QtWidgets.QWidget()
        content = column(right)
        self.transcript = Editor(readonly=True)
        self.transcript.setAccessibleName("Meeting transcript")
        content.addWidget(self.transcript, 1)
        files = row()
        self.open_transcript = button("Open transcript", self.open_selected)
        files.addWidget(self.open_transcript)
        files.addStretch()
        content.addLayout(files)
        layout.addWidget(right, 5)
        self.show_transcript()

    def refresh(self) -> None:
        selected = self.selected()
        meetings: list[Meeting] = []
        unreadable = 0
        for path in reversed(self.archive.journals()[-MAX_LISTED:]):
            try:
                meetings.append(self.archive.open(path.parent).meeting())
            except OSError, sqlite3.Error, ValueError:
                unreadable += 1
        meetings.sort(key=lambda meeting: meeting.period.started_at, reverse=True)
        self.meetings = {meeting.identity: meeting for meeting in meetings}
        self.recordings.clear()
        for meeting in meetings:
            when = datetime.fromtimestamp(meeting.period.started_at).strftime("%d %b · %H:%M")
            pending = "" if meeting.transcript_state is TranscriptState.COMPLETE else " · transcribing"
            item = QtWidgets.QTreeWidgetItem([f"{meeting.title}\n{when}{pending}", duration(meeting.captured_seconds)])
            item.setData(0, Qt.ItemDataRole.UserRole, meeting.identity)
            item.setToolTip(0, meeting.problem or meeting.title)
            self.recordings.addTopLevelItem(item)
            if selected is not None and meeting.identity == selected.identity:
                self.recordings.setCurrentItem(item)
        self.status.setText(f"{unreadable} recordings could not be read." if unreadable else "")
        self.show_transcript()

    def selected(self) -> Meeting | None:
        item = self.recordings.currentItem()
        identity: object = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return self.meetings.get(identity) if isinstance(identity, str) else None

    def show_transcript(self) -> None:
        meeting = self.selected()
        self.open_transcript.setEnabled(meeting is not None)
        if meeting is None:
            replace_text(self.transcript, "")
            return
        try:
            with Path(meeting.transcript_path).open("rb") as transcript:
                text = transcript.read(MAX_TRANSCRIPT_BYTES).decode("utf-8", errors="replace")
        except OSError as error:
            text = f"The transcript could not be read: {error}"
        replace_text(self.transcript, text)

    def open_selected(self) -> None:
        if (meeting := self.selected()) is not None:
            self.open_file(Path(meeting.transcript_path))
