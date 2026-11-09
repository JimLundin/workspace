"""Windows glue: installs a low-level keyboard hook, feeds keys to the engine,
sends the results, and runs the message loop. Every request, what the desktop
shows (layer, chord, pressed keys, the Windows-key tap) and the layout's state
go to the desktop's control window. Win32 is reached only through the typed
bindings in `winapi`.
"""

import contextlib
import gc
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Final, Protocol, assert_never

import usage
from cell import Cell
from components import DESKTOP, LAYOUT, Window
from config import APPS
from diagnostics import FailureInfo, failure_info
from keyboard import hook_watch
from keyboard.engine import QUIET, Engine, EngineState, Indicator, Signal, UnreleasedError, Verdict
from keyboard.firmware import APPS_KEY, CapturedKey, ConsumedKey, FirmwareKeyboard, HeldShortcut, connected, shortcut
from keyboard.layout import ESCAPE, SLOTS, TAPPING_TERM_MS, Key, Mod, Scancode, Unmapped, native_control
from keyboard.windows_key import WindowsKeyTap
from protocol import (
    LAYOUT_MAGIC,
    MAGIC,
    SWITCHER_TITLE,
    WM_CHORD,
    WM_INDICATOR,
    WM_KEY_STATE,
    WM_LAYOUT_STATE,
    WM_QUERY_LAYOUT_STATE,
    WM_REQUEST,
    WM_TOGGLE_LAYOUT,
    WM_WINDOWS_KEY_TAP,
    LayoutState,
    Request,
    encode,
    encode_indicator,
)
from usage import Detail
from winapi import inputs, keyboard_devices, keyboard_language, system, windows
from winapi.shapes import Point

LOCK_NAME: Final = "Local\\keyboard"
"""Name of the lock that stops a second copy from running in this Windows session."""
USAGE_FLUSH_MS: Final = 10 * 60 * 1000
"""How often usage counts are written to the usage log."""


class KeyboardSystem(Protocol):
    """Native input, observation and delivery owned by the keyboard process."""

    def send_key(self, key: Key | Mod, *, down: bool) -> None: ...
    def cursor_position(self) -> Point: ...
    def keyboard_devices(self) -> tuple[str, ...]: ...
    def foreground(self) -> int: ...
    def title(self, hwnd: int) -> str: ...
    def read_key_event(self, lparam: int) -> inputs.KeyEvent: ...
    def call_next_hook(self, code: int, wparam: int, lparam: int) -> int: ...
    def find_window(self, window: Window) -> int | None: ...
    # HWND and its complete native message are one fixed delivery contract.
    def post_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> bool: ...
    def set_timer(self, ms: int) -> int: ...
    def kill_timer(self, timer: int) -> None: ...
    def beep(self, sound: int) -> None: ...
    def type_text(self, text: str) -> None: ...
    def record_recovery(self, details: Mapping[str, Detail]) -> None: ...
    def record_counts(self, counts: Mapping[str, int]) -> None: ...
    def post_quit(self) -> None: ...


@dataclass(frozen=True, slots=True)
class NativeKeyboardSystem:
    """The live Windows adapter; constructing it starts no hook or timer."""

    def send_key(self, key: Key | Mod, *, down: bool) -> None:
        flags = (0 if down else inputs.KEYEVENTF_KEYUP) | (inputs.KEYEVENTF_EXTENDEDKEY if key.extended else 0)
        # Some programs consume the scancode, from Windows' own layout table.
        inputs.send_key(key.vk, inputs.scancode_for(key.vk), flags, LAYOUT_MAGIC)

    # Bind native observations directly: the hook avoids extra Python forwarding
    # calls while callers still depend on KeyboardSystem, never module globals.
    cursor_position = staticmethod(inputs.cursor_position)
    keyboard_devices = staticmethod(keyboard_devices.names)
    foreground = staticmethod(windows.foreground)
    title = staticmethod(windows.title)
    read_key_event = staticmethod(inputs.read_key_event)
    call_next_hook = staticmethod(inputs.call_next_hook)

    def find_window(self, window: Window) -> int | None:
        return windows.find(window.title)

    # Preserve HWND and the native message's three scalar fields at this adapter.
    def post_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> bool:
        return system.post_message(hwnd, message, wparam, lparam)

    set_timer = staticmethod(system.set_timer)
    kill_timer = staticmethod(system.kill_timer)
    beep = staticmethod(system.beep)

    def type_text(self, text: str) -> None:
        inputs.type_text(text, LAYOUT_MAGIC)

    def record_recovery(self, details: Mapping[str, Detail]) -> None:
        usage.record("layout", "input_recovery", details)

    def record_counts(self, counts: Mapping[str, int]) -> None:
        usage.record_counts("layout", counts)

    post_quit = staticmethod(system.post_quit)


@dataclass(frozen=True, slots=True)
class _Hosted:
    found: int | None = None
    """The desktop's control window, once found."""
    counts: frozendict[str, int] = frozendict()
    """Feature uses since the last flush."""
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
        return self.platform.set_timer(TAPPING_TERM_MS)

    def stop_timer(self, timer: int) -> None:
        self.platform.kill_timer(timer)

    def signal(self, signal: Signal) -> None:
        match signal:
            case Signal.ON:
                self.platform.beep(system.MB_OK)
                self.layout_state(LayoutState.ON)
            case Signal.OFF:
                self.platform.beep(system.MB_ICONHAND)
                self.layout_state(LayoutState.OFF)
            case Signal.CAPS_WORD:
                self.platform.beep(system.MB_ICONASTERISK)

    def request(self, request: Request, *, down: bool) -> None:
        # The desktop's availability doesn't own remapping. Never replay a missed
        # press after reconnecting: it could start an unwanted action.
        if not self.tell(WM_REQUEST, encode(request, APPS), int(down)) and down:
            self.platform.beep(system.MB_ICONHAND)

    def type_text(self, text: str) -> None:
        self.platform.type_text(text)

    def used(self, feature: str) -> None:
        counts = self._state.get().counts
        self._state.set(replace(self._state.get(), counts=counts | {feature: counts.get(feature, 0) + 1}))

    def indicate(self, indicator: Indicator) -> None:
        layer: int = indicator.layer.value if indicator.layer else 0
        self.tell(WM_INDICATOR, encode_indicator(layer, locked=indicator.locked, caps_word=indicator.caps_word), 0)
        if indicator.chord != self._state.get().chord:
            self._state.set(replace(self._state.get(), chord=indicator.chord))
            self.tell(WM_CHORD, int(indicator.chord), 0)

    def tell(self, message: int, wparam: int, lparam: int) -> bool:
        """Posts to the desktop's window; nothing happens if it isn't running."""
        for _ in range(2):  # a cached window may be gone (the desktop restarted): look again
            handle = self.found
            if handle is None:
                handle = self.platform.find_window(DESKTOP.window)
                if handle is None:
                    return False
                self.remember_window(handle)
            if self.platform.post_message(handle, message, wparam, lparam):
                return True
            self.remember_window(None)
        return False

    def layout_state(self, state: LayoutState) -> None:
        """The desktop follows the layout: it shows it, and dictation stops capture when it's off."""
        self.tell(WM_LAYOUT_STATE, state.value, 0)

    def flush_usage(self) -> None:
        counts = self._state.get().counts
        self._state.set(replace(self._state.get(), counts=frozendict()))
        with contextlib.suppress(OSError):  # the log is a convenience: never let it stop the keyboard
            self.platform.record_counts(counts)


class Exit(Enum):
    QUIT = auto()
    """Quit normally (the escape key was held, or the assistant asked)."""
    ALREADY_RUNNING = auto()
    HOOK_REFUSED = auto()
    """Windows refused the keyboard hook."""


@dataclass(frozen=True, slots=True)
class _Hooked:
    pointer: Point
    foreground: int = 0
    picker_active: bool = False
    pressed: frozenset[Scancode] = frozenset()
    """Physical keys for the overlay, independent of delayed tap/hold decisions."""
    native_releases: frozenset[int] = frozenset()
    shortcuts: tuple[CapturedKey, ...] = ()
    """Ownership of firmware shortcut presses, including ups after unplug."""
    apps_held: bool = False
    """The firmware keyboard holds its Tab thumb, which sends Right Alt for Apps."""
    chord_held: bool = False
    """The assistant was last told the firmware keyboard holds the chord modifiers."""
    busy: bool = False
    """Set while the engine runs; a re-entrant call lets its key through."""
    fault: FailureInfo | None = None
    fault_phase: str = "key"
    firmware: FirmwareKeyboard | None = None
    """The firmware keyboard's suspension of the layout, while it is plugged in."""
    recovery_errors: int = 0
    recovery_ticks: int = 0
    hook_tick: int | None = None
    """The newest key time the hook has seen; the hook's only watchdog cost."""
    watch: hook_watch.Watch = hook_watch.Answered.ANSWERED
    windows_key: WindowsKeyTap = field(default_factory=WindowsKeyTap)
    engine: EngineState = field(default_factory=EngineState)
    """The layout engine's state: each key, timer and toggle returns the next one."""
    """Bare Windows-key taps toggle the assistant's taskbar."""


@dataclass(frozen=True, slots=True)
class Keyboard:
    """The engine, plus what the hook callback needs around it. Only the hook thread runs it."""

    platform: KeyboardSystem
    engine: Engine
    host: WinHost
    _state: Cell[_Hooked]

    @classmethod
    def open(cls, platform: KeyboardSystem | None = None) -> Keyboard:
        system = platform if platform is not None else NativeKeyboardSystem()
        return cls(system, Engine(), WinHost(system), Cell(_Hooked(system.cursor_position())))

    @property
    def state(self) -> _Hooked:
        return self._state.get()

    def restore(self, state: _Hooked) -> None:
        """Put the keyboard in a given state: tests use it to start mid-gesture."""
        self._state.set(state)

    @property
    def engine_state(self) -> EngineState:
        return self._state.get().engine

    def set_keys(self, keys: EngineState) -> None:
        self._state.set(replace(self._state.get(), engine=keys))

    def step_keys(self, step: Callable[[EngineState], EngineState]) -> None:
        """Run one engine step and keep the state it returns, including after a refused cleanup."""
        try:
            keys = step(self.engine_state)
        except UnreleasedError as error:
            self.set_keys(error.state)
            raise
        self.set_keys(keys)

    def release_keys(self) -> None:
        self.step_keys(lambda keys: self.engine.release_all(keys, self.host))

    def timeout(self, timer: int) -> None:
        """A tapping-term timer fired."""
        self.step_keys(lambda keys: self.engine.timeout(keys, self.host, timer))

    def engine_key(self, scancode: Scancode, *, down: bool, now: int) -> Verdict:
        try:
            keys, verdict = self.engine.on_key(self.engine_state, self.host, scancode, down=down, now=now)
        except UnreleasedError as error:
            self.set_keys(error.state)
            raise
        self.set_keys(keys)
        return verdict

    def raw_key(self, at: int) -> None:
        """Raw input saw a key at `at`: the hook watchdog's evidence that keys still arrive."""
        self._state.set(replace(self._state.get(), watch=hook_watch.keyboard_input(self._state.get().watch, at)))

    @property
    def foreground(self) -> int:
        return self._state.get().foreground

    @property
    def picker_active(self) -> bool:
        return self._state.get().picker_active

    @property
    def pointer(self) -> Point:
        return self._state.get().pointer

    @property
    def pressed(self) -> frozenset[Scancode]:
        return self._state.get().pressed

    @property
    def native_releases(self) -> frozenset[int]:
        return self._state.get().native_releases

    @property
    def shortcuts(self) -> tuple[CapturedKey, ...]:
        return self._state.get().shortcuts

    @property
    def apps_held(self) -> bool:
        return self._state.get().apps_held

    @property
    def chord_held(self) -> bool:
        return self._state.get().chord_held

    @property
    def busy(self) -> bool:
        return self._state.get().busy

    @property
    def fault(self) -> FailureInfo | None:
        return self._state.get().fault

    @property
    def fault_phase(self) -> str:
        return self._state.get().fault_phase

    @property
    def firmware(self) -> FirmwareKeyboard | None:
        return self._state.get().firmware

    @property
    def recovery_errors(self) -> int:
        return self._state.get().recovery_errors

    @property
    def recovery_ticks(self) -> int:
        return self._state.get().recovery_ticks

    @property
    def hook_tick(self) -> int | None:
        return self._state.get().hook_tick

    @property
    def watch(self) -> hook_watch.Watch:
        return self._state.get().watch

    @property
    def windows_key(self) -> WindowsKeyTap:
        return self._state.get().windows_key

    def on_message(self, message: int) -> None:
        """Tray requests; toggling uses the same re-entrancy guard as physical keys."""
        if message == WM_QUERY_LAYOUT_STATE:
            state = LayoutState.ON if self.engine_state.enabled else LayoutState.OFF
            self.host.layout_state(state)
            self.host.indicate(self.engine_state.shown)
            self.host.tell(WM_KEY_STATE, 0, 0)
            for scancode in sorted(self.pressed):
                self.host.tell(WM_KEY_STATE, scancode, 1)
            self.host.tell(WM_CHORD, int(self.chord_held or self.engine_state.shown.chord), 0)
        if message != WM_TOGGLE_LAYOUT or self.firmware is not None:
            return
        self._state.set(replace(self._state.get(), busy=True))
        try:
            if not self.engine_state.enabled:
                self.prepare_enable()
            self.step_keys(lambda keys: self.engine.toggle(keys, self.host))
            self.clear_pressed()
        except Exception as error:
            self.input_failed(error, phase="toggle")
        finally:
            self._state.set(replace(self._state.get(), busy=False))

    def update_devices(self) -> None:
        """Observe hotplug outside the hook, release outputs, and restore prior intent."""
        attached = connected(self.platform.keyboard_devices())
        if attached == (self.firmware is not None):
            return
        if attached:
            new_firmware = FirmwareKeyboard(resume_layout=self.engine_state.enabled)
            self._state.set(replace(self._state.get(), firmware=new_firmware))
            self._state.set(replace(self._state.get(), busy=True))
            try:
                if self.engine_state.enabled:
                    self.step_keys(lambda keys: self.engine.toggle(keys, self.host))
                self.clear_pressed()
            except Exception as error:
                self.input_failed(error, phase="firmware_keyboard")
            finally:
                self._state.set(replace(self._state.get(), busy=False))
        else:
            previous = self.firmware
            self._state.set(replace(self._state.get(), firmware=None))
            self._state.set(replace(self._state.get(), apps_held=False))
            try:
                self.observe_chord()
                self.release_shortcuts()
            except Exception as error:
                self.input_failed(error, phase="firmware_shortcut")
                return
            if previous is not None and previous.resume_layout:
                self.on_message(WM_TOGGLE_LAYOUT)

    def release_shortcuts(self) -> None:
        """End capture on unplug/failure/shutdown while retaining swallowed key-ups."""
        held = self.shortcuts
        new_shortcuts = tuple(ConsumedKey(key.identity) for key in held)
        self._state.set(replace(self._state.get(), shortcuts=new_shortcuts))
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
        self.set_keys(self.engine_state.failed_open())
        if self.firmware is not None:
            new_firmware = FirmwareKeyboard(resume_layout=False)
            self._state.set(replace(self._state.get(), firmware=new_firmware))
        self._state.set(replace(self._state.get(), pressed=frozenset()))
        new_fault = failure_info(error)
        self._state.set(replace(self._state.get(), fault=new_fault))
        self._state.set(replace(self._state.get(), fault_phase=phase))
        self._state.set(replace(self._state.get(), recovery_ticks=5))
        self._state.set(replace(self._state.get(), busy=True))
        try:
            with contextlib.suppress(Exception):
                self.release_shortcuts()
            try:
                self.release_keys()
            except Exception:
                self._state.set(replace(self._state.get(), recovery_errors=self.recovery_errors + 1))
            with contextlib.suppress(Exception):
                self.host.release_owned()
            self.set_keys(replace(self.engine_state, shown=QUIET))
            with contextlib.suppress(Exception):
                self.host.tell(WM_KEY_STATE, 0, 0)
                self.host.layout_state(LayoutState.OFF)
                self.host.indicate(QUIET)
        finally:
            self._state.set(replace(self._state.get(), busy=False))

    def maintenance(self) -> None:
        """Bounded recovery and diagnostic I/O run on timer ticks, outside callbacks."""
        if not self.recovery_ticks:
            return
        self._state.set(replace(self._state.get(), recovery_ticks=self.recovery_ticks - 1))
        with contextlib.suppress(Exception):
            self.host.release_owned()
        with contextlib.suppress(Exception):
            if not self.engine_state.enabled:
                self.host.layout_state(LayoutState.OFF)
        if self.host.owned and self.recovery_ticks:
            return
        self._state.set(replace(self._state.get(), recovery_ticks=0))
        fault = self.fault
        self._state.set(replace(self._state.get(), fault=None))
        if fault is not None:
            with contextlib.suppress(Exception):
                self.platform.record_recovery(
                    {
                        **fault.details(),
                        "phase": self.fault_phase,
                        "ok": False,
                        "layout_disabled": True,
                        "cleanup_failures": self.recovery_errors,
                        "pending_releases": len(self.host.owned),
                    }
                )
        self._state.set(replace(self._state.get(), recovery_errors=0))

    def show_key(self, scancode: Scancode, *, down: bool) -> None:
        """Send each physical transition once; repeats and unpictured keys add nothing."""
        if scancode != ESCAPE and SLOTS.get(scancode, Unmapped.FREE) is Unmapped.FREE:
            return
        if (scancode in self.pressed) == down:
            return
        if down:
            self._state.set(replace(self._state.get(), pressed=self.pressed | {scancode}))
        else:
            self._state.set(replace(self._state.get(), pressed=self.pressed - {scancode}))
        self.host.tell(WM_KEY_STATE, scancode, int(down))

    def clear_pressed(self) -> None:
        self._state.set(replace(self._state.get(), pressed=frozenset()))
        self.host.tell(WM_KEY_STATE, 0, 0)

    def hook_proc(self, code: int, wparam: int, lparam: int) -> int:
        """Called by Windows for every key, before any application sees it."""
        if code == 0 and wparam in (system.WM_KEYDOWN, system.WM_SYSKEYDOWN, system.WM_KEYUP, system.WM_SYSKEYUP):
            down = wparam in (system.WM_KEYDOWN, system.WM_SYSKEYDOWN)
            try:
                key = self.platform.read_key_event(lparam)
                self.observe_windows_key(key, down=down)
                if self.swallow(key, down=down):
                    return 1
            except Exception as error:
                # A bug must never eat the keyboard: report it and let the key through.
                with contextlib.suppress(Exception):
                    self.input_failed(error)
        return self.platform.call_next_hook(code, wparam, lparam)

    def observe_windows_key(self, key: inputs.KeyEvent, *, down: bool) -> None:
        """Record the newest key time, and tell the desktop of a bare Windows-key tap.

        Physical keys and the layout's own output (a home row Win) count; other injected input does not.
        """
        state = self._state.get()
        counted = not key.flags & inputs.LLKHF_INJECTED or key.extra == LAYOUT_MAGIC
        tap = state.windows_key.key(key.vk, down=down) if counted else state.windows_key
        self._state.set(replace(state, hook_tick=key.time, windows_key=tap))
        if counted and tap.tapped:
            self.host.tell(WM_WINDOWS_KEY_TAP, 0, 0)

    def watch_hook(self, now: int) -> hook_watch.Reinstall | None:
        """Probe a hook suspected dead; the hook's owner acts on a reinstall."""
        match hook_watch.assess(self.watch, self.hook_tick, now):
            case hook_watch.Probe() as probe:
                new_watch = hook_watch.probed(probe, now, sent=self.probe_hook())
                self._state.set(replace(self._state.get(), watch=new_watch))
            case hook_watch.Reinstall() as reinstall:
                self._state.set(replace(self._state.get(), watch=hook_watch.Answered.ANSWERED))
                return reinstall
            case watch:
                self._state.set(replace(self._state.get(), watch=watch))
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
        self._state.set(replace(self._state.get(), busy=True))
        try:
            self.release_shortcuts()
            self.release_keys()
        except Exception as error:
            self.input_failed(error, phase="hook_reinstall")
        finally:
            self._state.set(replace(self._state.get(), busy=False))
        self._state.set(replace(self._state.get(), shortcuts=()))
        self._state.set(replace(self._state.get(), native_releases=frozenset()))
        self._state.set(replace(self._state.get(), apps_held=False))
        self.set_keys(replace(self.engine_state, escape_down_at=None))
        with contextlib.suppress(Exception):
            self.observe_chord()
            self.clear_pressed()
        silent = {} if outage.last_hook is None else {"hook_silent_ms": hook_watch.offset(now, outage.last_hook)}
        with contextlib.suppress(OSError):
            self.platform.record_recovery({"phase": "hook_reinstall", "ok": True, "outage_ms": hook_watch.offset(now, outage.since), **silent})

    def firmware_key(self, key: inputs.KeyEvent, *, down: bool) -> None:
        identity = key.scancode | (0x100 if key.flags & inputs.LLKHF_EXTENDED else 0)
        if down:
            self._state.set(replace(self._state.get(), native_releases=self.native_releases | {identity}))
        else:
            self._state.set(replace(self._state.get(), native_releases=self.native_releases - {identity}))

    def observe_chord(self) -> None:
        """Tell the desktop when the firmware keyboard starts or stops holding its Apps thumb."""
        held = self.firmware is not None and self.apps_held
        if held != self.chord_held:
            self._state.set(replace(self._state.get(), chord_held=held))
            self.host.tell(WM_CHORD, int(held), 0)

    def firmware_shortcut(self, key: inputs.KeyEvent, *, down: bool) -> bool:
        """Own only explicit shortcut presses and their paired physical releases."""
        if self.firmware is not None and key.vk == APPS_KEY:
            # Held Tab is Workspace's own key: never let its Right Alt reach an application.
            self._state.set(replace(self._state.get(), apps_held=down))
            self.observe_chord()
            return True
        identity = key.scancode | (0x100 if key.flags & inputs.LLKHF_EXTENDED else 0)
        for held in self.shortcuts:
            if held.identity == identity:
                if not down:
                    new_shortcuts = tuple(item for item in self.shortcuts if item.identity != identity)
                    self._state.set(replace(self._state.get(), shortcuts=new_shortcuts))
                    match held:
                        case HeldShortcut(request=request):
                            self.host.request(request, down=False)
                        case ConsumedKey():
                            pass
                        case _:
                            assert_never(held)
                return True
        # A native key already held stays native even if the Apps thumb arrives
        # during its repeat. Only a fresh configured key starts capture.
        if (
            self.firmware is not None
            and down
            and identity not in self.native_releases
            and (chosen := shortcut(key.vk, apps_held=self.apps_held)) is not None
        ):
            new_shortcuts = (*self.shortcuts, HeldShortcut(identity, chosen))
            self._state.set(replace(self._state.get(), shortcuts=new_shortcuts))
            self.host.request(chosen, down=True)
            return True
        return False

    def swallow(self, key: inputs.KeyEvent, *, down: bool) -> bool:
        """Runs the engine on one key; True if the original key should be blocked."""
        # Workspace's generated output must reach applications unchanged.
        if self.busy or key.extra == LAYOUT_MAGIC:
            return False
        if (
            (self.firmware is not None or self.shortcuts)
            and not key.flags & inputs.LLKHF_INJECTED
            and key.extra != MAGIC
            and self.firmware_shortcut(key, down=down)
        ):
            return True
        if self.firmware is not None:
            # Firmware owns ordinary keys and the layout toggle. Only the explicit
            # Apps thumb shortcuts above reach Workspace's requests.
            # Remember native downs so their releases still pass after unplugging.
            if not key.flags & inputs.LLKHF_INJECTED and key.extra != MAGIC:
                self.firmware_key(key, down=down)
            return False
        state = self._state.get()
        foreground = self.platform.foreground()
        moved = foreground != state.foreground
        picker_active = self.platform.title(foreground) == SWITCHER_TITLE if moved else state.picker_active
        pointer = self.platform.cursor_position()
        if moved or pointer != state.pointer or key.flags & inputs.LLKHF_EXTENDED or key.extra == MAGIC:
            self.set_keys(self.engine_state.without_typed())
        if moved or pointer != state.pointer:
            self._state.set(replace(state, foreground=foreground, pointer=pointer, picker_active=picker_active))
        if (self.native_releases or not self.engine_state.enabled) and not key.flags & inputs.LLKHF_INJECTED:
            identity = key.scancode | (0x100 if key.flags & inputs.LLKHF_EXTENDED else 0)
            if not down and identity in self.native_releases:
                self._state.set(replace(self._state.get(), native_releases=self.native_releases - {identity}))
                return False
            if not self.engine_state.enabled and down and (key.scancode != ESCAPE or key.flags & inputs.LLKHF_EXTENDED):
                # A modifier pressed while disabled still needs its native key-up
                # after enabling the layout, otherwise Windows can leave it held.
                self._state.set(replace(self._state.get(), native_releases=self.native_releases | {identity}))
        if key.extra == MAGIC:
            return False
        if self.picker_active and key.vk in (0x1B, 0x0D, 0x09):
            if down and not key.flags & inputs.LLKHF_INJECTED:
                identity = key.scancode | (0x100 if key.flags & inputs.LLKHF_EXTENDED else 0)
                self._state.set(replace(self._state.get(), native_releases=self.native_releases | {identity}))
            return False
        if native_control(key.vk):
            self.set_keys(self.engine_state.without_typed())
            return False
        if key.flags & inputs.LLKHF_EXTENDED:
            # Extended keys share base scancodes with layout cells: never remap
            # numpad Enter, arrows or physical modifiers into a different binding.
            return self.engine_state.enabled
        self._state.set(replace(self._state.get(), busy=True))
        try:
            was_enabled = self.engine_state.enabled
            if not was_enabled and key.scancode == ESCAPE and not down:
                self.prepare_enable()
            if was_enabled and not key.flags & inputs.LLKHF_INJECTED:
                self.show_key(Scancode(key.scancode), down=down)
            verdict = self.engine_key(Scancode(key.scancode), down=down, now=key.time)
            if self.engine_state.enabled != was_enabled or verdict is Verdict.QUIT:
                self.clear_pressed()
        finally:
            self._state.set(replace(self._state.get(), busy=False))
        match verdict:
            case Verdict.PASS:
                return False
            case Verdict.SWALLOW:
                return True
            case Verdict.QUIT:
                self.platform.post_quit()
                return True


def run() -> Exit:
    """Blocks until the layout quits."""
    lock = system.create_lock(LOCK_NAME)
    if lock is None:
        return Exit.ALREADY_RUNNING
    window = windows.create_hidden(LAYOUT.window.title)  # receives control requests from the assistant and keeper
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
        languages = open_languages(firmware_connected=keyboard.firmware is not None)
        return serve(keyboard, hook, languages)
    finally:
        keyboard_devices.stop_watching_input()
        windows.destroy(window)
        system.release_lock(lock)


def serve(keyboard: Keyboard, hook: inputs.Hook, languages: keyboard_language.KeyboardLanguages | None) -> Exit:
    """Run the message loop, then remove whichever hook is installed by then."""
    outcome = Exit.QUIT
    language_timer = system.set_timer(200)
    flush_timer = system.set_timer(USAGE_FLUSH_MS)
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
            if message.message == keyboard_devices.WM_INPUT:
                keyboard.raw_key(message.time)
            elif message.message == system.WM_TIMER:
                if message.wparam == language_timer:
                    maintain_keyboard(keyboard, languages)
                    if (outage := keyboard.watch_hook(system.tick_count())) is not None:
                        if (replacement := replace_hook(keyboard, hook, outage)) is None:
                            outcome = Exit.HOOK_REFUSED
                            break
                        hook = replacement
                elif message.wparam == flush_timer:
                    keyboard.host.flush_usage()
                else:
                    try:
                        keyboard.timeout(message.wparam)
                    except Exception as error:
                        keyboard.input_failed(error, phase="tap_hold_timer")
            elif message.message == LAYOUT.quit_message:
                break
            else:
                keyboard.on_message(message.message)
    finally:
        inputs.remove_hook(hook)
        system.kill_timer(language_timer)
        system.kill_timer(flush_timer)
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
            languages.enforce(enabled=keyboard.engine_state.enabled, firmware_connected=keyboard.firmware is not None)


def show_error(message: str) -> None:
    system.message_box(message, "Workspace keyboard", system.MB_ICONHAND)


def release_keyboard(keyboard: Keyboard) -> None:
    keyboard.clear_pressed()
    try:
        keyboard.release_shortcuts()
        keyboard.release_keys()
    except Exception as error:
        keyboard.input_failed(error, phase="shutdown")
    keyboard.host.release_owned()
    keyboard.maintenance()
    keyboard.host.flush_usage()
    keyboard.host.layout_state(LayoutState.QUIT)


def open_languages(*, firmware_connected: bool = False) -> keyboard_language.KeyboardLanguages | None:
    languages: keyboard_language.KeyboardLanguages | None = None
    try:
        languages = keyboard_language.KeyboardLanguages.load()
        languages.enforce(enabled=True, firmware_connected=firmware_connected)
    except OSError:
        traceback.print_exc()
    return languages
