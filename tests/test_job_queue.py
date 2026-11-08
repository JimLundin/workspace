"""Queued UI work yields frames, keeps its order and never runs one job inside another."""

import queue
import threading
from collections.abc import Callable

from desktop_ui import job_queue


def test_a_batch_yields_once_its_frame_budget_is_spent_and_keeps_fifo_order() -> None:
    # Defect: a count-only limit runs dozens of individually short jobs back to
    # back, blocking animation and input; or yielding drops or repeats work.
    now = 0.0
    delivered: list[int] = []
    jobs: queue.Queue[int] = queue.Queue()
    for index in range(24):
        jobs.put(index)

    def run(index: int) -> None:
        nonlocal now
        now += 0.002  # each job, like a local storage read, takes 2 ms
        delivered.append(index)

    busy = threading.Event()
    job_queue.drain(jobs, run, busy, clock=lambda: now)
    assert delivered == [0, 1], "A queue batch ran past its quarter frame."
    while not jobs.empty():
        job_queue.drain(jobs, run, busy, clock=lambda: now)
    assert delivered == list(range(24)) and not busy.is_set()


def test_a_drain_reached_from_inside_a_job_runs_nothing() -> None:
    # Defect: a job pumps native events and a nested drain starts the next job
    # before the first finishes publishing its state.
    delivered: list[str] = []
    jobs: queue.Queue[Callable[[], None]] = queue.Queue()
    busy = threading.Event()

    def first() -> None:
        delivered.append("start")
        job_queue.drain(jobs, lambda job: job(), busy)
        delivered.append("finish")

    jobs.put(first)
    jobs.put(lambda: delivered.append("next"))
    job_queue.drain(jobs, lambda job: job(), busy)
    assert delivered == ["start", "finish", "next"]
