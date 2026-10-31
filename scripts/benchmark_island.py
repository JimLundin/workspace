r"""Measure the island bar's frames on the real Qt window and glass scene; never sends input.

Drives the bar through rest, agent work with a transcription, dictation with
both and a recording and inbox beside it, a waiting question, and rest again, stepping 16 ms frames on a
controlled clock. Each frame's work includes the owner's frame, Qt's paint and
the glass publication. Reports frame-work percentiles, allocation per frame
(tracemalloc, GC enabled) and whether the frame loop stops at rest. Run from the
repository root on the desktop the bar would use:

    .venv\Scripts\python.exe -m scripts.benchmark_island --output island.json
"""

import argparse
import inspect
import statistics
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns

from pydantic import TypeAdapter
lazy from PySide6 import QtCore

from runtime import activate
lazy from assistant.desktop_bar import BarActions, BarObservations, DesktopBar
lazy from assistant.island_model import Agent, Job
lazy from assistant.qt_ui import application
lazy from assistant.recording_state import RecordingState
lazy from winapi import appearance

FRAME = 1 / 60


@dataclass(frozen=True, slots=True)
class Result:
    frames: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    allocated_kb_p95: float
    loop_stopped_at_rest: bool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--output", type=Path)
    match dict(inspect.getmembers(parser.parse_args())):
        case {"rounds": int() as rounds, "output": (Path() | None) as output} if rounds >= 1:
            activate()
            result = run(rounds)
        case _:
            parser.error("Use at least one round.")
    print(f"{result.frames} frames: p50 {result.p50_ms:.2f} ms, p95 {result.p95_ms:.2f} ms, max {result.max_ms:.2f} ms")
    print(f"allocated per frame (p95): {result.allocated_kb_p95:.1f} KB; loop stopped at rest: {result.loop_stopped_at_rest}")
    if output is not None:
        output.write_bytes(TypeAdapter(Result).dump_json(result, indent=2))


def transitions(bar: DesktopBar) -> tuple[Callable[[], None], ...]:
    """Agent work with a transcription, dictation beside both, a question, and rest."""

    def work() -> None:
        bar.agent_changed(Agent("Comparing both sheets", waiting=False))
        bar.job_changed(Job.TRANSCRIBING)

    def dictate() -> None:
        bar.recording_changed(RecordingState(phase="recording", seconds=125))
        bar.inbox_changed(3)
        bar.dictation(active=True)

    def ask() -> None:
        bar.dictation(active=False)
        bar.job_changed(None)
        bar.agent_changed(Agent("Which sheet should the reply cover?", waiting=True))

    def rest() -> None:
        bar.recording_changed(RecordingState())
        bar.inbox_changed(0)
        bar.agent_changed(None)

    return (work, dictate, ask, rest)


def run(rounds: int) -> Result:
    app = application()
    now = [1000.0]

    def inert(*_: object) -> None:
        return None

    actions = BarActions(inert, inert, inert, inert, inert, inert, inert, inert, inbox=inert)
    observations = BarObservations(clock=lambda: now[0], motion=lambda: True, material=lambda: appearance.Material.GLASS)
    bar = DesktopBar(actions, native_shell=False, observations=observations)
    bar.timer.stop()  # The benchmark owns every frame.
    bar.visible = True
    bar.render()
    app.processEvents()

    steps = transitions(bar)
    durations: tuple[float, ...] = ()
    allocations: tuple[float, ...] = ()
    try:
        # Time one pass untraced: tracing allocations slows Python itself. Then trace a pass.
        for traced in (False, True):
            if traced:
                tracemalloc.start()
            for _ in range(rounds):
                for step in steps:
                    step()
                    for _ in range(90):  # 1.5 s: every transition settles within it.
                        now[0] += FRAME
                        if traced:
                            tracemalloc.reset_peak()
                            before = tracemalloc.get_traced_memory()[0]
                            bar.paint_frames()
                            app.processEvents()
                            allocations = (*allocations, max(0, tracemalloc.get_traced_memory()[1] - before) / 1024)
                        else:
                            started = perf_counter_ns()
                            bar.paint_frames()
                            app.processEvents()
                            durations = (*durations, (perf_counter_ns() - started) / 1e6)
        stopped = not bar.loop.timer.isActive()
    finally:
        tracemalloc.stop()
        bar.close()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        app.processEvents()
    ranked = sorted(durations)
    return Result(
        len(ranked),
        statistics.median(ranked),
        ranked[int(len(ranked) * 0.95)],
        ranked[-1],
        sorted(allocations)[int(len(allocations) * 0.95)],
        stopped,
    )


if __name__ == "__main__":
    main()
