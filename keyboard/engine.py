"""Windows keyboard logic: decides what each physical key press or release turns
into, in Windows terms (virtual keys, modifiers). It makes no Win32 calls itself;
those go through a `Host`, so the logic can be tested without Windows. Each
step takes the keyboard's `EngineState` and returns the next one; its caller
keeps it. The layout's rules are an `Engine`, built from a `keyboard.layout.Layout`.

Tap-hold rule (like KMonad's tap-hold-next-release): a tap-hold key becomes
"hold" if another key is pressed AND released while it is down, or if it is
held past the tapping term. Otherwise it is a tap.

Chordal hold: for home row mods, if the first other key pressed is on the same
hand, it is a tap, decided at once. You use a modifier with the other hand, so
a same-hand key means a fast roll, not a shortcut. Holding past the tapping
term still always makes it a modifier.

Quick tap: tap a tap-hold key and press it again within `Timings.quick_tap`, and
the second press is that key held down, so it repeats (Backspace, Space...).

Typing streak: right after a typed character, a home row mod (except Shift) is
a letter immediately. Shift is exempt so capitals after a space still work;
layer thumbs are exempt so symbols and numbers inside words still work.

Caps word: holding both Shift keys turns it on (or off). Letters then come out
capitalised until something that isn't part of a word: a space, punctuation,
Enter, an arrow... Digits, `_`, Backspace and Delete keep it going.

Requests: every Workspace request is on the Apps layer. Hold-to-talk tools
send their press and release; disabling the layout releases them.
"""

from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Final, Protocol, assert_never

from keyboard.actions import BLANK, Action, Chord, Layer, Output, TapHold
from keyboard.bindings import Bindings, Unmapped
from keyboard.board import Board
from keyboard.keys import Key, Mod
from keyboard.layout import Layout, Timings
from keyboard.physical import Scancode
from protocol import App, LayoutState, Request, Tool


class Host(Protocol):
    """What the engine needs from Windows."""

    def send(self, key: Key | Mod, *, down: bool) -> None: ...
    def start_timer(self) -> int: ...
    def stop_timer(self, timer: int) -> None: ...
    def layout_state(self, state: LayoutState) -> None:
        """The layout was switched on or off."""

    def request(self, request: Request, *, down: bool) -> None:
        """A tool or app key went down or up: pass it on to the assistant."""

    def indicate(self, indicator: Indicator) -> None:
        """What the layer indicator should show now (it changed)."""


class Verdict(Enum):
    """What the OS should do with a physical key event."""

    PASS = auto()
    """Not ours: let it through unchanged."""
    SWALLOW = auto()
    """Handled (or deliberately blocked): don't let it through."""
    QUIT = auto()
    """The escape key was held long enough: shut down."""


class Decision(Enum):
    """How an undecided tap-hold key is resolved."""

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
    """State the user can't see on the keys: the layer keys come from, and caps word."""

    layer: Layer = Layer.BASE
    caps_word: bool = field(default=False, kw_only=True)
    chord: bool = field(default=False, kw_only=True)
    """The Apps layer is held, so a key makes its request, as a firmware chord would."""


@dataclass(frozen=True, slots=True)
class Pending:
    """A tap-hold key that is down but not yet decided."""

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
    """Milliseconds between two Windows timestamps, which wrap at 2**32."""
    return (now - then) & 0xFFFF_FFFF


def is_typing(a: Action) -> bool:
    """A typed character (for the typing streak): a key, maybe shifted, but not a shortcut."""
    return isinstance(a, Key) or (isinstance(a, Chord) and a.types)


@dataclass(frozen=True, slots=True)
class Modifiers:
    """Which modifiers Windows has down, and how many held keys want each one.
    Windows is told only when a count goes from 0 to 1 or back, so one key can't
    release another's modifier."""

    counts: frozendict[Mod, int] = frozendict()

    def added(self, mod: Mod) -> Modifiers:
        return Modifiers(self.counts | {mod: self.counts.get(mod, 0) + 1})

    def removed(self, mod: Mod) -> Modifiers:
        count = self.counts.get(mod, 0)
        if count > 1:
            return Modifiers(self.counts | {mod: count - 1})
        return Modifiers(frozendict({held: each for held, each in self.counts.items() if held is not mod})) if count else self

    def chord(self, host: Host, chord: Chord) -> None:
        """The chord's key goes down with its modifiers around it. Modifiers already
        held are left alone; the ones added are released right after."""
        added = [mod for mod in Mod if mod in chord.mods and mod not in self.counts]  # in a fixed order
        for mod in added:
            host.send(mod, down=True)
        host.send(chord.key, down=True)
        for mod in reversed(added):
            host.send(mod, down=False)

    def release_all(self, host: Host) -> None:
        """Release every held modifier; the owner forgets them before calling."""
        failures = 0
        for mod in self.counts:
            try:
                host.send(mod, down=False)
            except Exception:
                failures += 1
        if failures:
            raise OSError(f"Failed to release {failures} modifiers.")


NO_KEYS: Final[tuple[Action | None, ...]] = (None,) * Board.SIZE


def _put(pressed: tuple[Action | None, ...], cell: int, action: Action | None) -> tuple[Action | None, ...]:
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
        """The layer keys are read from: the top held layer, else the base layer."""
        return self.active_layers[-1] if self.active_layers else Layer.BASE

    def failed_open(self) -> EngineState:
        """Input failed: stop remapping and forget the escape press."""
        return replace(self, enabled=False, escape_down_at=None)


class UnreleasedError(OSError):
    """Cleanup was refused for some input; `state` is the engine with all of it forgotten."""

    def __init__(self, state: EngineState, message: str) -> None:
        super().__init__(message)
        self.state: Final = state


@dataclass(frozen=True, slots=True)
class Engine:
    """A layout's rules: what each key event turns into. Each method takes the
    keyboard's `EngineState` and returns the next one; its caller keeps it."""

    bindings: Bindings
    timings: Timings
    escape: Scancode
    """Tap to switch the layout on or off; hold to quit."""

    @classmethod
    def of(cls, layout: Layout, bindings: Bindings) -> Engine:
        return cls(bindings, layout.timings, layout.escape)

    def on_key(self, state: EngineState, host: Host, scancode: Scancode, *, down: bool, now: int) -> tuple[EngineState, Verdict]:
        """One physical key event, then the indicator. `now` is the event's timestamp in ms (it may wrap around)."""
        state, verdict = self.key(state, host, scancode, down=down, now=now)
        return refresh(state, host), verdict

    def key(self, state: EngineState, host: Host, scancode: Scancode, *, down: bool, now: int) -> tuple[EngineState, Verdict]:
        # Escape key: tap = on/off, hold = quit. Checked first, works in both states.
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
                return self.event(state, host, KeyDown(cell, now) if down else KeyUp(cell, now)), Verdict.SWALLOW

    def in_streak(self, state: EngineState, now: int) -> bool:
        last = state.last_typed_at
        return last is not None and elapsed(now, last) < self.timings.streak

    def quick_tap(self, state: EngineState, cell: int, now: int) -> bool:
        last = state.last_tap
        return last is not None and last.cell == cell and elapsed(now, last.at) < self.timings.quick_tap

    def event(self, state: EngineState, host: Host, e: Event) -> EngineState:
        if p := state.pending:
            return self.event_while_pending(state, host, p, e)
        match e:
            case KeyUp(cell):
                if current := state.pressed[cell]:
                    return release(replace(state, pressed=_put(state.pressed, cell, None)), host, current)
                return state
            case KeyDown(cell, now):
                if current := state.pressed[cell]:
                    return repeat(state, host, current, now)
                if (bound := self.bindings.action(state.layer(), cell)) is BLANK:
                    return state  # Nothing pressed, so its release has nothing to end.
                match bound:
                    case TapHold(tap) if self.quick_tap(state, cell, now):
                        a: Action = tap
                    case TapHold(tap, Mod() as mod) if mod != Mod.SHIFT and self.in_streak(state, now):
                        a = tap
                    case TapHold(tap, hold):
                        return replace(state, pending=Pending(cell, tap, hold, host.start_timer(), now), buffer=())
                    case other:
                        a = other
                return press(replace(state, pressed=_put(state.pressed, cell, a)), host, a, now)
            case _:
                assert_never(e)

    def event_while_pending(self, state: EngineState, host: Host, p: Pending, e: Event) -> EngineState:
        if e.cell == p.cell:
            match e:
                case KeyUp(_, now):
                    return self.resolve(state, host, Decision.TAP, now=now)
                case KeyDown():
                    return state  # auto-repeat of the undecided key is ignored
                case _:
                    assert_never(e)
        buffer = state.buffer
        match e:
            case KeyDown(cell, now):
                released_meanwhile = any(isinstance(waiting, KeyUp) and waiting.cell == cell for waiting in buffer)
                if not released_meanwhile:
                    # A key held since before is already decided: repeat it now.
                    if current := state.pressed[cell]:
                        return repeat(state, host, current, now)
                    # A buffered key's repeated down adds nothing; reuse the queued event.
                    for waiting in reversed(buffer):
                        if waiting.cell == cell:
                            if isinstance(waiting, KeyDown):
                                return state
                            break
                # The first press on the modifier's own hand is a roll, unless it is
                # another home row mod: same-hand mods combine, as QMK's Chordal Hold.
                first_press = not any(isinstance(waiting, KeyDown) for waiting in buffer)
                if first_press and isinstance(p.hold, Mod) and self.bindings.hand(cell) is self.bindings.hand(p.cell):
                    match self.bindings.action(state.layer(), cell):
                        case TapHold(hold=Mod()):
                            pass
                        case _:
                            return self.event(self.resolve(state, host, Decision.TAP, now=now), host, e)
            case KeyUp():
                pass
            case _:
                assert_never(e)
        if len(buffer) >= MAX_BUFFERED:
            # Too many keys waiting: decide it as a hold, then handle this one.
            return self.event(self.resolve(state, host, Decision.HOLD, now=e.at), host, e)
        buffer = (*buffer, e)
        state = replace(state, buffer=buffer)
        if isinstance(e, KeyUp) and any(isinstance(waiting, KeyDown) and waiting.cell == e.cell for waiting in buffer):
            # A home row mod holds only for a key on the other hand; a same-hand tap inside it is a roll.
            across = isinstance(p.hold, Layer) or any(
                isinstance(waiting, KeyDown) and self.bindings.hand(waiting.cell) is not self.bindings.hand(p.cell) for waiting in buffer
            )
            return self.resolve(state, host, Decision.HOLD if across else Decision.TAP, now=e.at)
        return state

    def timeout(self, state: EngineState, host: Host, timer: int) -> EngineState:
        if (p := state.pending) and p.timer == timer:
            return refresh(self.resolve(state, host, Decision.HOLD, now=p.pressed_at), host)
        return state

    def resolve(self, state: EngineState, host: Host, decision: Decision, *, now: int) -> EngineState:
        """Decide the undecided key. `now` is when the decision happened."""
        p = state.pending
        if p is None:
            return state
        state = replace(state, pending=None)
        host.stop_timer(p.timer)
        match decision:
            case Decision.HOLD:
                state = press(replace(state, pressed=_put(state.pressed, p.cell, p.hold)), host, p.hold, p.pressed_at)
            case Decision.TAP:
                state = release(press(state, host, p.tap, p.pressed_at), host, p.tap)
                state = replace(state, last_tap=LastTap(p.cell, now))
            case _:
                assert_never(decision)
        waiting, state = state.buffer, replace(state, buffer=())
        for e in waiting:
            state = self.event(state, host, e)
        return state


def refresh(state: EngineState, host: Host) -> EngineState:
    """Tells the indicator if what it should show has changed; every key event refreshes, so it builds a record only for a change."""
    layer, shown = state.layer(), state.shown
    chord = layer is Layer.APPS
    if layer is not shown.layer or state.caps_word is not shown.caps_word or chord is not shown.chord:
        indicated = Indicator(layer, caps_word=state.caps_word, chord=chord)
        host.indicate(indicated)
        return replace(state, shown=indicated)
    return state


def toggle(state: EngineState, host: Host) -> EngineState:
    """Switch the layout on/off, releasing held input and clearing its indicator."""
    state = release_all(replace(state, escape_down_at=None), host)
    state = replace(state, enabled=not state.enabled)
    host.layout_state(LayoutState.ON if state.enabled else LayoutState.OFF)
    return refresh(state, host)


def repeat(state: EngineState, host: Host, current: Action, now: int) -> EngineState:
    """Auto-repeat: repeat the output already chosen on the first press."""
    return press(state, host, current, now) if isinstance(current, (Key, Chord)) else state


def release_all(state: EngineState, host: Host) -> EngineState:
    """Clear ownership first and attempt every release, even after rejection.

    A rejected release raises `UnreleasedError`, which carries the cleared state.
    """
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
    cleared = replace(released, active_layers=(), last_typed_at=None, last_tap=None, caps_word=False, mods=Modifiers())
    try:
        released.mods.release_all(host)
    except Exception:
        failures += 1
    if failures:
        raise UnreleasedError(cleared, f"Failed to complete {failures} keyboard cleanup operations.")
    return cleared


def apply_caps_word(state: EngineState, a: Action) -> tuple[EngineState, Action]:
    """Caps word: capitalise letters, let word characters through, end on anything else."""
    if not state.caps_word:
        return state, a
    match a:
        case Key() if a.is_letter():
            return state, Chord.shifted(a)
        case Key() if a.continues_word():
            return state, a
        case Chord(Key.MINUS) as chord if chord.only_shifted:  # _
            return state, a
        case Key() | Chord():
            return replace(state, caps_word=False), a
        case Mod() | Layer() | TapHold() | Tool() | App():
            return state, a


def press(state: EngineState, host: Host, a: Action, now: int) -> EngineState:
    # Both Shift keys held (this one is already recorded as pressed): toggle caps word.
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
            # A layer beyond MAX_LAYERS is ignored rather than stored.
            if len(state.active_layers) < MAX_LAYERS:
                state = replace(state, active_layers=(*state.active_layers, a))
        case Tool() | App():
            if Mod.ALT in state.mods.counts:
                # Applications see Alt pressed alone; tapping an unassigned key
                # keeps its release from opening a menu.
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
            # Forget the hold first: the caller keeps this state if Windows refuses the release.
            if state.mods.counts.get(a, 0) == 1:
                host.send(a, down=False)
            return replace(state, mods=state.mods.removed(a))
        case Layer():
            layers = state.active_layers
            if a in layers:
                # Remove the most recently added copy.
                index = len(layers) - 1 - layers[::-1].index(a)
                return replace(state, active_layers=layers[:index] + layers[index + 1 :])
        case Tool() | App():
            host.request(a, down=False)
        case TapHold():
            pass
        case _:
            assert_never(a)
    return state
