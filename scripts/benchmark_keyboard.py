"""Measure the keyboard engine with synthetic input and GC enabled; never send keys.

Run with the same interpreter before and after a keyboard change. Use --root to
select a saved source tree. Native hook/SendInput latency and OS scheduling need
separate desktop measurements; this measures Engine.on_key and tap-hold timers.
"""

import argparse
import gc
import hashlib
import inspect
import json
import statistics
import sys
import tracemalloc
from array import array
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns

lazy from keyboard.engine import Engine, EngineState, Indicator, Signal
lazy from keyboard.layout import Key, Mod, Scancode
lazy from protocol import Request


@dataclass(frozen=True, slots=True)
class Options:
    root: Path = Path(__file__).resolve().parent.parent
    events: int = 100_000
    rounds: int = 5
    output: Path | None = None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--events", type=int, default=100_000)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parsed = dict(inspect.getmembers(parser.parse_args()))
    match parsed:
        case {"root": Path() as source_root, "events": int() as events, "rounds": int() as repetitions, "output": (Path() | None) as output}:
            options = Options(source_root, events, repetitions, output)
        case _:
            parser.error("Invalid benchmark arguments.")
    root = options.root.resolve()
    count, rounds = options.events, options.rounds
    if count < 1000 or rounds < 1:
        parser.error("Use at least 1000 events and one round.")
    sys.path.insert(0, str(root))
    run(root, count, rounds, options.output)


def run(root: Path, count: int, rounds: int, output: Path | None) -> None:
    # Lazy dependencies first resolve after main selects the source tree.

    # Plain typing, home-row rolls, modifiers, layers, repeat, voice, and timers.
    # Zero is a timer callback; other values are physical keyboard scancodes.
    pattern = (
        (0x05, True),
        (0x05, False),
        (0x14, True),
        (0x14, False),
        (0x13, True),
        (0x17, True),
        (0x13, False),
        (0x17, False),
        (0x13, True),
        (0x09, True),
        (0x09, False),
        (0x13, False),
        (0x2F, True),
        (0, False),
        (0x26, True),
        (0x26, False),
        (0x2F, False),
        (0x05, True),
        (0x05, True),
        (0x05, True),
        (0x05, False),
        (0x30, True),
        (0x30, False),
        (0x31, True),
        (0x31, False),
        (0x13, True),
        (0, False),
        (0x13, False),
        (0x39, True),
        (0x39, False),
    )
    events = tuple((Scancode(key), down, index * 20) for index in range(count) for key, down in (pattern[index % len(pattern)],))
    host = Host()
    measurements, collections, pauses = measure_latencies(host, events, rounds)
    engine = Engine()
    gc.collect()
    tracemalloc.start()
    try:
        play(engine, host, events)
        retained, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    names = (
        "keyboard/engine.py",
        "keyboard/layout.py",
        "keyboard/win.py",
        "keyboard/__main__.py",
        "keyboard.pyw",
        "protocol.py",
        "config.py",
        "components.py",
        "winapi/inputs.py",
        "winapi/windows.py",
        "winapi/_core.py",
    )
    report = {
        "python": sys.version,
        "root": str(root),
        "events_per_round": count,
        "rounds": rounds,
        "gc_enabled": gc.isenabled(),
        "assistant_imported": any(name == "assistant" or name.startswith("assistant.") for name in sys.modules),
        "latency_rounds": measurements,
        "median": {name: statistics.median(row[name] for row in measurements) for name in measurements[0]},
        "gc_collections_during_latency": len(collections),
        "gc_generations": collections,
        "longest_observed_gc_us": max(pauses, default=0) / 1000,
        "traced_peak_bytes": peak,
        "traced_retained_bytes": retained,
        "source": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names},
        "scope": "Synthetic engine events; no native input, capture, or agent work. Traced peak is live memory, not total allocation churn.",
    }
    rendered = json.dumps(report, indent=2)
    if output is not None:
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


def percentile(values: Sequence[int], fraction: float) -> float:
    return values[min(len(values) - 1, int(len(values) * fraction))] / 1000


@dataclass(frozen=True, slots=True)
class Host:
    """No output log or OS calls whose allocations could obscure the engine."""

    def send(self, key: Key | Mod, *, down: object) -> None:
        pass

    def start_timer(self) -> int:
        return 1

    def stop_timer(self, timer: int) -> None:
        pass

    def signal(self, signal: Signal) -> None:
        pass

    def request(self, request: Request, *, down: object) -> None:
        pass

    def type_text(self, text: str) -> None:
        pass

    def used(self, feature: str) -> None:
        pass

    def indicate(self, indicator: Indicator) -> None:
        pass


def measure_latencies(
    host: Host,
    events: Sequence[tuple[Scancode, bool, int]],
    rounds: int,
) -> tuple[tuple[frozendict[str, float], ...], tuple[int, ...], tuple[int, ...]]:
    collections: list[int] = []
    pauses: list[int] = []
    gc_started = 0

    def observe_gc(phase: str, info: dict[str, int]) -> None:
        nonlocal gc_started
        if phase == "start":
            gc_started = perf_counter_ns()
        else:
            pauses.append(perf_counter_ns() - gc_started)
            collections.append(info["generation"])

    gc.enable()
    # Warm up adaptive bytecode and tables before collecting latency samples.
    play(Engine(), host, events[:1000])
    measurements = tuple(round_latencies(host, events, rounds, observe_gc))
    return measurements, tuple(collections), tuple(pauses)


def round_latencies(
    host: Host,
    events: Sequence[tuple[Scancode, bool, int]],
    rounds: int,
    observe_gc: Callable[[str, dict[str, int]], None],
) -> Iterator[frozendict[str, float]]:
    """Each round's latency percentiles, measured on a fresh engine with observe_gc watching collections."""
    # One preallocated buffer, written in place, so the timed loop never allocates a sample.
    latencies = array("Q", [0]) * len(events)
    for _ in range(rounds):
        engine, state = Engine(), EngineState()
        gc.collect()
        gc.callbacks.append(observe_gc)
        try:
            for index, (key, down, now) in enumerate(events):
                started = perf_counter_ns()
                if key:
                    state, _ = engine.on_key(state, host, key, down=down, now=now)
                else:
                    state = engine.timeout(state, host, 1)
                latencies[index] = perf_counter_ns() - started
        finally:
            gc.callbacks.remove(observe_gc)
        values = sorted(latencies)
        yield frozendict(
            {
                "p50_us": percentile(values, 0.5),
                "p95_us": percentile(values, 0.95),
                "p99_us": percentile(values, 0.99),
                "p999_us": percentile(values, 0.999),
                "max_us": max(values) / 1000,
            }
        )


def play(engine: Engine, host: Host, events: Sequence[tuple[Scancode, bool, int]]) -> EngineState:
    """The engine's state after `events`, from a fresh start."""
    state = EngineState()
    for key, down, now in events:
        if key:
            state, _ = engine.on_key(state, host, key, down=down, now=now)
        else:
            state = engine.timeout(state, host, 1)
    return state


if __name__ == "__main__":
    main()
