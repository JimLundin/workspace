from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Final, Protocol, assert_never

from keyboard.actions import BLANK, Action, Chord, Layer, Output, TapHold
from keyboard.bindings import Bindings, Unmapped
from keyboard.board import Board
from keyboard.keys import Key, Mod
from keyboard.layout import Layout, Timings
from keyboard.physical import Scancode
from protocol import LayoutState, Request, Slot, Tool


class Host(Protocol):
    def send(self, key: Key | Mod, *, down: bool) -> None: ...
    def start_timer(self) -> int: ...
    def stop_timer(self, timer: int) -> None: ...
    def layout_state(self, state: LayoutState) -> None: ...

    def request(self, request: Request, *, down: bool) -> None: ...

    def indicate(self, indicator: Indicator) -> None: ...


class Verdict(Enum):
    PASS = auto()
    """Not ours: let it through unchanged."""
    SWALLOW = auto()
    """Handled (or deliberately blocked): don't let it through."""
    QUIT = auto()
    """The escape key was held long enough: shut down."""


class Decision(Enum):
    TAP = auto()
    HOLD = auto()


MAX_LAYERS = 4
"""Layers held at once: the layout has four layer keys."""
MAX_BUFFERED = 18
"""Key events that can wait on one undecided tap-hold key. One finger holds that
key; each of the other nine can add at most one press, plus the release of a key
it was already holding (auto-repeats are not buffered): 9 x 2 = 18. Anything
beyond that decides the key as a hold rather than growing."""


@dataclass(frozen=True, slots=True)
class Indicator:
    layer: Layer = Layer.BASE
    caps_word: bool = field(default=False, kw_only=True)
    chord: bool = field(default=False, kw_only=True)
    """The Apps layer is held, so a key makes its request, as a firmware chord would."""


@dataclass(frozen=True, slots=True)
class Pending:
    cell: int
    tap: Output
    hold: Mod | Layer
    timer: int
    pressed_at: int


@dataclass(frozen=True, slots=True)
class KeyDown:
    cell: int
    at: int


@dataclass(frozen=True, slots=True)
class KeyUp:
    cell: int
    at: int


type Event = KeyDown | KeyUp
"""A mapped physical key event, including repeats and buffered events."""


@dataclass(frozen=True, slots=True)
class LastTap:
    cell: int
    at: int


def elapsed(now: int, then: int) -> int:
    return (now - then) & 0xFFFF_FFFF


def is_typing(a: Action) -> bool:
    return isinstance(a, Key) or (isinstance(a, Chord) and a.types)


@dataclass(frozen=True, slots=True)
class Modifiers:
    counts: frozendict[Mod, int] = frozendict()

    def added(self, mod: Mod) -> Modifiers:
        return Modifiers(self.counts | {mod: self.counts.get(mod, 0) + 1})

    def removed(self, mod: Mod) -> Modifiers:
        count = self.counts.get(mod, 0)
        if count > 1:
            return Modifiers(self.counts | {mod: count - 1})
        return (
            Modifiers(
                frozendict(
                    {
                        held: each
                        for held, each in self.counts.items()
                        if held is not mod
                    }
                )
            )
            if count
            else self
        )

    def chord(self, host: Host, chord: Chord) -> None:
        added = [
            mod for mod in Mod if mod in chord.mods and mod not in self.counts
        ]
        for mod in added:
            host.send(mod, down=True)
        host.send(chord.key, down=True)
        for mod in reversed(added):
            host.send(mod, down=False)

    def release_all(self, host: Host) -> None:
        failures = 0
        for mod in self.counts:
            try:
                host.send(mod, down=False)
            except Exception:
                failures += 1
        if failures:
            raise OSError(f"Failed to release {failures} modifiers.")


NO_KEYS: Final[tuple[Action | None, ...]] = (None,) * Board.SIZE


def _put(
    pressed: tuple[Action | None, ...], cell: int, action: Action | None
) -> tuple[Action | None, ...]:
    return (*pressed[:cell], action, *pressed[cell + 1 :])


@dataclass(frozen=True, slots=True)
class EngineState:
    escape_down_at: int | None = None
    """When the escape key went down, if it is down."""
    enabled: bool = True
    """False while switched off with the escape key or tray toggle."""
    pressed: tuple[Action | None, ...] = NO_KEYS
    """What each held layout key turned into, by cell."""
    active_layers: tuple[Layer, ...] = ()
    pending: Pending | None = None
    buffer: tuple[Event, ...] = ()
    """Events that arrived while a tap-hold key was undecided."""
    last_typed_at: int | None = None
    """When the last character was typed (for the typing streak)."""
    last_tap: LastTap | None = None
    """The last tap-hold key tapped, and when (for quick tap)."""
    caps_word: bool = False
    mods: Modifiers = Modifiers()
    shown: Indicator = Indicator()
    """What the indicator was last told."""

    def layer(self) -> Layer:
        return self.active_layers[-1] if self.active_layers else Layer.BASE

    def failed_open(self) -> EngineState:
        return replace(self, enabled=False, escape_down_at=None)


class UnreleasedError(OSError):
    def __init__(self, state: EngineState, message: str) -> None:
        super().__init__(message)
        self.state: Final = state


@dataclass(frozen=True, slots=True)
class Engine:
    bindings: Bindings
    timings: Timings
    escape: Scancode
    """Tap to switch the layout on or off; hold to quit."""

    @classmethod
    def of(cls, layout: Layout, bindings: Bindings) -> Engine:
        return cls(bindings, layout.timings, layout.escape)

    def on_key(
        self,
        state: EngineState,
        host: Host,
        scancode: Scancode,
        *,
        down: bool,
        now: int,
    ) -> tuple[EngineState, Verdict]:
        state, verdict = self.key(state, host, scancode, down=down, now=now)
        return refresh(state, host), verdict

    def key(
        self,
        state: EngineState,
        host: Host,
        scancode: Scancode,
        *,
        down: bool,
        now: int,
    ) -> tuple[EngineState, Verdict]:
        if scancode == self.escape:
            pressed_at = state.escape_down_at
            if down:
                if pressed_at is None:
                    state = replace(state, escape_down_at=now)
            elif pressed_at is not None:
                state = replace(state, escape_down_at=None)
                if elapsed(now, pressed_at) >= self.timings.quit_hold:
                    return release_all(state, host), Verdict.QUIT
                state = toggle(state, host)
            return state, Verdict.SWALLOW
        if not state.enabled:
            return state, Verdict.PASS
        match self.bindings.slot(scancode):
            case Unmapped.FREE:
                return state, Verdict.PASS
            case Unmapped.BLOCKED:
                return state, Verdict.SWALLOW
            case int(cell):
                return self.event(
                    state,
                    host,
                    KeyDown(cell, now) if down else KeyUp(cell, now),
                ), Verdict.SWALLOW

    def in_streak(self, state: EngineState, now: int) -> bool:
        last = state.last_typed_at
        return last is not None and elapsed(now, last) < self.timings.streak

    def quick_tap(self, state: EngineState, cell: int, now: int) -> bool:
        last = state.last_tap
        return (
            last is not None
            and last.cell == cell
            and elapsed(now, last.at) < self.timings.quick_tap
        )

    def event(self, state: EngineState, host: Host, e: Event) -> EngineState:
        if p := state.pending:
            return self.event_while_pending(state, host, p, e)
        match e:
            case KeyUp(cell):
                if current := state.pressed[cell]:
                    return release(
                        replace(state, pressed=_put(state.pressed, cell, None)),
                        host,
                        current,
                    )
                return state
            case KeyDown(cell, now):
                if current := state.pressed[cell]:
                    return repeat(state, host, current, now)
                if (
                    bound := self.bindings.action(state.layer(), cell)
                ) is BLANK:
                    return state
                match bound:
                    case TapHold(tap) if self.quick_tap(state, cell, now):
                        a: Action = tap
                    case TapHold(tap, Mod() as mod) if (
                        mod != Mod.SHIFT and self.in_streak(state, now)
                    ):
                        a = tap
                    case TapHold(tap, hold):
                        return replace(
                            state,
                            pending=Pending(
                                cell, tap, hold, host.start_timer(), now
                            ),
                            buffer=(),
                        )
                    case other:
                        a = other
                return press(
                    replace(state, pressed=_put(state.pressed, cell, a)),
                    host,
                    a,
                    now,
                )
            case _:
                assert_never(e)

    def event_while_pending(
        self, state: EngineState, host: Host, p: Pending, e: Event
    ) -> EngineState:
        if e.cell == p.cell:
            match e:
                case KeyUp(_, now):
                    return self.resolve(state, host, Decision.TAP, now=now)
                case KeyDown():
                    return state
                case _:
                    assert_never(e)
        buffer = state.buffer
        match e:
            case KeyDown(cell, now):
                released_meanwhile = any(
                    isinstance(waiting, KeyUp) and waiting.cell == cell
                    for waiting in buffer
                )
                if not released_meanwhile:
                    if current := state.pressed[cell]:
                        return repeat(state, host, current, now)
                    for waiting in reversed(buffer):
                        if waiting.cell == cell:
                            if isinstance(waiting, KeyDown):
                                return state
                            break
                first_press = not any(
                    isinstance(waiting, KeyDown) for waiting in buffer
                )
                if (
                    first_press
                    and isinstance(p.hold, Mod)
                    and self.bindings.hand(cell) is self.bindings.hand(p.cell)
                ):
                    match self.bindings.action(state.layer(), cell):
                        case TapHold(hold=Mod()):
                            pass
                        case _:
                            return self.event(
                                self.resolve(
                                    state, host, Decision.TAP, now=now
                                ),
                                host,
                                e,
                            )
            case KeyUp():
                pass
            case _:
                assert_never(e)
        if len(buffer) >= MAX_BUFFERED:
            return self.event(
                self.resolve(state, host, Decision.HOLD, now=e.at), host, e
            )
        buffer = (*buffer, e)
        state = replace(state, buffer=buffer)
        if isinstance(e, KeyUp) and any(
            isinstance(waiting, KeyDown) and waiting.cell == e.cell
            for waiting in buffer
        ):
            across = isinstance(p.hold, Layer) or any(
                isinstance(waiting, KeyDown)
                and self.bindings.hand(waiting.cell)
                is not self.bindings.hand(p.cell)
                for waiting in buffer
            )
            return self.resolve(
                state, host, Decision.HOLD if across else Decision.TAP, now=e.at
            )
        return state

    def timeout(
        self, state: EngineState, host: Host, timer: int
    ) -> EngineState:
        if (p := state.pending) and p.timer == timer:
            return refresh(
                self.resolve(state, host, Decision.HOLD, now=p.pressed_at), host
            )
        return state

    def resolve(
        self, state: EngineState, host: Host, decision: Decision, *, now: int
    ) -> EngineState:
        p = state.pending
        if p is None:
            return state
        state = replace(state, pending=None)
        host.stop_timer(p.timer)
        match decision:
            case Decision.HOLD:
                state = press(
                    replace(state, pressed=_put(state.pressed, p.cell, p.hold)),
                    host,
                    p.hold,
                    p.pressed_at,
                )
            case Decision.TAP:
                state = release(
                    press(state, host, p.tap, p.pressed_at), host, p.tap
                )
                state = replace(state, last_tap=LastTap(p.cell, now))
            case _:
                assert_never(decision)
        waiting, state = state.buffer, replace(state, buffer=())
        for e in waiting:
            state = self.event(state, host, e)
        return state


def refresh(state: EngineState, host: Host) -> EngineState:
    layer, shown = state.layer(), state.shown
    chord = layer is Layer.APPS
    if (
        layer is not shown.layer
        or state.caps_word is not shown.caps_word
        or chord is not shown.chord
    ):
        indicated = Indicator(layer, caps_word=state.caps_word, chord=chord)
        host.indicate(indicated)
        return replace(state, shown=indicated)
    return state


def toggle(state: EngineState, host: Host) -> EngineState:
    state = release_all(replace(state, escape_down_at=None), host)
    state = replace(state, enabled=not state.enabled)
    host.layout_state(LayoutState.ON if state.enabled else LayoutState.OFF)
    return refresh(state, host)


def repeat(
    state: EngineState, host: Host, current: Action, now: int
) -> EngineState:
    return (
        press(state, host, current, now)
        if isinstance(current, (Key, Chord))
        else state
    )


def release_all(state: EngineState, host: Host) -> EngineState:
    failures = 0
    if state.pending is not None:
        try:
            host.stop_timer(state.pending.timer)
        except Exception:
            failures += 1
    released = replace(state, pending=None, buffer=(), pressed=NO_KEYS)
    for a in state.pressed:
        if a is not None:
            try:
                released = release(released, host, a)
            except Exception:
                failures += 1
    cleared = replace(
        released,
        active_layers=(),
        last_typed_at=None,
        last_tap=None,
        caps_word=False,
        mods=Modifiers(),
    )
    try:
        released.mods.release_all(host)
    except Exception:
        failures += 1
    if failures:
        raise UnreleasedError(
            cleared,
            f"Failed to complete {failures} keyboard cleanup operations.",
        )
    return cleared


def apply_caps_word(
    state: EngineState, a: Action
) -> tuple[EngineState, Action]:
    if not state.caps_word:
        return state, a
    match a:
        case Key() if a.is_letter():
            return state, Chord.shifted(a)
        case Key() if a.continues_word():
            return state, a
        case Chord(Key.MINUS) as chord if chord.only_shifted:
            return state, a
        case Key() | Chord():
            return replace(state, caps_word=False), a
        case Mod() | Layer() | TapHold() | Tool() | Slot():
            return state, a


def press(state: EngineState, host: Host, a: Action, now: int) -> EngineState:
    if a == Mod.SHIFT and state.pressed.count(Mod.SHIFT) >= 2:
        state = replace(state, caps_word=not state.caps_word)
    state, a = apply_caps_word(state, a)
    match a:
        case Key():
            host.send(a, down=True)
        case Chord():
            state.mods.chord(host, a)
        case Mod():
            if a not in state.mods.counts:
                host.send(a, down=True)
            state = replace(state, mods=state.mods.added(a))
        case Layer():
            if len(state.active_layers) < MAX_LAYERS:
                state = replace(state, active_layers=(*state.active_layers, a))
        case Tool() | Slot():
            if Mod.ALT in state.mods.counts:
                host.send(Key.MENU_MASK, down=True)
                host.send(Key.MENU_MASK, down=False)
            host.request(a, down=True)
        case TapHold():
            pass
        case _:
            assert_never(a)
    return replace(state, last_typed_at=now) if is_typing(a) else state


def release(state: EngineState, host: Host, a: Action) -> EngineState:
    match a:
        case Key():
            host.send(a, down=False)
        case Chord():
            host.send(a.key, down=False)
        case Mod():
            if state.mods.counts.get(a, 0) == 1:
                host.send(a, down=False)
            return replace(state, mods=state.mods.removed(a))
        case Layer():
            layers = state.active_layers
            if a in layers:
                index = len(layers) - 1 - layers[::-1].index(a)
                return replace(
                    state, active_layers=layers[:index] + layers[index + 1 :]
                )
        case Tool() | Slot():
            host.request(a, down=False)
        case TapHold():
            pass
        case _:
            assert_never(a)
    return state
