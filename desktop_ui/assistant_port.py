"""What the desktop asks of the assistant, and the canvas edits it makes through it.

The desktop never touches the assistant's owners: it sends `contracts.desktop_link`
commands through an `AssistantPort`, and runs on without them while the assistant
is down. `LinkedAssistant` carries them over the link to the assistant process.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

from contracts.canvas_activity import CanvasQuestion, CanvasRequest, CanvasRun
from contracts.desktop_link import AnswerCanvas, ContinueWork, EditCanvas, StartRun, ToAssistant, to_assistant
from contracts.personal_work import Catalog
from contracts.task import TextAnswer
from contracts.work_canvas_contracts import CanvasPublication, Continuation, NotQueued, Queued
from contracts.work_canvas_edits import UserEdit, user_edited
from contracts.work_canvas_model import CanvasDocument
from link.client import Client

UNAVAILABLE = "The assistant is restarting; try again in a moment."


class AssistantPort(Protocol):
    def send(self, command: ToAssistant) -> bool:
        """Queue a command; False while the assistant is down."""
        ...


@dataclass(frozen=True, slots=True)
class LinkedAssistant:
    """The assistant process, over the link's client end."""

    client: Client

    def send(self, command: ToAssistant) -> bool:
        return self.client.send(to_assistant(command))


class RemoteCanvas:
    """The canvas document as the desktop edits it: the assistant's latest publication, with
    each edit applied here at once (edits are pure) and sent for the assistant to record.

    The assistant's publication is the record: the next one replaces this copy, and a
    refused edit is answered with the record as it stands.
    """

    __slots__ = ("_catalog", "_lock", "_port", "_publication")

    def __init__(self, port: AssistantPort) -> None:
        self._port = port
        self._lock = threading.Lock()
        self._publication: CanvasPublication | None = None
        self._catalog = Catalog()

    def published(self, publication: CanvasPublication) -> None:
        with self._lock:
            self._publication = publication

    def catalog_changed(self, catalog: Catalog) -> None:
        with self._lock:
            self._catalog = catalog

    def read(self) -> CanvasDocument:
        with self._lock:
            return self._publication.document if self._publication is not None else CanvasDocument()

    def _sent(self, command: ToAssistant) -> None:
        if not self._port.send(command):
            raise OSError(UNAVAILABLE)

    def commit(self, edit: UserEdit) -> CanvasDocument:
        """The edited document at once; an invalid edit raises ValueError and sends nothing."""
        with self._lock:
            current = self._publication.document if self._publication is not None else CanvasDocument()
            edited = user_edited(current, self._catalog, edit)
        self._sent(EditCanvas(edit))
        return edited

    def start(self, run: CanvasRun) -> Queued | NotQueued:
        document = self.read()
        if not self._port.send(StartRun(run)):
            return NotQueued(document, UNAVAILABLE)
        return Queued(document if run in document.runs else replace(document, runs=(*document.runs, run)))

    def continue_work(self, work_id: str) -> Continuation:
        document = self.read()
        if not self._port.send(ContinueWork(work_id)):
            return NotQueued(document, UNAVAILABLE)
        return Queued(document)

    def waiting(self) -> tuple[CanvasQuestion, ...]:
        with self._lock:
            return self._publication.waiting if self._publication is not None else ()

    def answer(self, request: CanvasRequest, value: TextAnswer, deliver: Callable[[CanvasRequest, TextAnswer], bool]) -> bool:
        """The assistant delivers it to the conversation or task that asked; `deliver` is its own."""
        if not any(question.request == request for question in self.waiting()):
            return False
        return self._port.send(AnswerCanvas(request, value))
