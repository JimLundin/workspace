"""Spread visible tiles when display geometry changes; preserve manual placement between changes."""

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, assert_never, cast
from uuid import UUID

from assistant.tiling import GlazeWM

type Direction = Literal['horizontal', 'vertical']


@dataclass(frozen=True, slots=True)
class Tile:
    identity: str
    focused: bool


@dataclass(frozen=True, slots=True)
class Display:
    identity: str
    x: int
    y: int
    width: int
    height: int
    scale: float
    workspace: str
    workspace_id: str
    direction: Direction
    tiles: tuple[Tile, ...]

    @property
    def area(self) -> float:
        return self.width * self.height / (self.scale * self.scale)


@dataclass(frozen=True, slots=True)
class MoveTile:
    identity: str
    workspace: str


@dataclass(frozen=True, slots=True)
class OrientWorkspace:
    identity: str
    direction: Direction


type Operation = MoveTile | OrientWorkspace


def object_fields(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise OSError('Invalid monitor layout returned by GlazeWM.')
    return cast(dict[str, object], value)


def identity(value: object) -> str:
    if not isinstance(value, str):
        raise OSError('Invalid tiling identity.')
    try:
        return str(UUID(value))
    except ValueError as error:
        raise OSError('Invalid tiling identity.') from error


def number(row: dict[str, object], field: str) -> int:
    value = row.get(field)
    if type(value) is not int:
        raise OSError('Invalid monitor geometry.')
    return value


def children(row: dict[str, object]) -> tuple[dict[str, object], ...]:
    values = row.get('children')
    if not isinstance(values, list) or len(cast(list[object], values)) > 4096:
        raise OSError('Invalid tiling tree.')
    return tuple(object_fields(value) for value in cast(list[object], values))


def tiles(row: dict[str, object], depth: int = 0) -> tuple[Tile, ...]:
    if depth > 32:
        raise OSError('The tiling tree is too deep.')
    found: list[Tile] = []
    for node in children(row):
        if node.get('type') == 'window':
            if object_fields(node.get('state')).get('type') == 'tiling' and node.get('displayState') == 'shown' and node.get('activeDrag') is None:
                found.append(Tile(identity(node.get('id')), node.get('hasFocus') is True))
        else:
            found.extend(tiles(node, depth + 1))
    return tuple(found)


def displays(data: object) -> tuple[Display, ...]:
    rows = object_fields(data).get('monitors')
    if not isinstance(rows, list) or len(cast(list[object], rows)) > 64:
        raise OSError('Invalid monitor list.')
    found: list[Display] = []
    for value in cast(list[object], rows):
        row = object_fields(value)
        workspace = next((node for node in children(row) if node.get('isDisplayed') is True), None)
        if workspace is None:
            continue
        name, direction, scale = workspace.get('name'), workspace.get('tilingDirection'), row.get('scaleFactor')
        if not isinstance(name, str) or not name or direction not in ('horizontal', 'vertical'):
            raise OSError('Invalid displayed workspace.')
        if type(scale) not in (float, int) or not math.isfinite(cast(float, scale)) or cast(float, scale) <= 0:
            raise OSError('Invalid monitor scale.')
        width, height = number(row, 'width'), number(row, 'height')
        if width <= 0 or height <= 0:
            raise OSError('Invalid monitor geometry.')
        found.append(Display(identity(row.get('id')), number(row, 'x'), number(row, 'y'), width, height,
                             float(cast(float, scale)), name, identity(workspace.get('id')), direction, tiles(workspace)))
    def order(display: Display) -> tuple[int, int]:
        return display.x, display.y
    return tuple(sorted(found, key=order))


def plan(layout: tuple[Display, ...]) -> tuple[Operation, ...]:
    """Allocate readable space proportionally, moving excess tiles and retaining focus."""
    if not layout:
        return ()
    quotas = [0] * len(layout)
    total = sum(len(display.tiles) for display in layout)
    for _ in range(total):
        available = [index for index, count in enumerate(quotas) if count == 0]
        choices = available or list(range(len(layout)))
        def priority(index: int) -> tuple[float, int, int]:
            return layout[index].area / (quotas[index] + 1), len(layout[index].tiles), -index
        target = max(choices, key=priority)
        quotas[target] += 1
    operations: list[Operation] = []
    excess: list[Tile] = []
    for index, display in enumerate(layout):
        desired: Direction = 'vertical' if display.height > display.width else 'horizontal'
        if desired != display.direction:
            operations.append(OrientWorkspace(display.workspace_id, desired))
        def focus_order(tile: Tile) -> bool:
            return not tile.focused
        ordered = sorted(display.tiles, key=focus_order)
        excess.extend(ordered[quotas[index]:])
    for index, display in enumerate(layout):
        for _ in range(max(0, quotas[index] - len(display.tiles))):
            tile = excess.pop()
            operations.append(MoveTile(tile.identity, display.workspace))
    return tuple(operations)


class MonitorLayout:
    __slots__ = ('manager', 'problem', 'signature', 'stopped', 'thread')

    def __init__(self, manager: GlazeWM, problem: Callable[[str], None]) -> None:
        self.manager, self.problem = manager, problem
        self.stopped = threading.Event()
        self.signature: tuple[tuple[str, int, int, int, int, float], ...] | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is None and not self.stopped.is_set():
            self.thread = threading.Thread(target=self.initialize, name="window tiling", daemon=True)
            self.thread.start()

    def initialize(self) -> None:
        try:
            self.manager.start()
        except OSError as error:
            self.problem(str(error))
        self.run()

    def balance(self) -> None:
        try:
            with self.manager.lock:
                if self.manager.closed or self.stopped.is_set() or self.manager.paused() is not False:
                    return
                layout = displays(self.manager.exchange(('query', 'monitors')))
                for operation in plan(layout):
                    match operation:
                        case MoveTile(target, workspace):
                            self.manager.exchange(('command', '--id', target, 'move', '--workspace', workspace))
                        case OrientWorkspace(target, direction):
                            self.manager.exchange(('command', '--id', target, 'set-tiling-direction', direction))
                        case _:
                            assert_never(operation)
        except OSError as error:
            self.problem(str(error))

    def run(self) -> None:
        candidate = None
        while not self.stopped.wait(1):
            try:
                if self.manager.paused() is not False:
                    continue
                layout = displays(self.manager.exchange(('query', 'monitors')))
                signature = tuple((d.identity, d.x, d.y, d.width, d.height, d.scale) for d in layout)
                if signature != self.signature and signature == candidate:
                    self.balance()
                    self.signature = signature
                candidate = signature
            except OSError:
                continue  # Hotplug can briefly expose an incomplete container tree.

    def close(self) -> None:
        self.stopped.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=4)
