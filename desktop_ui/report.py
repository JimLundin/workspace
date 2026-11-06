"""The usage report: every feature, how often it was used, and which never were."""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from config import APPS, SNIPPETS
from miryoku.layout import TABLE, Command, Layer, Mod, describe
from protocol import Tool
from usage import DIRECTORY, USAGE_LOG


@dataclass(frozen=True, slots=True)
class Use:
    uses: int = 0
    failures: int = 0
    last: str = ""
    """When it was last used (ISO time)."""


@dataclass(frozen=True, slots=True)
class _Entry:
    """One usage log line: a single use (`feature`) or uses counted since the last line (`counts`)."""

    t: str
    source: str
    feature: str | None = None
    counts: Mapping[str, int] | None = None
    ok: bool | None = None


_ENTRY = TypeAdapter(_Entry)


def summarize(lines: Iterable[str], since: datetime | None = None) -> dict[str, Use]:
    """Uses per feature (`source/feature`). Lines that aren't log entries are skipped."""
    summary: dict[str, Use] = {}
    cutoff = since.isoformat() if since else ""
    for line in lines:
        try:
            entry = _ENTRY.validate_json(line)
        except ValidationError:
            continue
        if entry.t < cutoff:
            continue
        found: list[tuple[str, int]] = [(entry.feature, 1)] if entry.feature is not None else []
        if entry.counts is not None:
            found.extend(entry.counts.items())
        for name, count in found:
            key = f"{entry.source}/{name}"
            use = summary.get(key, Use())
            summary[key] = Use(use.uses + count, use.failures + (1 if entry.ok is False else 0), max(use.last, entry.t))
    return summary


def _most_used_first(item: tuple[str, Use]) -> tuple[int, str]:
    return -item[1].uses, item[0]


def report(summary: Mapping[str, Use], known: Iterable[str]) -> str:
    """A plain-text table, most used first, then the known features never used."""
    rows = sorted(summary.items(), key=_most_used_first)
    width = max((len(name) for name, _ in rows), default=10)
    lines = [f"{'Feature':<{width}}  {'Uses':>6}  {'Failed':>6}  Last used", ""]
    lines += [f"{name:<{width}}  {use.uses:>6}  {use.failures:>6}  {use.last.replace('T', ' ')}" for name, use in rows]
    unused = sorted(set(known) - set(summary))
    if unused:
        lines += ["", "Never used:", *(f"  {name}" for name in unused)]
    return "\n".join(lines) + "\n"


def known_features() -> Iterator[str]:
    """Everything either program can log, as `source/feature`."""
    yield from (f"assistant/{tool.name.lower()}" for tool in Tool if tool is not Tool.STOP)
    yield from (f"assistant/app:{app.name}" for app in APPS)
    yield from ("assistant/agent", "assistant/dark_when_away", "assistant/dark_when_away_toggle")
    for layer, actions in TABLE.items():
        if layer is not None:
            yield from sorted({f"layout/{layer.name.lower()}:{describe(a)}" for a in actions if a is not Command.NOTHING})
    yield from (f"layout/hold:{mod.name.lower()}" for mod in Mod)
    yield from (f"layout/layer:{layer.name.lower()}" for layer in Layer)
    yield from (f"layout/snippet:{trigger}" for trigger in SNIPPETS)
    yield from ("layout/caps_word", "layout/layer_lock", "layout/switch_off")


def write_report(days: int = 30) -> Path:
    """The report for the last `days` days, as a text file; its path."""
    lines = USAGE_LOG.read_text(encoding="utf-8").splitlines() if USAGE_LOG.exists() else []
    summary = summarize(lines, since=datetime.now() - timedelta(days=days))
    path = DIRECTORY / "usage report.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"Workspace usage, last {days} days\n\n" + report(summary, known_features()), encoding="utf-8")
    return path
