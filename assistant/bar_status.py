"""System indicators are observed off the UI thread, with one bounded result slot."""

import queue
import threading
from contextlib import suppress

from assistant.ambient import SystemStatus
lazy from winapi.system_status import speakers, wifi


class StatusObserver:
    __slots__ = ("cancelled", "results", "worker")

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self.results: queue.Queue[SystemStatus] = queue.Queue(maxsize=1)
        self.worker = threading.Thread(target=self.run, name="toolbar system status", daemon=True)
        self.worker.start()

    def run(self) -> None:

        while not self.cancelled.is_set():
            observed = SystemStatus(speakers(), wifi())
            with suppress(queue.Empty):
                self.results.get_nowait()
            self.results.put_nowait(observed)
            self.cancelled.wait(1)

    def close(self) -> None:
        self.cancelled.set()
        self.worker.join(timeout=0.1)
