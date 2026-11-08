"""Automatic personal-work collection with durable edits and bounded model reviews."""

import hashlib
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Protocol

from assistant.meeting_store import MeetingStore
from assistant.personal_work_sources import Observations
from assistant.personal_work_store import PersonalStore
from cell import Cell
from contracts.personal_work import (
    CORRELATION_INPUT,
    PERSONAL_REQUEST,
    PERSONAL_RESPONSE,
    AddDocument,
    AddWebPage,
    Catalog,
    CorrelationInput,
    DismissWork,
    DocumentAdded,
    ListWork,
    MeetingSource,
    PersonalRequest,
    PersonalResponse,
    PersonalView,
    RestoreWork,
    SaveWork,
    Source,
    SourceKind,
    SourceOrigin,
    UnlinkWork,
    WorkPlan,
    WorkRefused,
    WorkSaved,
    WorkThread,
    source_id,
)


class Sources(Protocol):
    def read(self, at: float, cancel: threading.Event) -> Observations: ...
    def refresh(self) -> None: ...
    def close(self) -> None: ...


type Model = Callable[[CorrelationInput, threading.Event], WorkPlan]


def correlation_input(catalog: Catalog) -> CorrelationInput:
    # The latest sixty observations bound model input. Retained connections in
    # saved work remain visible even when their original page is no longer rendered.
    def order(source: Source) -> tuple[float, str]:
        return -source.observed_at, source.id

    ordered = tuple(sorted(catalog.sources, key=order))
    roots = tuple(source for source in ordered if source.parent_id is None)[:60]
    offered = frozenset(source.id for source in roots)
    # A bounded review never sees a message without its conversation reference.
    pieces = tuple(source for source in ordered if source.parent_id in offered)[: 60 - len(roots)]
    sources = (*roots, *pieces)
    return CorrelationInput(catalog.revision, catalog.works, sources, catalog.rejected, catalog.dismissed)


def signature(catalog: Catalog) -> str:
    request = correlation_input(catalog)

    # Observation timestamps do not invalidate a review of unchanged content.
    def identity(source: Source) -> str:
        return source.id

    canonical = replace(
        request, catalog_revision=0, sources=tuple(replace(source, observed_at=0) for source in sorted(request.sources, key=identity))
    )
    return hashlib.sha256(CORRELATION_INPUT.dump_json(canonical)).hexdigest()


type Command = SaveWork | UnlinkWork | AddDocument | AddWebPage | DismissWork | RestoreWork
"""A UI write the worker applies in order."""


@dataclass(frozen=True, slots=True)
class _Reviewing:
    view: PersonalView
    reviewed: str | None = None
    """The signature of the catalog last reviewed by the model."""
    force: bool = False
    """Review on the next tick even if nothing changed."""


@dataclass(frozen=True, slots=True)
class PersonalWork:
    """The worker owns polling/queued UI writes; HTTP handlers own their own transactions.

    Locks, lifecycle flags, queue and last-reviewed signature are scheduling state
    local to this owner. The catalog, source observations and view stay immutable.
    """

    # Store, source reader, UI publisher, model and clock have independent
    # effect ownership. Dismissal cancels bound research only after its
    # correction commits; the model can only return a typed connection plan.
    store: PersonalStore
    sources: Sources
    publish: Callable[[PersonalView], None]
    _state: Cell[_Reviewing]
    """Replaced whole under the lock."""
    model: Model | None = field(default=None, kw_only=True)
    clock: Callable[[], float] = field(default=time.time, kw_only=True)
    dismissed: Callable[[WorkThread], None] | None = field(default=None, kw_only=True)
    lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    closed: threading.Event = field(default_factory=threading.Event, init=False)
    wake: threading.Event = field(default_factory=threading.Event, init=False)
    commands: queue.Queue[Command] = field(default_factory=lambda: queue.Queue[Command](maxsize=64), init=False)
    _started: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _finished: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    """Set when the worker thread's run returns; a started thread isn't kept."""

    @classmethod
    def open(  # noqa: PLR0913 - injected collaborators and test seams
        cls,
        store: PersonalStore,
        sources: Sources,
        publish: Callable[[PersonalView], None],
        *,
        model: Model | None = None,
        clock: Callable[[], float] = time.time,
        dismissed: Callable[[WorkThread], None] | None = None,
    ) -> PersonalWork:
        """The service, showing the stored catalog until its first review."""
        return cls(store, sources, publish, Cell(_Reviewing(PersonalView(store.read()))), model=model, clock=clock, dismissed=dismissed)

    @property
    def view(self) -> PersonalView:
        return self._state.get().view

    def snapshot(self) -> PersonalView:
        with self.lock:
            return self._state.get().view

    def show(self, catalog: Catalog, status: str) -> None:
        with self.lock:
            if catalog.revision < self._state.get().view.catalog.revision:
                return
            new_view = PersonalView(catalog, status)
            self._state.set(replace(self._state.get(), view=new_view))
            self.publish(self._state.get().view)

    def start(self) -> None:
        with self.lock:
            if not self._started.is_set():
                self._started.set()
                threading.Thread(target=self._finishing, args=(self.run,), name="personal work", daemon=True).start()

    def _finishing(self, run: Callable[[], None]) -> None:
        try:
            run()
        finally:
            self._finished.set()

    def refresh(self) -> None:
        with self.lock:
            self._state.set(replace(self._state.get(), force=True))
            self.wake.set()

    def observe_meeting(self, store: MeetingStore) -> None:
        meeting, preview = store.observation()
        source = MeetingSource(source_id(SourceKind.MEETING, meeting.identity), meeting, preview, self.clock())
        catalog = self.store.observe((source,))
        self.show(catalog, "Meeting added to the canvas. Connections update from its conversation.")
        self.wake.set()

    def enqueue(self, command: SaveWork | UnlinkWork | AddDocument | AddWebPage | DismissWork | RestoreWork) -> None:
        # Pydantic trusts existing dataclass instances by default. The wire
        # round-trip revalidates their constrained fields before queue admission;
        # its parsing implementation is trusted, not part of Workspace's tests.
        try:
            validated = PERSONAL_REQUEST.validate_json(PERSONAL_REQUEST.dump_json(command))
        except ValueError as error:
            raise ValueError("Invalid personal work edit.") from error
        match validated:
            case SaveWork() | UnlinkWork() | AddDocument() | AddWebPage() | DismissWork() | RestoreWork():
                command = validated
            case _:
                raise ValueError("Invalid personal work edit.")
        if self.closed.is_set():
            raise ValueError("My work is closing.")
        try:
            self.commands.put_nowait(command)
        except queue.Full as error:
            raise ValueError("My work is busy. Try this edit again.") from error
        self.wake.set()

    def handle(self, request: PersonalRequest, *, origin: SourceOrigin = SourceOrigin.AGENT) -> PersonalResponse:
        try:
            response = self.store.handle(request, self.clock(), origin=origin)
        except ValueError as error:
            return WorkRefused(str(error))
        if isinstance(request, (SaveWork, UnlinkWork, AddDocument, AddWebPage, DismissWork, RestoreWork)):
            self.show(self.store.read(), "Saved. Connections update automatically from observed source changes.")
            self.wake.set()
        if isinstance(request, DismissWork) and isinstance(response, WorkSaved) and self.dismissed is not None:
            self.dismissed(response.work)
        return response

    def context(self, query: str) -> str:
        page = self.store.handle(ListWork(query=query, limit=20), self.clock())
        match page:
            case WorkSaved() | WorkRefused() | DocumentAdded():
                return ""
            case _:
                from_page = PERSONAL_RESPONSE.dump_json(page).decode()
                return "Personal ongoing work and its observed source connections:\n" + from_page[:24000]

    def tick(self) -> None:
        while not self.closed.is_set():
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            response = self.handle(command, origin=SourceOrigin.USER)
            if isinstance(response, WorkRefused):
                self.show(self.store.read(), response.error)
        with self.lock:
            force = self._state.get().force
            self._state.set(replace(self._state.get(), force=False))
        if force:
            self.sources.refresh()
            with self.lock:
                self._state.set(replace(self._state.get(), reviewed=None))
        observations = self.sources.read(self.clock(), self.closed)
        if self.closed.is_set():
            return
        catalog = self.store.observe(observations.sources)
        coverage = " · ".join(name.capitalize() for name in observations.coverage)
        status = (
            "Observed " + coverage + ". Coverage follows rendered pages and current filters."
            if coverage
            else "Open signed-in Teams, Outlook and Kanban pages to connect your work."
        )
        if observations.problems:
            status += " " + " ".join(observations.problems)
        self.show(catalog, status)
        current = signature(catalog)
        if not catalog.sources or current == self._state.get().reviewed:
            return
        if self.model is None:
            self.show(catalog, status + " Configure the agent model to connect sources automatically.")
            return
        self.show(catalog, "Connecting related sources to your work… " + status)
        request = correlation_input(catalog)
        try:
            plan = self.model(request, self.closed)
            if self.closed.is_set():
                return
            catalog = self.store.reconcile(request, plan, self.clock())
            reviewed = signature(catalog)
            with self.lock:
                self._state.set(replace(self._state.get(), reviewed=reviewed))
            self.show(catalog, "Work and source connections updated automatically. " + status)
        except Exception:
            # The next bounded observation can retry; failed reviews never
            # erase saved work or accept part of an invalid model plan.
            self.show(self.store.read(), "Connections could not be updated on this review. Saved work remains. " + status)

    def run(self) -> None:
        try:
            while not self.closed.is_set():
                self.wake.clear()
                try:
                    self.tick()
                except OSError, ValueError:
                    self.show(self.snapshot().catalog, "My work could not refresh. Saved work remains available.")
                # Canvas intake wakes at publication; regular sampling bounds
                # arrival latency for evidence visible in the signed-in browser.
                self.wake.wait(15)
        finally:
            self.sources.close()

    def close(self) -> None:
        self.closed.set()
        self.wake.set()
        if self._started.is_set():
            if not self._finished.wait(20):
                raise OSError("Personal work did not stop cleanly.")
        else:
            self.sources.close()
