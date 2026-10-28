"""Windows glue: installs a low-level keyboard hook, feeds keys to the engine,
sends the results, passes tool and app keys on to the assistant, and runs the
message loop. Win32 is reached only through the typed bindings in `winapi`.
"""

import contextlib
import gc
import traceback
from enum import Enum, auto
from typing import Final

import keeper
import usage
from config import APPS
from diagnostics import FailureInfo, failure_info
from protocol import (
    ASSISTANT_WINDOW,
    LAYOUT_MAGIC,
    LAYOUT_WINDOW,
    MAGIC,
    WM_INDICATOR,
    WM_KEY_STATE,
    WM_LAYOUT_STATE,
    WM_QUERY_LAYOUT_STATE,
    WM_QUIT_LAYOUT,
    WM_REQUEST,
    WM_TOGGLE_LAYOUT,
    LayoutState,
    Request,
    encode,
    encode_indicator,
)
from winapi import inputs, keyboard_language, system, windows

from .engine import QUIET, Engine, Indicator, Signal, Verdict
from .layout import ESCAPE, SLOTS, TAPPING_TERM_MS, VOICE_KEYS, Key, Mod, Scancode, Unmapped, native_control

LOCK_NAME: Final = "Local\\miryoku"
"""Name of the lock that stops a second copy from running in this Windows session."""
USAGE_FLUSH_MS: Final = 10 * 60 * 1000
"""How often usage counts are written to the usage log."""


class WinHost:
    """What the engine needs, done with Windows calls."""

    __slots__ = ("assistant", "counts", "owned")

    def __init__(self) -> None:
        self.assistant: int | None = None
        """The assistant's window, once found."""
        self.counts: dict[str, int] = {}
        self.owned: set[Key | Mod] = set()
        """Attempted Workspace output, retained until Windows accepts its key-up."""
        """Feature uses since the last flush."""

    def send(self, key: Key | Mod, down: bool) -> None:
        if down:
            self.owned.add(key)
        flags = (0 if down else inputs.KEYEVENTF_KEYUP) | (inputs.KEYEVENTF_EXTENDEDKEY if key.extended else 0)
        # The scancode, which some programs read, from Windows' own layout table.
        inputs.send_key(key.vk, inputs.scancode_for(key.vk), flags, LAYOUT_MAGIC)
        if not down:
            self.owned.discard(key)

    def release_owned(self) -> None:
        """Retry only our outputs, including a chord interrupted before engine ownership."""
        for key in tuple(self.owned):
            with contextlib.suppress(Exception):
                self.send(key, False)

    def start_timer(self) -> int:
        return system.set_timer(TAPPING_TERM_MS)

    def stop_timer(self, timer: int) -> None:
        system.kill_timer(timer)

    def signal(self, signal: Signal) -> None:
        match signal:
            case Signal.ON:
                system.beep(system.MB_OK)
                self.tell_assistant(WM_LAYOUT_STATE, LayoutState.ON.value, 0)
            case Signal.OFF:
                system.beep(system.MB_ICONHAND)
                self.tell_assistant(WM_LAYOUT_STATE, LayoutState.OFF.value, 0)
            case Signal.CAPS_WORD:
                system.beep(system.MB_ICONASTERISK)

    def request(self, request: Request, down: bool) -> None:
        if not self.tell_assistant(WM_REQUEST, encode(request, APPS), int(down)):
            raise OSError("The assistant could not receive a tool request. Layout disabled; restart Workspace to restore tools.")

    def type_text(self, text: str) -> None:
        inputs.type_text(text, LAYOUT_MAGIC)

    def used(self, feature: str) -> None:
        self.counts[feature] = self.counts.get(feature, 0) + 1

    def indicate(self, indicator: Indicator) -> None:
        layer: int = indicator.layer.value if indicator.layer else 0
        self.tell_assistant(WM_INDICATOR, encode_indicator(layer, indicator.locked, indicator.caps_word), 0)

    def tell_assistant(self, message: int, wparam: int, lparam: int) -> bool:
        """Posts to the assistant's window; nothing happens if it isn't running."""
        for _ in range(2):  # a cached window may be gone (the assistant restarted): look again
            if self.assistant is None:
                self.assistant = windows.find(ASSISTANT_WINDOW)
                if self.assistant is None:
                    return False
            if system.post_message(self.assistant, message, wparam, lparam):
                return True
            self.assistant = None
        return False

    def flush_usage(self) -> None:
        counts, self.counts = self.counts, {}
        with contextlib.suppress(OSError):  # the log is a convenience: never let it stop the keyboard
            usage.record_counts("layout", counts)


class Exit(Enum):
    QUIT = auto()
    """Quit normally (the escape key was held, or the assistant asked)."""
    ALREADY_RUNNING = auto()
    HOOK_REFUSED = auto()
    """Windows refused the keyboard hook."""


class Keyboard:
    """The engine, plus what the hook callback needs around it."""

    __slots__ = (
        "busy", "engine", "fault", "fault_phase", "foreground", "host", "native_releases",
        "picker_active", "pointer", "pressed", "recovery_errors", "recovery_ticks",
    )

    def __init__(self) -> None:
        self.engine = Engine()
        self.host = WinHost()
        self.foreground = 0
        self.picker_active = False
        self.pointer = inputs.cursor_position()
        self.pressed: set[Scancode] = set()
        """Physical keys for the overlay, independent of delayed tap/hold decisions."""
        self.native_releases: set[int] = set()
        self.busy = False
        self.fault: FailureInfo | None = None
        self.fault_phase = "key"
        self.recovery_errors = 0
        self.recovery_ticks = 0
        """Set while the engine runs; a re-entrant call lets its key through."""

    def on_message(self, message: int) -> None:
        """Tray requests; toggling uses the same re-entrancy guard as physical keys."""
        if message == WM_QUERY_LAYOUT_STATE:
            state = LayoutState.ON if self.engine.enabled else LayoutState.OFF
            self.host.tell_assistant(WM_LAYOUT_STATE, state.value, 0)
            self.host.indicate(self.engine.shown)
            self.host.tell_assistant(WM_KEY_STATE, 0, 0)
            for scancode in sorted(self.pressed):
                self.host.tell_assistant(WM_KEY_STATE, scancode, 1)
        if message != WM_TOGGLE_LAYOUT:
            return
        self.busy = True
        try:
            if not self.engine.enabled:
                self.prepare_enable()
            self.engine.toggle(self.host)
            self.clear_pressed()
        except Exception as error:
            self.input_failed(error, phase="toggle")
        finally:
            self.busy = False

    def prepare_enable(self) -> None:
        """Do not resume remapping while a rejected Workspace key-up is outstanding."""
        self.host.release_owned()
        if self.host.owned:
            raise OSError("Windows still refuses Workspace key releases. Switch away from the elevated application before enabling the layout.")

    def input_failed(self, error: Exception, *, phase: str = "key") -> None:
        """Fail open, without logging or retaining traceback objects inside the hook."""
        self.engine.enabled = False
        self.engine.typed = ""
        self.engine.escape_down_at = None
        self.pressed.clear()
        self.fault = failure_info(error)
        self.fault_phase = phase
        self.recovery_ticks = 5
        self.busy = True
        try:
            try:
                self.engine.release_all(self.host)
            except Exception:
                self.recovery_errors += 1
            with contextlib.suppress(Exception):
                self.host.release_owned()
            self.engine.shown = QUIET
            with contextlib.suppress(Exception):
                self.host.tell_assistant(WM_KEY_STATE, 0, 0)
                self.host.tell_assistant(WM_LAYOUT_STATE, LayoutState.OFF.value, 0)
                self.host.indicate(QUIET)
        finally:
            self.busy = False

    def maintenance(self) -> None:
        """Bounded recovery and diagnostic I/O run on timer ticks, outside callbacks."""
        if not self.recovery_ticks:
            return
        self.recovery_ticks -= 1
        with contextlib.suppress(Exception):
            self.host.release_owned()
        with contextlib.suppress(Exception):
            if not self.engine.enabled:
                self.host.tell_assistant(WM_LAYOUT_STATE, LayoutState.OFF.value, 0)
        if self.host.owned and self.recovery_ticks:
            return
        self.recovery_ticks = 0
        fault, self.fault = self.fault, None
        if fault is not None:
            with contextlib.suppress(Exception):
                usage.record("layout", "input_recovery", {
                    **fault.details(), "phase": self.fault_phase, "ok": False, "layout_disabled": True,
                    "cleanup_failures": self.recovery_errors, "pending_releases": len(self.host.owned),
                })
        self.recovery_errors = 0

    def show_key(self, scancode: Scancode, down: bool) -> None:
        """Send each physical transition once; repeats and unpictured keys add nothing."""
        if scancode != ESCAPE and scancode not in VOICE_KEYS and SLOTS.get(scancode, Unmapped.FREE) is Unmapped.FREE:
            return
        if (scancode in self.pressed) == down:
            return
        if down:
            self.pressed.add(scancode)
        else:
            self.pressed.discard(scancode)
        self.host.tell_assistant(WM_KEY_STATE, scancode, int(down))

    def clear_pressed(self) -> None:
        self.pressed.clear()
        self.host.tell_assistant(WM_KEY_STATE, 0, 0)

    def hook_proc(self, code: int, wparam: int, lparam: int) -> int:
        """Called by Windows for every key, before any application sees it."""
        if code == 0 and wparam in (system.WM_KEYDOWN, system.WM_SYSKEYDOWN, system.WM_KEYUP, system.WM_SYSKEYUP):
            down = wparam in (system.WM_KEYDOWN, system.WM_SYSKEYDOWN)
            try:
                if self.swallow(inputs.read_key_event(lparam), down):
                    return 1
            except Exception as error:
                # A bug must never eat the keyboard: report it and let the key through.
                with contextlib.suppress(Exception):
                    self.input_failed(error)
        return inputs.call_next_hook(code, wparam, lparam)

    def desktop_direction(self, key: inputs.KeyEvent, down: bool) -> bool:
        self.busy = True
        try:
            return self.engine.native_direction(self.host, Key(key.vk), down, key.time)
        finally:
            self.busy = False

    def swallow(self, key: inputs.KeyEvent, down: bool) -> bool:
        """Runs the engine on one key; True if the original key should be blocked."""
        # Workspace's generated output must reach applications unchanged.
        if self.busy or key.extra == LAYOUT_MAGIC:
            return False
        foreground = windows.foreground()
        if foreground != self.foreground:
            self.picker_active = windows.title(foreground) == "Workspace window switcher"
        pointer = inputs.cursor_position()
        if foreground != self.foreground or pointer != self.pointer or key.flags & inputs.LLKHF_EXTENDED or key.extra == MAGIC:
            self.engine.typed = ""
        self.foreground = foreground
        self.pointer = pointer
        if (self.native_releases or not self.engine.enabled) and not key.flags & inputs.LLKHF_INJECTED:
            identity = key.scancode | (0x100 if key.flags & inputs.LLKHF_EXTENDED else 0)
            if not down and identity in self.native_releases:
                self.native_releases.remove(identity)
                return False
            if not self.engine.enabled and down and (key.scancode != ESCAPE or key.flags & inputs.LLKHF_EXTENDED):
                # A modifier pressed while disabled still needs its native key-up
                # after enabling the layout, otherwise Windows can leave it held.
                self.native_releases.add(identity)
        if key.extra == MAGIC:
            return False
        if self.picker_active and key.vk in (0x1B, 0x0D, 0x09):
            if down and not key.flags & inputs.LLKHF_INJECTED:
                self.native_releases.add(key.scancode | (0x100 if key.flags & inputs.LLKHF_EXTENDED else 0))
            return False
        if 0x25 <= key.vk <= 0x28 and not key.flags & inputs.LLKHF_INJECTED and self.desktop_direction(key, down):
            return True
        if native_control(key.vk):
            self.engine.typed = ""
            return False
        if key.flags & inputs.LLKHF_EXTENDED:
            # Extended keys share base scancodes with layout cells: never remap
            # numpad Enter, arrows or physical modifiers into a different binding.
            return self.engine.enabled
        self.busy = True
        try:
            was_enabled = self.engine.enabled
            if not was_enabled and key.scancode == ESCAPE and not down:
                self.prepare_enable()
            if was_enabled and not key.flags & inputs.LLKHF_INJECTED:
                self.show_key(Scancode(key.scancode), down)
            verdict = self.engine.on_key(self.host, Scancode(key.scancode), down, key.time)
            if self.engine.enabled != was_enabled or verdict is Verdict.QUIT:
                self.clear_pressed()
        finally:
            self.busy = False
        match verdict:
            case Verdict.PASS:
                return False
            case Verdict.SWALLOW:
                return True
            case Verdict.QUIT:
                system.post_quit()
                return True


def run() -> Exit:  # noqa: PLR0915
    """Blocks until the layout quits."""
    lock = system.create_lock(LOCK_NAME)
    if lock is None:
        return Exit.ALREADY_RUNNING
    window = windows.create_hidden(LAYOUT_WINDOW)  # receives control requests from the assistant and keeper
    try:
        keyboard = Keyboard()
        hook = inputs.set_keyboard_hook(keyboard.hook_proc)
        if hook is None:
            return Exit.HOOK_REFUSED
        languages: keyboard_language.KeyboardLanguages | None = None
        try:
            languages = keyboard_language.KeyboardLanguages()
            languages.enforce(True)
        except OSError:
            traceback.print_exc()
        language_timer = system.set_timer(200)
        flush_timer = system.set_timer(USAGE_FLUSH_MS)
        keeper.ready()  # tells the keeper this version came up
        keyboard.host.tell_assistant(WM_LAYOUT_STATE, LayoutState.ON.value, 0)
        # Nothing here creates reference cycles, so the cycle collector has nothing to
        # do; turning it off means it can never pause the hook mid-keypress.
        gc.collect()
        gc.freeze()
        gc.disable()
        try:
            # Windows only delivers hook calls and timer ticks while this loop waits.
            for message in system.messages():
                if message.message == system.WM_TIMER:
                    if message.wparam == language_timer:
                        keyboard.maintenance()
                        if languages is not None:
                            # Elevated windows may refuse this request. Keep the hook independent.
                            with contextlib.suppress(OSError):
                                languages.enforce(keyboard.engine.enabled)
                    elif message.wparam == flush_timer:
                        keyboard.host.flush_usage()
                    else:
                        try:
                            keyboard.engine.timeout(keyboard.host, message.wparam)
                        except Exception as error:
                            keyboard.input_failed(error, phase="tap_hold_timer")
                elif message.message == WM_QUIT_LAYOUT:
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
            keyboard.clear_pressed()
            try:
                keyboard.engine.release_all(keyboard.host)
            except Exception as error:
                keyboard.input_failed(error, phase="shutdown")
            keyboard.host.release_owned()
            keyboard.maintenance()
            keyboard.host.flush_usage()
            keyboard.host.tell_assistant(WM_LAYOUT_STATE, LayoutState.QUIT.value, 0)
            gc.enable()
        return Exit.QUIT
    finally:
        windows.destroy(window)
        system.release_lock(lock)


def show_error(message: str) -> None:
    system.message_box(message, "Miryoku", system.MB_ICONHAND)
