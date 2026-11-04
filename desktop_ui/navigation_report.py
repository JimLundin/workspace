"""The navigation report: what the navigation log says navigation costs, and which
single change to the declared layouts would have cost least.

Every function is pure. `scripts/navigation_report.py` reads the log files and
prints the text; docs/window-placement.md explains the cost table and how to read
the suggestions. The report only proposes; nothing here changes a layout.
"""

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import combinations, islice
from typing import Final, assert_never

from pydantic import ValidationError

import protocol
from desktop_ui.navigation import identity, launcher
from desktop_ui.navigation_log import ENTRY, Cause, Entry, app_name, setup_name
from desktop_ui.shell_items import PinnedApp
from desktop_ui.window_layout import (
    BOTTOM_HALF,
    CODE,
    EDGE,
    FULL,
    LAYOUTS,
    LEFT_HALF,
    LEFT_TWO_THIRDS,
    RIGHT_HALF,
    RIGHT_THIRD,
    TERMINAL,
    TOP_HALF,
    App,
    Position,
    Program,
    Region,
    Role,
    Setup,
)
from miryoku.firmware import CHORDS

EFFORT: Final[frozendict[Cause, int]] = frozendict({"key": 1, "pager": 4, "scroll": 4, "toolbar": 4, "alt_tab": 3, "mouse": 4, "other": 0})
"""What one navigation costs by its cause; `other` is a program taking focus, not the user's effort."""
DESKTOP_SWITCH: Final = 1
"""Added to an effortful navigation that lands on another desktop."""
AWAY_MS: Final = 4 * 60 * 60 * 1000
"""A window in front longer than this was away time, so its entry is left out of the per-hour rates."""
TOP_PAIRS: Final = 10
TOP_SUGGESTIONS: Final = 5
UNKNOWN: Final = "(unknown)"
WITHOUT_CHORD: Final[tuple[Cause, ...]] = ("mouse", "alt_tab", "pager", "toolbar", "scroll")
"""The causes of a navigation the user made without a chord."""


def chorded(requests: Iterable[protocol.Request]) -> Iterator[str]:
    """The logged names of the apps an app chord goes to."""
    for request in requests:
        match request:
            case protocol.App(target=target):
                name = app_name(identity(launcher(target)))
                if name is not None:
                    yield name
            case protocol.Tool():
                pass
            case _:
                assert_never(request)


CHORDED: Final = frozenset(chorded(CHORDS))


@dataclass(frozen=True, slots=True)
class Log:
    entries: tuple[Entry, ...]
    malformed: int
    """Lines that weren't one entry of the documented schema with a local time and offset."""


def read(lines: Iterable[str]) -> Log:
    def parsed(line: str) -> Entry | None:
        try:
            entry = ENTRY.validate_json(line)
        except ValidationError:
            return None
        return entry if entry.time.utcoffset() is not None else None

    results = tuple(parsed(line) for line in lines if line.strip())
    entries = tuple(entry for entry in results if entry is not None)
    return Log(entries, len(results) - len(entries))


def selected(entries: Iterable[Entry], since: datetime, setup: Setup | None) -> tuple[Entry, ...]:
    """Entries from `since` on; only `setup`'s when one is given."""
    return tuple(entry for entry in entries if entry.time >= since and (setup is None or entry.setup == setup_name(setup)))


def charge(cause: Cause, *, crossed: bool) -> int:
    effort = EFFORT[cause]
    return effort + DESKTOP_SWITCH if effort and crossed else effort


def cost(entry: Entry) -> int:
    """The logged navigation's cost, by its own cause and desktops."""
    return charge(entry.cause, crossed=entry.other_desktop)


def wasted(entry: Entry) -> bool:
    """A chord that moved nothing; a zoom or a cycle between one app's windows keeps the same app on purpose."""
    return (
        entry.cause == "key" and entry.kind not in {"zoom", "cycle_app"} and entry.from_app == entry.to_app and entry.from_desktop == entry.to_desktop
    )


def away(entry: Entry) -> bool:
    return entry.dwell_ms is not None and entry.dwell_ms > AWAY_MS


@dataclass(frozen=True, slots=True)
class Totals:
    navigations: int
    hours: float
    """Time in front summed over the counted entries' previous windows."""
    cost: int
    causes: frozendict[Cause, int]
    switches: int
    wasted: int
    away: int
    """Entries left out of the rates as away time."""


def totals(entries: Sequence[Entry]) -> Totals:
    present = tuple(entry for entry in entries if not away(entry))
    return Totals(
        len(present),
        sum(entry.dwell_ms or 0 for entry in present) / 3_600_000,
        sum(cost(entry) for entry in present),
        frozendict(Counter(entry.cause for entry in present)),
        sum(entry.other_desktop for entry in present),
        sum(wasted(entry) for entry in present),
        len(entries) - len(present),
    )


@dataclass(frozen=True, slots=True)
class Pair:
    """Navigations between two apps, both ways."""

    apps: tuple[str, str]
    count: int
    cost: int
    crossed: int


def label(app: str | None) -> str:
    return UNKNOWN if app is None else app


def costliest(pair: Pair) -> tuple[int, int, tuple[str, str]]:
    return -pair.cost, -pair.count, pair.apps


def pairs(entries: Iterable[Entry]) -> tuple[Pair, ...]:
    """Round trips by combined cost, highest first; a navigation within one app isn't a pair."""
    moves = tuple((tuple(sorted((label(entry.from_app), label(entry.to_app)))), entry) for entry in entries if entry.from_app != entry.to_app)

    def pair(key: tuple[str, ...]) -> Pair:
        both = tuple(entry for other, entry in moves if other == key)
        return Pair((key[0], key[1]), len(both), sum(cost(entry) for entry in both), sum(entry.other_desktop for entry in both))

    found = (pair(key) for key in frozenset(key for key, _ in moves))
    return tuple(sorted(found, key=costliest))


@dataclass(frozen=True, slots=True)
class HotSpot:
    """An app the user reached without a chord, by how."""

    app: str
    causes: frozendict[Cause, int]
    total: int


def commonest(spot: HotSpot) -> tuple[int, str]:
    return -spot.total, spot.app


def by_count(causes: Mapping[Cause, int]) -> tuple[tuple[Cause, int], ...]:
    def order(item: tuple[Cause, int]) -> tuple[int, str]:
        return -item[1], item[0]

    return tuple(sorted(causes.items(), key=order))


def hot_spots(entries: Iterable[Entry]) -> tuple[HotSpot, ...]:
    reached: Counter[tuple[str, Cause]] = Counter((label(entry.to_app), entry.cause) for entry in entries if entry.cause in WITHOUT_CHORD)

    def spot(app: str) -> HotSpot:
        causes: frozendict[Cause, int] = frozendict({cause: count for (target, cause), count in reached.items() if target == app})
        return HotSpot(app, causes, sum(causes.values()))

    found = (spot(app) for app in frozenset(app for app, _ in reached))
    return tuple(sorted(found, key=commonest))


@dataclass(frozen=True, slots=True)
class History:
    """One setup's logged navigations, replayed against candidate layouts."""

    entries: tuple[Entry, ...]
    chorded: frozenset[str]
    """Apps a chord would have reached; replay assumes the chord for them."""


def replayed(history: History, layout: Mapping[App, Position]) -> int:
    """The history's cost had the layout placed its apps.

    A declared app is on its layout desktop; any other app on the desktop it was
    logged on. Each navigation's desktop switch is re-derived from those desktops.
    """
    desktops = frozendict({app_name(app): position.desktop for app, position in layout.items()})

    def desktop(app: str | None, logged: int | None) -> int | None:
        return desktops.get(app, logged) if app is not None else logged

    def replay(entry: Entry) -> int:
        start, end = desktop(entry.from_app, entry.from_desktop), desktop(entry.to_app, entry.to_desktop)
        crossed = start is not None and end is not None and start != end
        by = "key" if entry.cause != "other" and entry.to_app in history.chorded else entry.cause
        return charge(by, crossed=crossed)

    return sum(replay(entry) for entry in history.entries)


@dataclass(frozen=True, slots=True)
class Move:
    """One app to another desktop: its own role and region when they're free there, else a whole monitor nobody uses there."""

    app: App
    to: Position


@dataclass(frozen=True, slots=True)
class Swap:
    """Two apps exchange desktops, each keeping its role and region."""

    first: App
    second: App


@dataclass(frozen=True, slots=True)
class Exchange:
    """Two apps exchange their whole positions, when swapping desktops alone would overlap."""

    first: App
    second: App


type Change = Move | Swap | Exchange


def changed(layout: Mapping[App, Position], change: Change) -> frozendict[App, Position]:
    match change:
        case Move(app=app, to=to):
            return frozendict({**layout, app: to})
        case Swap(first=first, second=second):
            a, b = layout[first], layout[second]
            return frozendict({**layout, first: replace(a, desktop=b.desktop), second: replace(b, desktop=a.desktop)})
        case Exchange(first=first, second=second):
            return frozendict({**layout, first: layout[second], second: layout[first]})
        case _:
            assert_never(change)


def overlapping(layout: Mapping[App, Position]) -> bool:
    """Placement's rule: two apps on one desktop and monitor must not share any area."""

    def meet(a: Region, b: Region) -> bool:
        return a.left < b.left + b.width and b.left < a.left + a.width and a.top < b.top + b.height and b.top < a.top + a.height

    return any(a.desktop == b.desktop and a.role == b.role and meet(a.region, b.region) for a, b in combinations(layout.values(), 2))


def moves(layout: Mapping[App, Position], app: App, desktop: int) -> Iterator[Move]:
    """The app on `desktop` at its own role and region, or else full screen on the first monitor unused there."""
    kept = Move(app, replace(layout[app], desktop=desktop))
    if not overlapping(changed(layout, kept)):
        yield kept
        return
    used = frozenset(position.role for other, position in layout.items() if other != app and position.desktop == desktop)
    roles = (role for role in Role if role not in used and any(position.role == role for position in layout.values()))
    yield from (Move(app, Position(desktop, role, FULL)) for role in islice(roles, 1))


def changes(layout: Mapping[App, Position]) -> Iterator[Change]:
    """Every move of one app to another declared desktop, then every swap of two apps on different desktops.

    Moving an app onto the desktop of the app it alternates with most is one of the moves.
    """
    desktops = range(1 + max((position.desktop for position in layout.values()), default=-1))
    for app, position in layout.items():
        for desktop in desktops:
            if desktop != position.desktop:
                yield from moves(layout, app, desktop)
    for (first, a), (second, b) in combinations(layout.items(), 2):
        if a.desktop != b.desktop:
            swap = Swap(first, second)
            yield Exchange(first, second) if overlapping(changed(layout, swap)) else swap


@dataclass(frozen=True, slots=True)
class Suggestion:
    change: Change
    before: int
    after: int


def suggested(history: History, layout: Mapping[App, Position], change: Change) -> Suggestion | None:
    """The change's replayed cost against the layout's; None when it would overlap two apps."""
    candidate = changed(layout, change)
    if overlapping(candidate):
        return None
    return Suggestion(change, replayed(history, layout), replayed(history, candidate))


def most_saved(suggestion: Suggestion) -> int:
    return suggestion.after - suggestion.before


def suggestions(history: History, layout: Mapping[App, Position]) -> tuple[Suggestion, ...]:
    """The changes that would have saved most, at most `TOP_SUGGESTIONS`."""
    found = (suggestion for change in changes(layout) if (suggestion := suggested(history, layout, change)) is not None)
    saving = sorted((suggestion for suggestion in found if suggestion.after < suggestion.before), key=most_saved)
    return tuple(saving[:TOP_SUGGESTIONS])


REGION_NAMES: Final[frozendict[Region, str]] = frozendict(
    {
        FULL: "FULL",
        LEFT_HALF: "LEFT_HALF",
        RIGHT_HALF: "RIGHT_HALF",
        TOP_HALF: "TOP_HALF",
        BOTTOM_HALF: "BOTTOM_HALF",
        LEFT_TWO_THIRDS: "LEFT_TWO_THIRDS",
        RIGHT_THIRD: "RIGHT_THIRD",
    }
)
PROGRAM_NAMES: Final[frozendict[App, str]] = frozendict({TERMINAL: "TERMINAL", CODE: "CODE", EDGE: "EDGE"})


def source(app: App) -> str:
    """The app as `LAYOUTS` spells it."""
    match app:
        case PinnedApp():
            return f"PinnedApp.{app.name}"
        case Program(exe=exe):
            return PROGRAM_NAMES.get(app, f'Program("{exe}")')
        case _:
            assert_never(app)


def position(where: Position) -> str:
    region = REGION_NAMES.get(where.region, repr(where.region))
    return f"Position({where.desktop}, Role.{where.role.name}, {region})"


def edits(setup: Setup, layout: Mapping[App, Position], change: Change) -> Iterator[str]:
    """The exact `LAYOUTS` lines the change rewrites."""
    candidate = changed(layout, change)
    match change:
        case Move(app=app):
            moved: tuple[App, ...] = (app,)
        case Swap(first=first, second=second) | Exchange(first=first, second=second):
            moved = (first, second)
        case _:
            assert_never(change)
    for app in moved:
        yield f"LAYOUTS[Setup.{setup.name}][{source(app)}]: {position(layout[app])} -> {position(candidate[app])}"


def describe(change: Change, layout: Mapping[App, Position]) -> str:
    match change:
        case Move(app=app, to=to):
            return f"Move {label(app_name(app))} from desktop {layout[app].desktop + 1} to desktop {to.desktop + 1}"
        case Swap(first=first, second=second):
            return f"Swap the desktops of {label(app_name(first))} and {label(app_name(second))}"
        case Exchange(first=first, second=second):
            return f"Exchange the places of {label(app_name(first))} and {label(app_name(second))}"
        case _:
            assert_never(change)


def days(entries: Iterable[Entry]) -> int:
    """The calendar days the entries were logged on."""
    return len({entry.time.date() for entry in entries})


def share(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "-"


def rate(amount: int, hours: float) -> str:
    return f"{amount / hours:.1f}" if hours else "-"


def setup_title(setup: Setup | None) -> str:
    return setup_name(setup) or "unknown setup"


def totals_lines(setup: Setup | None, entries: Sequence[Entry]) -> Iterator[str]:
    total = totals(entries)
    yield f"  {setup_title(setup)}: {total.navigations} navigations over {total.hours:.1f} h in front"
    yield f"    {rate(total.navigations, total.hours)} navigations/h, cost {total.cost} ({rate(total.cost, total.hours)}/h)"
    causes = ", ".join(f"{cause} {count} ({share(count, total.navigations)})" for cause, count in by_count(total.causes))
    yield f"    by cause: {causes or 'none'}"
    yield f"    desktop switches {total.switches}, chords that moved nothing {total.wasted}, away entries left out {total.away}"


def pair_lines(entries: Iterable[Entry]) -> Iterator[str]:
    found = pairs(entries)[:TOP_PAIRS]
    if not found:
        yield "    none"
    for pair in found:
        yield f"    {pair.apps[0]} <-> {pair.apps[1]}: cost {pair.cost}, {pair.count} times, {pair.crossed} across desktops"


def hot_spot_lines(entries: Iterable[Entry]) -> Iterator[str]:
    found = hot_spots(entries)
    if not found:
        yield "    none"
    for spot in found:
        causes = ", ".join(f"{cause} {count}" for cause, count in by_count(spot.causes))
        yield f"    {spot.app}: {spot.total} ({causes})"


def suggestion_lines(setup: Setup, history: History) -> Iterator[str]:
    layout = LAYOUTS[setup]
    found = suggestions(history, layout)
    if not found:
        yield "    No single move or swap would have cost less."
    logged_days = max(days(history.entries), 1)
    for rank, suggestion in enumerate(found, 1):
        saving = suggestion.before - suggestion.after
        yield (
            f"    {rank}. {describe(suggestion.change, layout)}: cost {suggestion.before} -> {suggestion.after}, "
            f"saving {saving} ({saving / logged_days:.1f}/day over {logged_days} logged day(s))"
        )
        yield from (f"       {edit}" for edit in edits(setup, layout, suggestion.change))


def report(log: Log, chords: frozenset[str]) -> str:
    """The report of the log's entries, already selected, as terminal text."""
    order: tuple[Setup | None, ...] = (*Setup, None)
    by_setup = tuple((setup, entries) for setup in order if (entries := tuple(entry for entry in log.entries if entry.setup == setup_name(setup))))

    def sections() -> Iterator[str]:
        yield f"{len(log.entries)} entries; {log.malformed} malformed lines skipped."
        yield f"Rates leave out entries whose previous window was in front over {AWAY_MS // 3_600_000} h: that is away time."
        yield "Unknown apps are shown as (unknown)."
        if not by_setup:
            return
        yield ""
        yield "1. Totals per setup"
        for name, entries in by_setup:
            yield from totals_lines(name, entries)
        yield ""
        yield "2. Top app pairs by round-trip cost"
        for name, entries in by_setup:
            yield f"  {setup_title(name)}:"
            yield from pair_lines(entries)
        yield ""
        yield "3. Apps reached without a chord: hint or binding gaps"
        for name, entries in by_setup:
            yield f"  {setup_title(name)}:"
            yield from hot_spot_lines(entries)
        yield ""
        yield "4. Suggested layout changes"
        yield "  Replay assumes a chord for every target app that has one and keeps the logged cause otherwise,"
        yield "  so its cost can be lower than the logged cost above. A moved app keeps its role and region"
        yield "  unless they're taken on the new desktop; a change that would overlap two apps is skipped."
        for name, entries in by_setup:
            if name is not None:
                yield f"  {setup_title(name)}:"
                yield from suggestion_lines(name, History(entries, chords))

    return "\n".join(sections()) + "\n"
