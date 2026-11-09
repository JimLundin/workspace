"""Windows glue: installs a low-level keyboard hook, routes each key, feeds the
layout's keys to the engine, sends the results, and runs the message loop. Every
request, what the desktop shows (layer, chord, pressed keys) and the layout's
state go to the desktop's control window.
"""

import contextlib
import gc
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Final, Protocol, assert_never

import components
import config
import diagnostics
from cell import Cell
from diagnostics import Detail, FailureInfo, failure_info
from keyboard import engine, hook_watch, settings
from keyboard.bindings import native_control, pictured
from keyboard.engine import EngineState, Indicator, UnreleasedError, Verdict
from keyboard.firmware import CapturedKey, ConsumedKey, FirmwareKeyboard, HeldShortcut, connected, shortcut
from keyboard.hook_watch import ANSWERED
from keyboard.layout import Key, Mod, Scancode
from protocol import LayoutState, Message, Origin, Request, Window, encode, encode_indicator
from winapi import inputs, keyboard_devices, keyboard_language, system, windows

LOCK_NAME: Final = "Local\\keyboard"
"""Name of the lock that stops a second copy from running in this Windows session."""
LOG: Final = components.DIRECTORY / "keyboard.log"
"""The keyboard's own log: its input recoveries."""


class KeyboardSystem(Protocol):
    """Native input, observation and delivery owned by the keyboard process."""

    def send_key(self, key: Key | Mod, *, down: bool) -> None: ...
    def keyboard_devices(self) -> tuple[str, ...]: ...
    def foreground(self) -> int: ...
    def title(self, hwnd: int) -> str: ...
    def read_key_event(self, lparam: int) -> inputs.KeyEvent: ...
    def call_next_hook(self, code: int, wparam: int, lparam: int) -> int: ...
    def find_window(self, window: Window) -> int | None: ...
    def post_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> bool: ...
    def set_timer(self, ms: int) -> int: ...
    def kill_timer(self, timer: int) -> None: ...
    def record_recovery(self, details: Mapping[str, Detail]) -> None: ...
    def post_quit(self) -> None: ...


@dataclass(frozen=True, slots=True)
class NativeKeyboardSystem:
    """The live Windows adapter; constructing it starts no hook or timer."""

    def send_key(self, key: Key | Mod, *, down: bool) -> None:
        inputs.send_key(key.vk, down=down, extended=key.extended, extra=Origin.LAYOUT)

    keyboard_devices = staticmethod(keyboard_devices.names)
    foreground = staticmethod(windows.foreground)
    title = staticmethod(windows.title)
    read_key_event = staticmethod(inputs.read_key_event)
    call_next_hook = staticmethod(inputs.call_next_hook)

    def find_window(self, window: Window) -> int | None:
        return windows.find(window.title)

    def post_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> bool:
        return system.post_message(hwnd, message, wparam, lparam)

    set_timer = staticmethod(system.set_timer)
    kill_timer = staticmethod(system.kill_timer)

    def record_recovery(self, details: Mapping[str, Detail]) -> None:
        diagnostics.append(LOG, diagnostics.evidence("input_recovery", details))

    post_quit = staticmethod(system.post_quit)


@dataclass(frozen=True, slots=True)
class _Hosted:
    found: int | None = None
    """The desktop's control window, once found."""
    owned: frozenset[Key | Mod] = frozenset()
    """Attempted Workspace output, retained until Windows accepts its key-up."""
    chord: bool = False
    """The layout's home row chord, last published like the firmware keyboard's."""


@dataclass(frozen=True, slots=True)
class WinHost:
    """What the engine needs, done with Windows calls. Only the hook thread uses it."""

    platform: KeyboardSystem = field(default_factory=NativeKeyboardSystem)
    _state: Cell[_Hosted] = field(default_factory=lambda: Cell(_Hosted()), init=False, repr=False)

    @property
    def found(self) -> int | None:
        return self._state.get().found

    @property
    def owned(self) -> frozenset[Key | Mod]:
        return self._state.get().owned

    def remember_window(self, found: int | None) -> None:
        """Start from a known desktop window, as after it was found before."""
        self._state.set(replace(self._state.get(), found=found))

    def own(self, key: Key | Mod) -> None:
        """Treat `key` as Workspace output whose key-up Windows has not yet accepted."""
        self._state.set(replace(self._state.get(), owned=self._state.get().owned | {key}))

    def send(self, key: Key | Mod, *, down: bool) -> None:
        if down:
            self.own(key)
        self.platform.send_key(key, down=down)
        if not down:
            self._state.set(replace(self._state.get(), owned=self._state.get().owned - {key}))

    def release_owned(self) -> None:
        """Retry only our outputs, including a chord interrupted before engine ownership."""
        for key in tuple(self._state.get().owned):
            with contextlib.suppress(Exception):
                self.send(key, down=False)

    def start_timer(self) -> int:
        return self.platform.set_timer(settings.TAPPING_TERM_MS)

    def stop_timer(self, timer: int) -> None:
        self.platform.kill_timer(timer)

    def request(self, request: Request, *, down: bool) -> None:
        # Never replay a press the desktop missed: it could start an unwanted action later.
        self.tell(Message.REQUEST, encode(request, config.APPS), int(down))

    def indicate(self, indicator: Indicator) -> None:
        layer: int = indicator.layer.value if indicator.layer else 0
        self.tell(Message.INDICATOR, encode_indicator(layer, caps_word=indicator.caps_word), 0)
        if indicator.chord != self._state.get().chord:
            self._state.set(replace(self._state.get(), chord=indicator.chord))
            self.tell(Message.CHORD, int(indicator.chord), 0)

    def tell(self, message: int, wparam: int, lparam: int) -> bool:
        """Posts to the desktop's window; nothing happens if it isn't running."""
        for _ in range(2):  # a cached window may be gone (the desktop restarted): look again
            handle = self.found
            if handle is None:
                handle = self.platform.find_window(components.DESKTOP.window)
                if handle is None:
                    return False
                self.remember_window(handle)
            if self.platform.post_message(handle, message, wparam, lparam):
                return True
            self.remember_window(None)
        return False

    def layout_state(self, state: LayoutState) -> None:
        """The desktop follows the layout: it shows it, and dictation stops capture when it's off."""
        self.tell(Message.LAYOUT_STATE, state.value, 0)


class Exit(Enum):
    QUIT = auto()
    """Quit normally (the escape key was held, or the assistant asked)."""
    ALREADY_RUNNING = auto()
    HOOK_REFUSED = auto()
    """Windows refused the keyboard hook."""


class Route(Enum):
    """What kind of key the hook is looking at, decided before anything acts on it."""

    OWN = auto()
    """Our own output, the desktop's typed text, or a key arriving while the engine runs: untouched."""
    APPS_THUMB = auto()
    """The Charybdis's Tab thumb (Right Alt): Workspace's own key, never an application's."""
    SHORTCUT_HELD = auto()
    """A repeat or release of a Charybdis shortcut already captured."""
    SHORTCUT = auto()
    """A fresh chord key under the Charybdis's Apps thumb."""
    FIRMWARE = auto()
    """Any other key while the Charybdis is connected: native."""
    OWED_UP = auto()
    """A key-up Windows is owed for a key-down it saw natively."""
    NATIVE = auto()
    """Function, media, arrow and physical modifier keys, and the window switcher's Esc, Enter and Tab."""
    EXTENDED = auto()
    """Other extended keys, which share base scancodes with layout cells: never remapped."""
    LAYOUT = auto()
    """Everything else: the engine decides."""


SWITCHER_KEYS: Final = frozenset({0x1B, 0x0D, 0x09})
"""Esc, Enter and Tab, which the window switcher reads natively."""


def identity(key: inputs.KeyEvent) -> int:
    """A physical key: its scancode, with extended keys kept apart."""
    return key.scancode | (0x100 if key.extended else 0)


def physical(key: inputs.KeyEvent) -> bool:
    """Typed on a keyboard, not injected by any program."""
    return not key.injected


def route(key: inputs.KeyEvent, state: HookState, *, down: bool) -> Route:
    """The hook's policy, in the order it applies: each rule only sees keys the ones above let through."""
    if state.busy or key.extra == Origin.LAYOUT:
        return Route.OWN
    key_identity = identity(key)
    typed = physical(key) and key.extra != Origin.DESKTOP
    if typed and (state.firmware is not None or state.shortcuts):
        if state.firmware is not None and key.vk == settings.APPS_KEY:
            return Route.APPS_THUMB
        if any(held.identity == key_identity for held in state.shortcuts):
            return Route.SHORTCUT_HELD
        if state.firmware is not None and down and key_identity not in state.owed and shortcut(key.vk, apps_held=state.apps_held):
            return Route.SHORTCUT
    if state.firmware is not None:
        return Route.FIRMWARE
    if typed and not down and key_identity in state.owed:
        return Route.OWED_UP
    if key.extra == Origin.DESKTOP:
        return Route.OWN
    if (state.switcher and key.vk in SWITCHER_KEYS) or native_control(key.vk):
        return Route.NATIVE
    if key.extended:
        return Route.EXTENDED
    return Route.LAYOUT


def owes(key: inputs.KeyEvent, state: HookState, *, down: bool) -> bool:
    """Whether Windows must later get this key's up natively: a physical down the layout won't own.

    That is every physical down while the layout is off (but the escape key, which turns
    it on), and the window switcher's own keys."""
    if not down or not physical(key) or key.extra == Origin.DESKTOP:
        return False
    if not state.engine.enabled and (key.scancode != settings.ESCAPE or key.extended):
        return True
    return state.switcher and key.vk in SWITCHER_KEYS


@dataclass(frozen=True, slots=True)
class Recovery:
    """A failure the hook failed open on, until its cleanup is retried and logged."""

    fault: FailureInfo
    phase: str
    ticks: int
    """Maintenance ticks left to retry refused key-ups before logging."""
    cleanup_failures: int = 0


@dataclass(frozen=True, slots=True)
class HookState:
    """Everything the hook thread knows between calls, replaced whole by each change."""

    engine: EngineState = field(default_factory=EngineState)
    """The layout engine's state: each key, timer and toggle returns the next one."""
    window: int = 0
    """The foreground window, polled on each key."""
    switcher: bool = False
    """The foreground window is Workspace's window switcher."""
    pressed: frozenset[Scancode] = frozenset()
    """Physical keys for the overlay, independent of delayed tap/hold decisions."""
    owed: frozenset[int] = frozenset()
    """Key identities whose down Windows saw natively, so their up must pass too."""
    firmware: FirmwareKeyboard | None = None
    """The Charybdis's suspension of the layout, while it is plugged in."""
    shortcuts: tuple[CapturedKey, ...] = ()
    """Charybdis shortcut presses Workspace owns, including ups after unplug."""
    apps_held: bool = False
    """The Charybdis holds its Tab thumb, which sends Right Alt for Apps."""
    chord_held: bool = False
    """The desktop was last told the Charybdis holds its Apps thumb."""
    busy: bool = False
    """Set while the engine runs; a re-entrant call lets its key through."""
    recovery: Recovery | None = None
    hook_tick: int | None = None
    """The newest key time the hook has seen; the hook's only watchdog cost."""
    watch: hook_watch.Watch = ANSWERED


def _busy(state: HookState) -> HookState:
    return replace(state, busy=True)


def _idle(state: HookState) -> HookState:
    return replace(state, busy=False)


@dataclass(frozen=True, slots=True)
class Guard:
    """Marks the hook busy for a `with` block; a plain class, since it runs on every layout key."""

    state: Cell[HookState]

    def __enter__(self) -> None:
        self.state.update(_busy)

    def __exit__(self, *_: object) -> None:
        self.state.update(_idle)


@dataclass(frozen=True, slots=True)
class Keyboard:
    """The engine, plus what the hook callback needs around it. Only the hook thread runs it."""

    platform: KeyboardSystem
    host: WinHost
    _state: Cell[HookState]

    @classmethod
    def open(cls, platform: KeyboardSystem | None = None) -> Keyboard:
        system = platform if platform is not None else NativeKeyboardSystem()
        return cls(system, WinHost(system), Cell(HookState()))

    @property
    def state(self) -> HookState:
        return self._state.get()

    def restore(self, state: HookState) -> None:
        """Put the keyboard in a given state: tests use it to start mid-gesture."""
        self._state.set(state)

    @property
    def engine_state(self) -> EngineState:
        return self._state.get().engine

    def set_keys(self, keys: EngineState) -> None:
        self._state.update(lambda state: replace(state, engine=keys))

    def guarded(self) -> Guard:
        """Keys arriving meanwhile (our own output) pass untouched."""
        return Guard(self._state)

    def step_keys(self, step: Callable[[EngineState], tuple[EngineState, Verdict]]) -> Verdict:
        """Run one engine step and keep the state it returns, including after a refused cleanup."""
        try:
            keys, verdict = step(self.engine_state)
        except UnreleasedError as error:
            self.set_keys(error.state)
            raise
        self.set_keys(keys)
        return verdict

    def release_keys(self) -> None:
        self.step_keys(lambda keys: (engine.release_all(keys, self.host), Verdict.PASS))

    def toggle_keys(self) -> None:
        self.step_keys(lambda keys: (engine.toggle(keys, self.host), Verdict.PASS))

    def timeout(self, timer: int) -> None:
        """A tapping-term timer fired."""
        self.step_keys(lambda keys: (engine.timeout(keys, self.host, timer), Verdict.PASS))

    def raw_key(self, at: int) -> None:
        """Raw input saw a key at `at`: the hook watchdog's evidence that keys still arrive."""
        self._state.update(lambda state: replace(state, watch=hook_watch.keyboard_input(state.watch, at)))

    def on_message(self, message: int) -> None:
        """The desktop's query and the tray's toggle; toggling uses the same guard as physical keys."""
        state = self._state.get()
        if message == Message.QUERY_LAYOUT_STATE:
            self.host.layout_state(LayoutState.ON if state.engine.enabled else LayoutState.OFF)
            self.host.indicate(state.engine.shown)
            self.host.tell(Message.KEY_STATE, 0, 0)
            for scancode in sorted(state.pressed):
                self.host.tell(Message.KEY_STATE, scancode, 1)
            self.host.tell(Message.CHORD, int(state.chord_held or state.engine.shown.chord), 0)
        if message != Message.TOGGLE_LAYOUT or state.firmware is not None:
            return
        with self.guarded():
            try:
                if not state.engine.enabled:
                    self.prepare_enable()
                self.toggle_keys()
                self.clear_pressed()
            except Exception as error:
                self.input_failed(error, phase="toggle")

    def update_devices(self) -> None:
        """Observe hotplug outside the hook, release outputs, and restore prior intent."""
        previous = self._state.get().firmware
        attached = connected(self.platform.keyboard_devices())
        if attached == (previous is not None):
            return
        if attached:
            enabled = self.engine_state.enabled
            self._state.update(lambda state: replace(state, firmware=FirmwareKeyboard(resume_layout=enabled)))
            with self.guarded():
                try:
                    if enabled:
                        self.toggle_keys()
                    self.clear_pressed()
                except Exception as error:
                    self.input_failed(error, phase="firmware_keyboard")
            return
        self._state.update(lambda state: replace(state, firmware=None, apps_held=False))
        try:
            self.observe_chord()
            self.release_shortcuts()
        except Exception as error:
            self.input_failed(error, phase="firmware_shortcut")
            return
        if previous is not None and previous.resume_layout:
            self.on_message(Message.TOGGLE_LAYOUT)

    def release_shortcuts(self) -> None:
        """End capture on unplug, failure or shutdown, still swallowing the keys' ups."""
        held = self._state.get().shortcuts
        self._state.update(lambda state: replace(state, shortcuts=tuple(ConsumedKey(key.identity) for key in held)))
        failures = 0
        for key in held:
            match key:
                case HeldShortcut(request=request):
                    try:
                        self.host.request(request, down=False)
                    except Exception:
                        failures += 1
                case ConsumedKey():
                    pass
                case _:
                    assert_never(key)
        if failures:
            raise OSError(f"Failed to finish {failures} external keyboard shortcut requests.")

    def prepare_enable(self) -> None:
        """Do not resume remapping while a rejected Workspace key-up is outstanding."""
        self.host.release_owned()
        if self.host.owned:
            raise OSError("Windows still refuses Workspace key releases. Switch away from the elevated application before enabling the layout.")

    def input_failed(self, error: Exception, *, phase: str = "key") -> None:
        """Fail open, without logging or retaining traceback objects inside the hook."""
        state = self._state.get()
        earlier = state.recovery.cleanup_failures if state.recovery is not None else 0
        firmware = FirmwareKeyboard(resume_layout=False) if state.firmware is not None else None
        self._state.update(lambda state: replace(state, engine=state.engine.failed_open(), firmware=firmware, pressed=frozenset()))
        with self.guarded():
            with contextlib.suppress(Exception):
                self.release_shortcuts()
            failed = 0
            try:
                self.release_keys()
            except Exception:
                failed = 1
            with contextlib.suppress(Exception):
                self.host.release_owned()
            recovery = Recovery(failure_info(error), phase, ticks=5, cleanup_failures=earlier + failed)
            self._state.update(lambda state: replace(state, engine=replace(state.engine, shown=Indicator()), recovery=recovery))
            with contextlib.suppress(Exception):
                self.host.tell(Message.KEY_STATE, 0, 0)
                self.host.layout_state(LayoutState.OFF)
                self.host.indicate(Indicator())

    def maintenance(self) -> None:
        """Retry refused key-ups for a few ticks after a failure, then log it, outside callbacks."""
        recovery = self._state.get().recovery
        if recovery is None:
            return
        with contextlib.suppress(Exception):
            self.host.release_owned()
        with contextlib.suppress(Exception):
            if not self.engine_state.enabled:
                self.host.layout_state(LayoutState.OFF)
        ticks = recovery.ticks - 1
        if self.host.owned and ticks:
            self._state.update(lambda state: replace(state, recovery=replace(recovery, ticks=ticks)))
            return
        self._state.update(lambda state: replace(state, recovery=None))
        with contextlib.suppress(Exception):
            self.platform.record_recovery(
                {
                    **recovery.fault.details(),
                    "phase": recovery.phase,
                    "ok": False,
                    "layout_disabled": True,
                    "cleanup_failures": recovery.cleanup_failures,
                    "pending_releases": len(self.host.owned),
                }
            )

    def show_key(self, scancode: Scancode, *, down: bool) -> None:
        """Send each physical transition once; repeats and unpictured keys add nothing."""
        pressed = self._state.get().pressed
        if scancode != settings.ESCAPE and not pictured(scancode):
            return
        if (scancode in pressed) == down:
            return
        self._state.update(lambda state: replace(state, pressed=state.pressed | {scancode} if down else state.pressed - {scancode}))
        self.host.tell(Message.KEY_STATE, scancode, int(down))

    def clear_pressed(self) -> None:
        self._state.update(lambda state: replace(state, pressed=frozenset()))
        self.host.tell(Message.KEY_STATE, 0, 0)

    def hook_proc(self, code: int, wparam: int, lparam: int) -> int:
        """Called by Windows for every key, before any application sees it."""
        if code == 0 and (down := inputs.transition(wparam)) is not None:
            try:
                key = self.platform.read_key_event(lparam)
                self._state.update(lambda state: replace(state, hook_tick=key.time))
                if self.swallow(key, down=down):
                    return 1
            except Exception as error:
                # A bug must never eat the keyboard: report it and let the key through.
                with contextlib.suppress(Exception):
                    self.input_failed(error)
        return self.platform.call_next_hook(code, wparam, lparam)

    def watch_hook(self, now: int) -> hook_watch.Reinstall | None:
        """Probe a hook suspected dead; the hook's owner acts on a reinstall."""
        state = self._state.get()
        match hook_watch.assess(state.watch, state.hook_tick, now):
            case hook_watch.Probe() as probe:
                watch = hook_watch.probed(probe, now, sent=self.probe_hook())
                self._state.update(lambda state: replace(state, watch=watch))
            case hook_watch.Reinstall() as reinstall:
                self._state.update(lambda state: replace(state, watch=ANSWERED))
                return reinstall
            case watch:
                self._state.update(lambda state: replace(state, watch=watch))
        return None

    def probe_hook(self) -> bool:
        """Tap the unassigned mask key, which a live hook sees and lets through."""
        try:
            self.host.send(Key.MENU_MASK, down=True)
            self.host.send(Key.MENU_MASK, down=False)
        except OSError:
            with contextlib.suppress(Exception):
                self.host.release_owned()
            return False
        return True

    def hook_reinstalled(self, outage: hook_watch.Reinstall, now: int) -> None:
        """The dead hook dropped every key-up: end all holds and record the gap."""
        with self.guarded():
            try:
                self.release_shortcuts()
                self.release_keys()
            except Exception as error:
                self.input_failed(error, phase="hook_reinstall")
        self._state.update(
            lambda state: replace(state, shortcuts=(), owed=frozenset(), apps_held=False, engine=replace(state.engine, escape_down_at=None))
        )
        with contextlib.suppress(Exception):
            self.observe_chord()
            self.clear_pressed()
        silent = {} if outage.last_hook is None else {"hook_silent_ms": hook_watch.offset(now, outage.last_hook)}
        with contextlib.suppress(OSError):
            self.platform.record_recovery({"phase": "hook_reinstall", "ok": True, "outage_ms": hook_watch.offset(now, outage.since), **silent})

    def observe_chord(self) -> None:
        """Tell the desktop when the Charybdis starts or stops holding its Apps thumb."""
        state = self._state.get()
        held = state.firmware is not None and state.apps_held
        if held != state.chord_held:
            self._state.update(lambda state: replace(state, chord_held=held))
            self.host.tell(Message.CHORD, int(held), 0)

    def observe_window(self) -> HookState:
        """Poll the foreground window; only a change costs a title read, for the window switcher."""
        state = self._state.get()
        window = self.platform.foreground()
        if window == state.window:
            return state
        switcher = self.platform.title(window) == components.SWITCHER_TITLE
        return self._state.update(lambda state: replace(state, window=window, switcher=switcher))

    def swallow(self, key: inputs.KeyEvent, *, down: bool) -> bool:
        """True if the original key should be blocked."""
        state = self._state.get()
        if state.firmware is None and not state.busy and key.extra != Origin.LAYOUT:
            state = self.observe_window()
        kind = route(key, state, down=down)
        if kind in (Route.NATIVE, Route.EXTENDED, Route.LAYOUT) and owes(key, state, down=down):
            self._state.update(lambda state: replace(state, owed=state.owed | {identity(key)}))
        match kind:
            case Route.OWN | Route.NATIVE:
                return False
            case Route.APPS_THUMB:
                self._state.update(lambda state: replace(state, apps_held=down))
                self.observe_chord()
                return True
            case Route.SHORTCUT_HELD:
                if not down:
                    self.finish_shortcut(identity(key))
                return True
            case Route.SHORTCUT:
                if request := shortcut(key.vk, apps_held=state.apps_held):
                    self._state.update(lambda state: replace(state, shortcuts=(*state.shortcuts, HeldShortcut(identity(key), request))))
                    self.host.request(request, down=True)
                return True
            case Route.FIRMWARE:
                # The Charybdis owns ordinary keys: remember its native downs so their ups pass after unplugging.
                if physical(key) and key.extra != Origin.DESKTOP:
                    self._state.update(lambda state: replace(state, owed=state.owed | {identity(key)} if down else state.owed - {identity(key)}))
                return False
            case Route.OWED_UP:
                self._state.update(lambda state: replace(state, owed=state.owed - {identity(key)}))
                return False
            case Route.EXTENDED:
                return state.engine.enabled
            case Route.LAYOUT:
                with self.guarded():
                    verdict = self.layout_key(key, down=down)
                match verdict:
                    case Verdict.PASS:
                        return False
                    case Verdict.SWALLOW:
                        return True
                    case Verdict.QUIT:
                        self.platform.post_quit()
                        return True
            case _:
                assert_never(kind)

    def finish_shortcut(self, held_identity: int) -> None:
        """A captured shortcut key came up: end its request, if it still has one."""
        held = next(item for item in self._state.get().shortcuts if item.identity == held_identity)
        self._state.update(lambda state: replace(state, shortcuts=tuple(item for item in state.shortcuts if item.identity != held_identity)))
        match held:
            case HeldShortcut(request=request):
                self.host.request(request, down=False)
            case ConsumedKey():
                pass
            case _:
                assert_never(held)

    def layout_key(self, key: inputs.KeyEvent, *, down: bool) -> Verdict:
        """One key through the engine, with the overlay told of physical transitions."""
        was_enabled = self.engine_state.enabled
        scancode = Scancode(key.scancode)
        if not was_enabled and key.scancode == settings.ESCAPE and not down:
            self.prepare_enable()
        if was_enabled and physical(key):
            self.show_key(scancode, down=down)
        verdict = self.step_keys(lambda keys: engine.on_key(keys, self.host, scancode, down=down, now=key.time))
        if self.engine_state.enabled != was_enabled or verdict is Verdict.QUIT:
            self.clear_pressed()
        return verdict


def run() -> Exit:
    """Blocks until the layout quits."""
    lock = system.create_lock(LOCK_NAME)
    if lock is None:
        return Exit.ALREADY_RUNNING
    window = windows.create_hidden(components.LAYOUT.window.title)  # receives control requests from the assistant and keeper
    with contextlib.suppress(OSError):  # without it the hook still works, only more slowly under load
        system.keep_responsive()
    try:
        keyboard = Keyboard.open()
        keyboard.update_devices()
        hook = inputs.set_keyboard_hook(keyboard.hook_proc)
        if hook is None:
            return Exit.HOOK_REFUSED
        with contextlib.suppress(OSError):  # without raw input the hook just goes unwatched
            keyboard_devices.watch_input(window)
        languages = open_languages(firmware_connected=keyboard.state.firmware is not None)
        return serve(keyboard, hook, languages)
    finally:
        keyboard_devices.stop_watching_input()
        windows.destroy(window)
        system.release_lock(lock)


def serve(keyboard: Keyboard, hook: inputs.Hook, languages: keyboard_language.KeyboardLanguages | None) -> Exit:
    """Run the message loop, then remove whichever hook is installed by then."""
    outcome = Exit.QUIT
    language_timer = system.set_timer(200)
    layout_state: LayoutState = LayoutState.ON if keyboard.engine_state.enabled else LayoutState.OFF
    keyboard.host.layout_state(layout_state)
    # Nothing here creates reference cycles, so the cycle collector has nothing to
    # do; turning it off means it can never pause the hook mid-keypress.
    gc.collect()
    gc.freeze()
    gc.disable()
    try:
        # Windows only delivers hook calls and timer ticks while this loop waits.
        for message in system.messages():
            if message.message == system.WindowMessage.INPUT:
                keyboard.raw_key(message.time)
            elif message.message == system.WindowMessage.TIMER:
                if message.wparam == language_timer:
                    maintain_keyboard(keyboard, languages)
                    if outage := keyboard.watch_hook(system.tick_count()):
                        if not (replacement := replace_hook(keyboard, hook, outage)):
                            outcome = Exit.HOOK_REFUSED
                            break
                        hook = replacement
                else:
                    try:
                        keyboard.timeout(message.wparam)
                    except Exception as error:
                        keyboard.input_failed(error, phase="tap_hold_timer")
            elif message.message == components.LAYOUT.quit_message:
                break
            else:
                keyboard.on_message(message.message)
    finally:
        inputs.remove_hook(hook)
        system.kill_timer(language_timer)
        if languages is not None:
            with contextlib.suppress(OSError):
                languages.close()
        release_keyboard(keyboard)
        gc.enable()
    return outcome


def replace_hook(keyboard: Keyboard, dead: inputs.Hook, outage: hook_watch.Reinstall) -> inputs.Hook | None:
    """Install the replacement before removing the old hook, so no key goes unhooked."""
    replacement = inputs.set_keyboard_hook(keyboard.hook_proc)
    if replacement is not None:
        inputs.remove_hook(dead)
        keyboard.hook_reinstalled(outage, system.tick_count())
    return replacement


def maintain_keyboard(keyboard: Keyboard, languages: keyboard_language.KeyboardLanguages | None) -> None:
    """Refresh device policy before applying the foreground language, outside hooks."""
    keyboard.maintenance()
    with contextlib.suppress(OSError):
        keyboard.update_devices()
    if languages is not None:
        # Elevated windows may refuse this request. Keep the hook independent.
        with contextlib.suppress(OSError):
            languages.enforce(enabled=keyboard.engine_state.enabled, firmware_connected=keyboard.state.firmware is not None)


def show_error(message: str) -> None:
    system.error_box(message, "Workspace keyboard")


def release_keyboard(keyboard: Keyboard) -> None:
    keyboard.clear_pressed()
    try:
        keyboard.release_shortcuts()
        keyboard.release_keys()
    except Exception as error:
        keyboard.input_failed(error, phase="shutdown")
    keyboard.host.release_owned()
    keyboard.maintenance()
    keyboard.host.layout_state(LayoutState.QUIT)


def open_languages(*, firmware_connected: bool = False) -> keyboard_language.KeyboardLanguages | None:
    languages: keyboard_language.KeyboardLanguages | None = None
    try:
        languages = keyboard_language.KeyboardLanguages.load()
        languages.enforce(enabled=True, firmware_connected=firmware_connected)
    except OSError:
        traceback.print_exc()
    return languages
