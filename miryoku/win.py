"""Windows glue: installs a low-level keyboard hook, feeds keys to the engine,
sends the results, passes tool and app keys on to the assistant, and runs the
message loop. Win32 is reached only through the typed bindings in `winapi`.
"""

import contextlib
import gc
import traceback
from collections.abc import Mapping
from enum import Enum, auto
from typing import Final, Protocol, assert_never

import usage
from components import ASSISTANT, LAYOUT, ready
from config import APPS
from diagnostics import FailureInfo, failure_info
from miryoku.engine import QUIET, Engine, Indicator, Signal, Verdict
from miryoku.firmware import CapturedKey, ConsumedKey, FirmwareKeyboard, VoiceShortcut, connected, voice_tool
from miryoku.layout import ESCAPE, SLOTS, TAPPING_TERM_MS, VOICE_KEYS, Key, Mod, Scancode, Unmapped, native_control
from protocol import (
    LAYOUT_MAGIC,
    MAGIC,
    WM_INDICATOR,
    WM_KEY_STATE,
    WM_LAYOUT_STATE,
    WM_QUERY_LAYOUT_STATE,
    WM_REQUEST,
    WM_TOGGLE_LAYOUT,
    LayoutState,
    Request,
    encode,
    encode_indicator,
)
from usage import Detail
from winapi import inputs, keyboard_devices, keyboard_language, system, windows

LOCK_NAME: Final = "Local\\miryoku"
"""Name of the lock that stops a second copy from running in this Windows session."""
USAGE_FLUSH_MS: Final = 10 * 60 * 1000
"""How often usage counts are written to the usage log."""


class KeyboardSystem(Protocol):
    """Native input, observation and delivery owned by the keyboard process."""

    def send_key(self, key: Key | Mod, *, down: bool) -> None: ...
    def cursor_position(self) -> tuple[int, int]: ...
    def keyboard_devices(self) -> tuple[str, ...]: ...
    def foreground(self) -> int: ...
    def title(self, hwnd: int) -> str: ...
    def read_key_event(self, lparam: int) -> inputs.KeyEvent: ...
    def call_next_hook(self, code: int, wparam: int, lparam: int) -> int: ...
    def find_assistant(self) -> int | None: ...
    # HWND and its complete native message are one fixed delivery contract.
    def post_message(self, hwnd: int, message: int, wparam: int, lparam: int) -> bool: ...
    def set_timer(self, ms: int) -> int: ...
    def kill_timer(self, timer: int) -> None: ...
    def beep(self, sound: int) -> None: ...
    def type_text(self, text: str) -> None: ...
    def record_recovery(self, details: Mapping[str, Detail]) -> None: ...
    def record_counts(self, counts: Mapping[str, int]) -> None: ...
    def post_quit(self) -> None: ...


class NativeKeyboardSystem:
    """The live Windows adapter; constructing it starts no hook or timer."""

    __slots__ = ()

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

    def find_assistant(self) -> int | None:
        return windows.find(ASSISTANT.window.title)

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


class WinHost:
    """What the engine needs, done with Windows calls."""

    __slots__ = ("assistant", "counts", "owned", "platform")

    def __init__(self, platform: KeyboardSystem | None = None) -> None:
        self.platform: KeyboardSystem = platform if platform is not None else NativeKeyboardSystem()
        self.assistant: int | None = None
        """The assistant's window, once found."""
        self.counts: dict[str, int] = {}
        self.owned: set[Key | Mod] = set()
        """Attempted Workspace output, retained until Windows accepts its key-up."""
        """Feature uses since the last flush."""

    def send(self, key: Key | Mod, *, down: bool) -> None:
        if down:
            self.owned.add(key)
        self.platform.send_key(key, down=down)
        if not down:
            self.owned.discard(key)

    def release_owned(self) -> None:
        """Retry only our outputs, including a chord interrupted before engine ownership."""
        for key in tuple(self.owned):
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
                self.tell_assistant(WM_LAYOUT_STATE, LayoutState.ON.value, 0)
            case Signal.OFF:
                self.platform.beep(system.MB_ICONHAND)
                self.tell_assistant(WM_LAYOUT_STATE, LayoutState.OFF.value, 0)
            case Signal.CAPS_WORD:
                self.platform.beep(system.MB_ICONASTERISK)

    def request(self, request: Request, *, down: bool) -> None:
        # Assistant availability does not own remapping. Never replay a missed
        # press after reconnecting: it could start an unwanted action.
        if not self.tell_assistant(WM_REQUEST, encode(request, APPS), int(down)) and down:
            self.platform.beep(system.MB_ICONHAND)

    def type_text(self, text: str) -> None:
        self.platform.type_text(text)

    def used(self, feature: str) -> None:
        self.counts[feature] = self.counts.get(feature, 0) + 1

    def indicate(self, indicator: Indicator) -> None:
        layer: int = indicator.layer.value if indicator.layer else 0
        self.tell_assistant(WM_INDICATOR, encode_indicator(layer, locked=indicator.locked, caps_word=indicator.caps_word), 0)

    def tell_assistant(self, message: int, wparam: int, lparam: int) -> bool:
        """Posts to the assistant's window; nothing happens if it isn't running."""
        for _ in range(2):  # a cached window may be gone (the assistant restarted): look again
            if self.assistant is None:
                self.assistant = self.platform.find_assistant()
                if self.assistant is None:
                    return False
            if self.platform.post_message(self.assistant, message, wparam, lparam):
                return True
            self.assistant = None
        return False

    def flush_usage(self) -> None:
        counts, self.counts = self.counts, {}
        with contextlib.suppress(OSError):  # the log is a convenience: never let it stop the keyboard
            self.platform.record_counts(counts)


class Exit(Enum):
    QUIT = auto()
    """Quit normally (the escape key was held, or the assistant asked)."""
    ALREADY_RUNNING = auto()
    HOOK_REFUSED = auto()
    """Windows refused the keyboard hook."""


class Keyboard:
    """The engine, plus what the hook callback needs around it."""

    __slots__ = (
        "busy",
        "engine",
        "fault",
        "fault_phase",
        "firmware",
        "foreground",
        "host",
        "native_releases",
        "picker_active",
        "platform",
        "pointer",
        "pressed",
        "recovery_errors",
        "recovery_ticks",
        "voice_shortcuts",
    )

    def __init__(self, platform: KeyboardSystem | None = None) -> None:
        self.platform: KeyboardSystem = platform if platform is not None else NativeKeyboardSystem()
        self.engine = Engine()
        self.host = WinHost(self.platform)
        self.foreground = 0
        self.picker_active = False
        self.pointer = self.platform.cursor_position()
        self.pressed: set[Scancode] = set()
        """Physical keys for the overlay, independent of delayed tap/hold decisions."""
        self.native_releases: set[int] = set()
        self.voice_shortcuts: tuple[CapturedKey, ...] = ()
        """Immutable ownership of voice voice key presses, including ups after unplug."""
        self.busy = False
        self.fault: FailureInfo | None = None
        self.fault_phase = "key"
        self.firmware: FirmwareKeyboard | None = None
        """The message-loop owner replaces this immutable suspension observation."""
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
        if message != WM_TOGGLE_LAYOUT or self.firmware is not None:
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

    def update_devices(self) -> None:
        """Observe hotplug outside the hook, release outputs, and restore prior intent."""
        attached = connected(self.platform.keyboard_devices())
        if attached == (self.firmware is not None):
            return
        if attached:
            self.firmware = FirmwareKeyboard(resume_layout=self.engine.enabled)
            self.busy = True
            try:
                if self.engine.enabled:
                    self.engine.toggle(self.host)
                self.clear_pressed()
            except Exception as error:
                self.input_failed(error, phase="firmware_keyboard")
            finally:
                self.busy = False
        else:
            previous, self.firmware = self.firmware, None
            try:
                self.release_voice_shortcuts()
            except Exception as error:
                self.input_failed(error, phase="firmware_voice")
                return
            if previous is not None and previous.resume_layout:
                self.on_message(WM_TOGGLE_LAYOUT)

    def release_voice_shortcuts(self) -> None:
        """End capture on unplug/failure/shutdown while retaining swallowed key-ups."""
        held = self.voice_shortcuts
        self.voice_shortcuts = tuple(ConsumedKey(key.identity) for key in held)
        failures = 0
        for key in held:
            match key:
                case VoiceShortcut(tool=tool):
                    try:
                        self.host.request(tool, down=False)
                    except Exception:
                        failures += 1
                case ConsumedKey():
                    pass
                case _:
                    assert_never(key)
        if failures:
            raise OSError(f"Failed to finish {failures} external keyboard voice requests.")

    def prepare_enable(self) -> None:
        """Do not resume remapping while a rejected Workspace key-up is outstanding."""
        self.host.release_owned()
        if self.host.owned:
            raise OSError("Windows still refuses Workspace key releases. Switch away from the elevated application before enabling the layout.")

    def input_failed(self, error: Exception, *, phase: str = "key") -> None:
        """Fail open, without logging or retaining traceback objects inside the hook."""
        self.engine.enabled = False
        if self.firmware is not None:
            self.firmware = FirmwareKeyboard(resume_layout=False)
        self.engine.typed = ""
        self.engine.escape_down_at = None
        self.pressed.clear()
        self.fault = failure_info(error)
        self.fault_phase = phase
        self.recovery_ticks = 5
        self.busy = True
        try:
            with contextlib.suppress(Exception):
                self.release_voice_shortcuts()
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
        self.recovery_errors = 0

    def show_key(self, scancode: Scancode, *, down: bool) -> None:
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
                if self.swallow(self.platform.read_key_event(lparam), down=down):
                    return 1
            except Exception as error:
                # A bug must never eat the keyboard: report it and let the key through.
                with contextlib.suppress(Exception):
                    self.input_failed(error)
        return self.platform.call_next_hook(code, wparam, lparam)

    def desktop_direction(self, key: inputs.KeyEvent, *, down: bool) -> bool:
        self.busy = True
        try:
            return self.engine.native_direction(self.host, Key(key.vk), down=down, now=key.time)
        finally:
            self.busy = False

    def firmware_voice(self, key: inputs.KeyEvent, *, down: bool) -> bool:
        """Own only explicit voice key presses and their paired physical releases."""
        identity = key.scancode | (0x100 if key.flags & inputs.LLKHF_EXTENDED else 0)
        for held in self.voice_shortcuts:
            if held.identity == identity:
                if not down:
                    self.voice_shortcuts = tuple(item for item in self.voice_shortcuts if item.identity != identity)
                    match held:
                        case VoiceShortcut(tool=tool):
                            self.host.request(tool, down=False)
                        case ConsumedKey():
                            pass
                        case _:
                            assert_never(held)
                return True
        # A native voice key already held stays native even if modifiers arrive
        # during its repeat. Only a fresh Ctrl+Alt letter press starts capture.
        if (
            self.firmware is not None
            and down
            and identity not in self.native_releases
            and (tool := voice_tool(key.vk, self.native_releases)) is not None
        ):
            self.voice_shortcuts = (*self.voice_shortcuts, VoiceShortcut(identity, tool))
            self.host.request(tool, down=True)
            return True
        return False

    def swallow(self, key: inputs.KeyEvent, *, down: bool) -> bool:
        """Runs the engine on one key; True if the original key should be blocked."""
        # Workspace's generated output must reach applications unchanged.
        if self.busy or key.extra == LAYOUT_MAGIC:
            return False
        if (
            (self.firmware is not None or self.voice_shortcuts)
            and not key.flags & inputs.LLKHF_INJECTED
            and key.extra != MAGIC
            and self.firmware_voice(key, down=down)
        ):
            return True
        if self.firmware is not None:
            # Firmware owns ordinary keys and the layout toggle. Only explicit
            # Ctrl+Alt letter shortcuts above reach Workspace's voice commands.
            # Remember native downs so their releases still pass after unplugging.
            if not key.flags & inputs.LLKHF_INJECTED and key.extra != MAGIC:
                identity = key.scancode | (0x100 if key.flags & inputs.LLKHF_EXTENDED else 0)
                if down:
                    self.native_releases.add(identity)
                else:
                    self.native_releases.discard(identity)
            return False
        foreground = self.platform.foreground()
        if foreground != self.foreground:
            self.picker_active = self.platform.title(foreground) == "Workspace window switcher"
        pointer = self.platform.cursor_position()
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
        if 0x25 <= key.vk <= 0x28 and not key.flags & inputs.LLKHF_INJECTED and self.desktop_direction(key, down=down):
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
                self.show_key(Scancode(key.scancode), down=down)
            verdict = self.engine.on_key(self.host, Scancode(key.scancode), down=down, now=key.time)
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
                self.platform.post_quit()
                return True


def run() -> Exit:
    """Blocks until the layout quits."""
    lock = system.create_lock(LOCK_NAME)
    if lock is None:
        return Exit.ALREADY_RUNNING
    window = windows.create_hidden(LAYOUT.window.title)  # receives control requests from the assistant and keeper
    try:
        keyboard = Keyboard()
        keyboard.update_devices()
        hook = inputs.set_keyboard_hook(keyboard.hook_proc)
        if hook is None:
            return Exit.HOOK_REFUSED
        languages = open_languages(firmware_connected=keyboard.firmware is not None)
        language_timer = system.set_timer(200)
        flush_timer = system.set_timer(USAGE_FLUSH_MS)
        ready()  # tells the keeper this version came up
        layout_state: LayoutState = LayoutState.ON if keyboard.engine.enabled else LayoutState.OFF
        keyboard.host.tell_assistant(WM_LAYOUT_STATE, layout_state.value, 0)
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
                        maintain_keyboard(keyboard, languages)
                    elif message.wparam == flush_timer:
                        keyboard.host.flush_usage()
                    else:
                        try:
                            keyboard.engine.timeout(keyboard.host, message.wparam)
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
        return Exit.QUIT
    finally:
        windows.destroy(window)
        system.release_lock(lock)


def maintain_keyboard(keyboard: Keyboard, languages: keyboard_language.KeyboardLanguages | None) -> None:
    """Refresh device policy before applying the foreground language, outside hooks."""
    keyboard.maintenance()
    with contextlib.suppress(OSError):
        keyboard.update_devices()
    if languages is not None:
        # Elevated windows may refuse this request. Keep the hook independent.
        with contextlib.suppress(OSError):
            languages.enforce(enabled=keyboard.engine.enabled, firmware_connected=keyboard.firmware is not None)


def show_error(message: str) -> None:
    system.message_box(message, "Miryoku", system.MB_ICONHAND)


def release_keyboard(keyboard: Keyboard) -> None:
    keyboard.clear_pressed()
    try:
        keyboard.release_voice_shortcuts()
        keyboard.engine.release_all(keyboard.host)
    except Exception as error:
        keyboard.input_failed(error, phase="shutdown")
    keyboard.host.release_owned()
    keyboard.maintenance()
    keyboard.host.flush_usage()
    keyboard.host.tell_assistant(WM_LAYOUT_STATE, LayoutState.QUIT.value, 0)


def open_languages(*, firmware_connected: bool = False) -> keyboard_language.KeyboardLanguages | None:
    languages: keyboard_language.KeyboardLanguages | None = None
    try:
        languages = keyboard_language.KeyboardLanguages()
        languages.enforce(enabled=True, firmware_connected=firmware_connected)
    except OSError:
        traceback.print_exc()
    return languages
