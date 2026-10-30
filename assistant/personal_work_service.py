"""Automatic personal-work collection with durable edits and bounded model reviews."""

import hashlib
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from assistant.personal_work_sources import Observations
from automation.personal_work import (
    CORRELATION_INPUT,
    PERSONAL_RESPONSE,
    AddDocument,
    AddWebPage,
    Catalog,
    CorrelationInput,
    DismissWork,
    DocumentAdded,
    ListWork,
    PersonalRequest,
    PersonalResponse,
    PersonalStore,
    PersonalView,
    RestoreWork,
    SaveWork,
    UnlinkWork,
    WorkPlan,
    WorkRefused,
    WorkSaved,
    WorkSource,
    WorkThread,
)


class Sources(Protocol):
    def read(self, at: float, cancel: threading.Event) -> Observations: ...
    def refresh(self) -> None: ...
    def close(self) -> None: ...


type Model = Callable[[CorrelationInput, threading.Event], WorkPlan]


def correlation_input(catalog: Catalog) -> CorrelationInput:
    # The latest sixty observations bound model input. Retained connections in
    # saved work remain visible even when their original page is no longer rendered.
    def order(source: WorkSource) -> tuple[float, str]:
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
    def identity(source: WorkSource) -> str:
        return source.id

    canonical = replace(
        request, catalog_revision=0, sources=tuple(replace(source, observed_at=0) for source in sorted(request.sources, key=identity))
    )
    return hashlib.sha256(CORRELATION_INPUT.dump_json(canonical)).hexdigest()


class PersonalWork:
    """The worker owns polling/queued UI writes; HTTP handlers own their own transactions.

    Locks, lifecycle flags, queue and last-reviewed signature are scheduling state
    local to this owner. The catalog, source observations and view stay immutable.
    """

    __slots__ = (
        "clock",
        "closed",
        "commands",
        "dismissed",
        "force",
        "lock",
        "model",
        "publish",
        "reviewed",
        "sources",
        "store",
        "thread",
        "view",
        "wake",
    )

    def __init__(
        self,
        store: PersonalStore,
        sources: Sources,
        publish: Callable[[PersonalView], None],
        *,
        model: Model | None = None,
        clock: Callable[[], float] = time.time,
        dismissed: Callable[[WorkThread], None] | None = None,
    ) -> None:
        # Store, source reader, UI publisher, model and clock have independent
        # effect ownership. Dismissal cancels bound research only after its
        # correction commits; the model can only return a typed connection plan.
        self.store, self.sources, self.publish, self.model, self.clock = store, sources, publish, model, clock
        self.lock = threading.RLock()
        self.closed, self.wake = threading.Event(), threading.Event()
        self.thread: threading.Thread | None = None
        self.commands: queue.Queue[SaveWork | UnlinkWork | AddDocument | AddWebPage | DismissWork | RestoreWork] = queue.Queue(maxsize=64)
        self.view = PersonalView(store.read())
        self.reviewed: str | None = None
        self.force = False
        self.dismissed: Callable[[WorkThread], None] | None = dismissed

    def snapshot(self) -> PersonalView:
        with self.lock:
            return self.view

    def show(self, catalog: Catalog, status: str) -> None:
        with self.lock:
            if catalog.revision < self.view.catalog.revision:
                return
            self.view = PersonalView(catalog, status)
            self.publish(self.view)

    def start(self) -> None:
        with self.lock:
            if self.thread is None:
                self.thread = threading.Thread(target=self.run, name="personal work", daemon=True)
                self.thread.start()

    def refresh(self) -> None:
        with self.lock:
            self.force = True
            self.wake.set()

    def enqueue(self, command: SaveWork | UnlinkWork | AddDocument | AddWebPage | DismissWork | RestoreWork) -> None:
        if self.closed.is_set():
            raise ValueError("My work is closing.")
        try:
            self.commands.put_nowait(command)
        except queue.Full as error:
            raise ValueError("My work is busy. Try this edit again.") from error
        self.wake.set()

    def handle(self, request: PersonalRequest) -> PersonalResponse:
        try:
            response = self.store.handle(request, self.clock())
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
            response = self.handle(command)
            if isinstance(response, WorkRefused):
                self.show(self.store.read(), response.error)
        with self.lock:
            force, self.force = self.force, False
        if force:
            self.sources.refresh()
            self.reviewed = None
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
        if not catalog.sources or current == self.reviewed:
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
            self.reviewed = signature(catalog)
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
                self.wake.wait(120)
        finally:
            self.sources.close()

    def close(self) -> None:
        self.closed.set()
        self.wake.set()
        thread = self.thread
        if thread is not None:
            thread.join(20)
            if thread.is_alive():
                raise OSError("Personal work did not stop cleanly.")
        else:
            self.sources.close()
