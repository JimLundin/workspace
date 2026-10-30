"""Engine tests: scripted key presses in, Windows key events out. Run anywhere
with `pytest`."""

import unittest
from dataclasses import replace

from miryoku.engine import DEFAULT_CONFIGURATION, MAX_BUFFERED, Configuration, Engine, Indicator, Signal, Verdict
from miryoku.layout import (
    AGENT,
    DICTATE_TOGGLE,
    ESCAPE,
    FUNCTION_KEYS,
    QUICK_TAP_MS,
    QUIT_HOLD_MS,
    STREAK_MS,
    TALK,
    Chord,
    Key,
    Layer,
    Mod,
    Scancode,
    TapHold,
    slot,
)
from protocol import Request, Tool

NAMES = {0xA0: "SFT", 0xA2: "CTL", 0xA4: "ALT", 0x20: "spc", 0x25: "left", 0x08: "bksp", 0xDB: "[", 0xC0: "`", 0xBE: "."}

PHYSICAL = {  # physical key by its QWERTY name
    "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06, "6": 0x07,
    "8": 0x09, "9": 0x0A, "0": 0x0B, "-": 0x0C, "=": 0x0D,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14,
    "i": 0x17, "o": 0x18, "p": 0x19, "[": 0x1A, "]": 0x1B,
    "caps": 0x3A, "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21,
    "k": 0x25, "l": 0x26, ";": 0x27, "'": 0x28, "#": 0x2B,
    "x": 0x2D, "c": 0x2E, "v": 0x2F, "m": 0x32, ",": 0x33, ".": 0x34, "/": 0x35,
}  # fmt: skip

ESC = ESCAPE
SPACEBAR = Scancode(0x39)


def sc(name: str) -> Scancode:
    return Scancode(PHYSICAL[name])


class FakeHost:
    __slots__ = ("indicated", "log", "timer", "used_features")

    def __init__(self) -> None:
        self.log: list[str] = []
        self.timer = 0
        self.used_features: list[str] = []
        self.indicated: list[str] = []

    def send(self, key: Key | Mod, *, down: bool) -> None:
        vk = key.vk
        if vk in NAMES:
            name = NAMES[vk]
        elif 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
            name = chr(vk).lower()
        else:
            name = f"{vk:#x}"
        self.log.append(("+" if down else "-") + name)

    def start_timer(self) -> int:
        self.timer += 1
        return self.timer

    def stop_timer(self, timer: int) -> None:
        pass

    def signal(self, signal: Signal) -> None:
        self.log.append(f"!{signal.name}")

    def request(self, request: Request, *, down: bool) -> None:
        name = request.name.lower() if isinstance(request, Tool) else f"app:{request.name}"
        self.log.append(f"?{name}{'+' if down else '-'}")

    def type_text(self, text: str) -> None:
        self.log.append(f"~{text}")

    def used(self, feature: str) -> None:
        self.used_features.append(feature)

    def indicate(self, indicator: Indicator) -> None:
        parts = [indicator.layer.name.lower()] if indicator.layer else []
        parts += ["locked"] * indicator.locked + ["caps"] * indicator.caps_word
        self.indicated.append(" ".join(parts) or "-")


class Harness:
    __slots__ = ("e", "h", "now")

    def __init__(self, configuration: Configuration = DEFAULT_CONFIGURATION) -> None:
        self.e = Engine(configuration=configuration)
        self.h = FakeHost()
        self.now = 0

    def key(self, scancode: Scancode, *, down: bool, now: int) -> Verdict:
        return self.e.on_key(self.h, scancode, down=down, now=now)

    def at(self, ms: int) -> Harness:
        self.now = ms
        return self

    def d(self, name: str) -> None:
        self.key(sc(name), down=True, now=self.now)

    def u(self, name: str) -> None:
        self.key(sc(name), down=False, now=self.now)

    def tap(self, name: str) -> None:
        self.d(name)
        self.u(name)

    def timeout_last(self) -> None:
        """Fire the most recently started timer."""
        self.e.timeout(self.h, self.h.timer)

    def take(self) -> str:
        log, self.h.log = self.h.log, []
        return " ".join(log)


def both_shifts(t: Harness) -> None:
    """Hold both Shift keys (t and n) past the tapping term."""
    t.d("r")
    t.d("o")
    t.timeout_last()  # t: Shift; n now undecided
    t.timeout_last()  # n: Shift too
    t.u("o")
    t.u("r")
    t.take()


# ---- basics ----------------------------------------------------------------
def test_plain_letters() -> None:
    t = Harness()
    for name in ("t", "2", "4"):
        t.tap(name)
    assert t.take() == "+g -g +q -q +f -f"


def test_home_row_tap() -> None:
    t = Harness()
    t.tap("r")
    assert t.take() == "+t -t"


def test_roll_is_two_taps() -> None:
    t = Harness()
    t.d("r")
    t.d("i")
    t.u("r")
    t.u("i")
    assert t.take() == "+t -t +m -m"


def test_hold_shift() -> None:
    t = Harness()
    t.d("r")
    t.tap("8")
    t.u("r")  # t + j (other hand)
    assert t.take() == "+SFT +j -j -SFT"


def test_timeout_hold() -> None:
    t = Harness()
    t.d("e")
    t.timeout_last()
    t.tap("caps")
    t.u("e")
    assert t.take() == "+CTL +z -z -CTL"


def test_nav_layer() -> None:
    t = Harness()
    t.d("c")
    t.tap("o")
    t.tap("0")
    t.u("c")
    assert t.take() == "+left -left +CTL +c -CTL -c"


def test_space_tap() -> None:
    t = Harness()
    t.tap("c")
    assert t.take() == "+spc -spc"


def test_num_layer() -> None:
    t = Harness()
    t.d(",")
    t.tap("w")
    t.tap("x")
    t.u(",")
    assert t.take() == "+4 -4 +. -."


def test_sym_layer() -> None:
    t = Harness()
    t.d("m")
    t.tap("2")
    t.tap("caps")
    t.u("m")
    assert t.take() == "+SFT +[ -SFT -[ +SFT +` -SFT -`"


def test_mod_plus_layer() -> None:
    t = Harness()
    t.d("r")
    t.d(",")
    t.tap("w")
    t.u(",")
    t.u("r")
    assert t.take() == "+SFT +4 -4 -SFT"


def test_release_all_lets_go() -> None:
    t = Harness()
    t.d("r")
    t.tap("8")
    t.take()
    t.e.release_all(t.h)
    assert t.take() == "-SFT"


def test_rejected_release_does_not_leave_other_keys_modifiers_or_voice_held() -> None:
    class RejectedRelease(FakeHost):
        def send(self, key: Key | Mod, *, down: bool) -> None:
            super().send(key, down=down)
            if not down and key is Key.A:
                raise OSError("Rejected release")

    host = RejectedRelease()
    engine = Engine()
    engine.pressed[0:3] = [Key.A, Key.B, Mod.SHIFT]
    engine.mods.counts[Mod.SHIFT] = 1
    engine.voice_held[TALK] = Tool.DICTATE
    engine.locked = Layer.NAV
    with unittest.TestCase().assertRaises(OSError):
        engine.release_all(host)
    assert host.log == ["-a", "-b", "-SFT", "?dictate-"]
    assert not engine.mods.counts and not engine.voice_held
    assert engine.layer() is None
    assert all(action is None for action in engine.pressed)


def test_rejected_modifier_release_does_not_skip_remaining_modifiers() -> None:
    class RejectedModifier(FakeHost):
        def send(self, key: Key | Mod, *, down: bool) -> None:
            super().send(key, down=down)
            if key is Mod.SHIFT:
                raise OSError("Rejected modifier")

    engine = Engine()
    engine.mods.counts.update({Mod.SHIFT: 1, Mod.CTRL: 1})
    host = RejectedModifier()
    with unittest.TestCase().assertRaises(OSError):
        engine.mods.release_all(host)
    assert host.log == ["-SFT", "-CTL"] and not engine.mods.counts


def test_unbound_keys_cannot_type_or_trigger_physical_shortcuts() -> None:
    t = Harness()
    for code in (0x01, 0x0F, 0x1C, 0x0E, 0x2A, 0x36, 0x1D, 0x38, 0x4B, 0x5D):
        assert t.key(Scancode(code), down=True, now=0) == Verdict.SWALLOW
        assert t.key(Scancode(code), down=True, now=1) == Verdict.SWALLOW
        assert t.key(Scancode(code), down=False, now=2) == Verdict.SWALLOW
    assert t.take() == ""


def test_function_row_passes_and_disabled_layout_restores_unbound_keys() -> None:
    t = Harness()
    for function in FUNCTION_KEYS:
        assert t.key(function, down=True, now=0) == Verdict.PASS
        assert t.key(function, down=False, now=1) == Verdict.PASS
    t.e.enabled = False
    for code in (0x01, 0x0F, 0x1C, 0x0E, 0x2A, 0x36, 0x1D, 0x38, 0x4B, 0x5D):
        assert t.key(Scancode(code), down=True, now=2) == Verdict.PASS
        assert t.key(Scancode(code), down=False, now=3) == Verdict.PASS
    assert t.take() == ""


def test_unused_keys_are_blocked() -> None:
    t = Harness()
    for scancode in (0x23, 0x35):  # QWERTY H and the retired rightmost thumb key
        assert t.key(Scancode(scancode), down=True, now=0) == Verdict.SWALLOW
        assert t.key(Scancode(scancode), down=False, now=1) == Verdict.SWALLOW
    assert t.take() == ""


# ---- escape key ------------------------------------------------------------
def test_escape_tap_toggles_off_and_on() -> None:
    t = Harness()
    assert t.key(ESC, down=True, now=100) == Verdict.SWALLOW
    assert t.key(ESC, down=False, now=150) == Verdict.SWALLOW
    assert t.key(sc("q"), down=True, now=200) == Verdict.PASS  # off: plain keyboard
    assert t.key(sc("q"), down=False, now=210) == Verdict.PASS
    t.key(ESC, down=True, now=300)
    t.key(ESC, down=False, now=350)
    t.tap("q")  # on again: Colemak-DH
    assert t.take() == "!OFF !ON +a -a"


def test_escape_hold_quits() -> None:
    t = Harness()
    t.key(ESC, down=True, now=1000)
    t.key(ESC, down=True, now=1000 + QUIT_HOLD_MS // 2)  # auto-repeat doesn't restart the clock
    assert t.key(ESC, down=False, now=1000 + QUIT_HOLD_MS) == Verdict.QUIT


def test_escape_survives_timer_wraparound() -> None:
    t = Harness()
    t.key(ESC, down=True, now=0xFFFF_FFFF - 100)
    assert t.key(ESC, down=False, now=50) == Verdict.SWALLOW  # 151 ms: a tap


def test_escape_switching_off_releases_held_mods() -> None:
    t = Harness()
    t.d("r")
    t.tap("8")
    t.take()  # Shift is now held
    t.key(ESC, down=True, now=0)
    t.key(ESC, down=False, now=10)
    assert t.take() == "-SFT !OFF"


def test_tray_toggle_releases_input_and_clears_the_locked_layer() -> None:
    t = Harness()
    t.d("c")
    t.timeout_last()  # Nav
    t.tap("2")  # lock Nav
    t.u("c")
    t.d("r")  # Shift
    t.d("o")  # left arrow
    t.key(TALK, down=True, now=10)
    t.take()

    t.e.toggle(t.h)
    assert t.take() == "-SFT -left ?dictate- !OFF"
    assert t.h.indicated[-1] == "-"
    assert t.h.used_features[-1] == "switch_off"
    assert t.key(sc("q"), down=True, now=20) is Verdict.PASS
    assert t.key(sc("q"), down=False, now=30) is Verdict.PASS
    t.e.toggle(t.h)
    t.tap("q")
    assert t.take() == "!ON +a -a"  # back to the base layout, not locked Nav


def test_tray_toggle_discards_pending_input_and_its_timer() -> None:
    t = Harness()
    t.d("r")  # undecided home-row modifier
    t.d("i")  # buffered on the opposite hand
    t.e.toggle(t.h)
    t.timeout_last()
    assert t.take() == "!OFF"
    t.e.toggle(t.h)
    t.tap("2")
    assert t.take() == "!ON +q -q"


def test_tray_toggle_cancels_an_escape_key_already_held() -> None:
    t = Harness()
    t.key(ESC, down=True, now=0)
    t.e.toggle(t.h)
    assert t.key(ESC, down=False, now=QUIT_HOLD_MS) is Verdict.SWALLOW
    assert t.key(sc("q"), down=True, now=QUIT_HOLD_MS + 1) is Verdict.PASS
    assert t.take() == "!OFF"


# ---- typing streak ---------------------------------------------------------
def test_streak_sends_home_row_letter_on_press() -> None:
    t = Harness()
    t.at(0).tap("t")  # g
    t.at(STREAK_MS // 2).d("w")  # r/ALT, mid-word
    assert t.take() == "+g -g +r"  # r is out before release
    t.u("w")
    assert t.take() == "-r"


def test_streak_expires() -> None:
    t = Harness()
    t.at(0).tap("t")
    t.at(STREAK_MS * 3).d("w")  # pause: a normal tap-hold again
    assert t.take() == "+g -g"
    t.tap("8")
    t.u("w")
    assert t.take() == "+ALT +j -j -ALT"


def test_each_engine_uses_its_configured_timing_boundaries() -> None:
    for milliseconds, elapsed, letter in ((0, 0, False), (1, 0, True), (1, 1, False)):
        t = Harness(replace(DEFAULT_CONFIGURATION, streak_ms=milliseconds))
        t.at(0).tap("t")
        t.take()
        t.at(elapsed).d("w")
        assert t.take() == ("+r" if letter else "")
        if not letter:
            t.timeout_last()
            assert t.take() == "+ALT"
        t.u("w")
        assert t.take() == ("-r" if letter else "-ALT")
    t = Harness(replace(DEFAULT_CONFIGURATION, quick_tap_ms=0, quit_hold_ms=1))
    t.tap("r")
    t.take()
    t.d("r")
    assert t.take() == "", "Disabling quick tap must allow the repeated key to become a hold."
    t.timeout_last()
    t.u("r")
    assert t.take() == "+SFT -SFT"
    t.key(ESC, down=True, now=0)
    assert t.key(ESC, down=False, now=1) is Verdict.QUIT


def test_streak_never_blocks_shift() -> None:
    t = Harness()
    t.at(0).tap("c")  # space
    t.at(STREAK_MS // 3).d("r")
    t.tap("8")
    t.u("r")  # Shift+j right after a space
    assert t.take() == "+spc -spc +SFT +j -j -SFT"


def test_streak_never_blocks_layers() -> None:
    t = Harness()
    t.at(0).tap("t")
    t.at(STREAK_MS // 3).d(",")
    t.tap("w")
    t.u(",")  # Num layer right after a letter
    assert t.take() == "+g -g +4 -4"


def test_streak_counts_rolled_taps() -> None:
    t = Harness()
    t.at(0).d("r")
    t.at(STREAK_MS // 4).d("w")
    t.at(STREAK_MS // 3).u("r")  # roll t -> r
    assert t.take() == "+t -t +r"  # r came out on press via the streak


def test_streak_holds_do_not_start_a_streak() -> None:
    t = Harness()
    t.at(0).d("e")
    t.timeout_last()  # Ctrl held
    t.at(50).d("w")
    t.timeout_last()  # Alt held
    t.at(70).tap("2")  # Ctrl + Alt + q
    assert t.take() == "+CTL +ALT +q -q"


# ---- capacity --------------------------------------------------------------
def test_auto_repeat_is_not_buffered() -> None:
    t = Harness()
    t.d("e")  # s/CTL, undecided
    for _ in range(100):
        t.d("8")  # j held (other hand), auto-repeating
    assert t.take() == "", "still undecided: repeats did not fill the buffer"
    t.u("e")
    assert t.take() == "+s -s +j", "tap s, then j replayed once"


def test_released_key_can_be_pressed_again_while_a_tap_hold_is_pending() -> None:
    t = Harness()
    t.d("8")  # j was held before the undecided modifier
    assert t.take() == "+j"
    t.at(STREAK_MS + 1).d("e")  # s/CTL, after the typing streak expires
    t.u("8")
    t.d("8")  # a new press, not auto-repeat of the still-unreleased output
    assert t.take() == "", "both edges wait for the tap-hold decision"
    t.u("e")
    assert t.take() == "+s -s -j +j", "the buffered release must precede the new press"
    t.u("8")
    t.u("8")  # a duplicate up must not emit another release
    assert t.take() == "-j"


def test_an_already_held_letter_repeats_while_a_modifier_is_undecided() -> None:
    t = Harness()
    t.d("8")
    assert t.take() == "+j"
    t.at(STREAK_MS + 1).d("e")
    t.d("8")
    assert t.take() == "+j"
    t.u("e")
    t.u("8")
    assert t.take() == "+s -s -j"


def test_full_buffer_decides_hold() -> None:
    # More distinct keys down than nine fingers can press: decide as a hold.
    plain = ["2", "3", "4", "5", "6", "8", "9", "0", "-", "=", "t", "i", "caps", "s", "d", "f", "k", "l", ";"]
    assert len(plain) > MAX_BUFFERED
    t = Harness()
    t.d("o")  # n/SFT (right hand); the first key, q, is on the other hand
    for name in plain:
        t.d(name)
    assert t.take().startswith("+SFT +q"), "a full buffer resolves the key as a hold"


# ---- caps word -------------------------------------------------------------
def test_caps_word_capitalises_until_space() -> None:
    t = Harness()
    both_shifts(t)
    t.tap("2")
    t.tap("3")  # q w
    assert t.take() == "+SFT +q -SFT -q +SFT +w -SFT -w"
    t.tap("c")
    t.tap("2")  # space ends it
    assert t.take() == "+spc -spc +q -q"


def test_caps_word_keeps_going_through_digits_and_underscore() -> None:
    t = Harness()
    both_shifts(t)
    t.d(",")
    t.tap("w")
    t.u(",")  # Num layer: 4
    t.d("m")
    t.tap("v")
    t.u("m")  # Sym layer: _
    t.tap("2")
    assert t.take() == "+4 -4 +SFT +0xbd -SFT -0xbd +SFT +q -SFT -q"


def test_caps_word_toggles_off_and_clears_on_switch_off() -> None:
    t = Harness()
    both_shifts(t)
    both_shifts(t)  # off again
    t.tap("2")
    assert t.take() == "+q -q"
    both_shifts(t)
    t.key(ESC, down=True, now=0)
    t.key(ESC, down=False, now=10)  # off
    t.key(ESC, down=True, now=20)
    t.key(ESC, down=False, now=30)  # on: caps word is gone
    t.tap("2")
    assert t.take() == "!OFF !ON +q -q"


def test_caps_word_signals_when_turned_on() -> None:
    t = Harness()
    t.d("r")
    t.d("o")
    t.timeout_last()
    t.timeout_last()
    assert "!CAPS_WORD" in t.take()


# ---- layer lock ------------------------------------------------------------
def test_layer_lock_keeps_nav_until_tapped_again() -> None:
    t = Harness()
    t.d("c")
    t.tap("2")
    t.u("c")  # hold Space thumb, tap lock, let go
    t.tap("o")  # still Nav: left
    assert t.take() == "+left -left"
    t.tap("2")  # lock key again: unlocked
    t.tap("o")  # base: n
    assert t.take() == "+n -n"


def test_layer_lock_on_num_and_cleared_by_escape() -> None:
    t = Harness()
    t.d(",")
    t.tap("=")
    t.u(",")  # hold Backspace thumb, tap lock (right pinky)
    t.tap("w")  # still Num: 4
    assert t.take() == "+4 -4"
    t.key(ESC, down=True, now=0)
    t.key(ESC, down=False, now=10)  # off
    t.key(ESC, down=True, now=20)
    t.key(ESC, down=False, now=30)  # on: lock is gone
    t.tap("w")
    assert t.take() == "!OFF !ON +r -r"


# ---- chordal hold ----------------------------------------------------------
def test_same_hand_roll_is_two_taps_at_once() -> None:
    t = Harness()
    t.d("e")
    t.d("4")  # s/CTL then f, same hand
    assert t.take() == "+s -s +f", "decided on the second key's press"
    t.u("4")
    t.u("e")
    assert t.take() == "-f"


def test_other_hand_key_still_gets_the_modifier() -> None:
    t = Harness()
    t.d("e")
    t.tap("8")
    t.u("e")  # Ctrl + j
    assert t.take() == "+CTL +j -j -CTL"


def test_same_hand_shortcut_works_after_holding() -> None:
    t = Harness()
    t.d("e")
    t.timeout_last()  # held past the tapping term
    t.tap("caps")
    t.u("e")  # Ctrl + z, one hand
    assert t.take() == "+CTL +z -z -CTL"


def test_layer_thumbs_are_not_affected() -> None:
    t = Harness()
    t.d("c")
    t.tap("e")
    t.u("c")  # Nav thumb (left) + left-hand Ctrl key
    assert not t.take().startswith("+spc"), "the Nav thumb was not turned into a tap"


# ---- quick tap -------------------------------------------------------------
def test_backspace_thumb_repeats_after_a_tap() -> None:
    t = Harness()
    t.at(0).tap(",")  # tap: backspace
    t.at(QUICK_TAP_MS // 2).d(",")  # again quickly and hold
    t.d(",")
    t.d(",")  # auto-repeat
    t.u(",")
    assert t.take() == "+bksp -bksp +bksp +bksp +bksp -bksp"


def test_after_a_pause_the_thumb_is_a_layer_again() -> None:
    for pause in (QUICK_TAP_MS, QUICK_TAP_MS * 2):
        t = Harness()
        t.at(0).tap(",")
        t.at(pause).d(",")
        t.tap("w")
        t.u(",")  # Num layer: 4
        assert t.take() == "+bksp -bksp +4 -4"


def test_home_row_letter_repeats_after_a_tap() -> None:
    t = Harness()
    t.at(1000).tap("r")  # t (Shift key)
    t.at(1000 + QUICK_TAP_MS // 2).d("r")
    t.d("r")
    assert t.take() == "+t -t +t +t", "held t repeats instead of becoming Shift"


# ---- modifier state -----------------------------------------------------------------


def test_quick_tap_survives_timestamp_wraparound() -> None:
    t = Harness()
    t.at(0xFFFF_FFE0).tap("r")
    assert t.take() == "+t -t"
    t.at(10).d("r")  # the timestamp wrapped, but this is still within QUICK_TAP_MS
    assert t.take() == "+t", "a quick second press repeats the letter immediately"
    t.timeout_last()  # the old tap's timer cannot turn the repeated letter into Shift
    assert t.take() == ""
    t.u("r")
    assert t.take() == "-t"


def test_held_shift_survives_a_shifted_symbol() -> None:
    t = Harness()
    t.d("r")
    t.timeout_last()  # t held: Shift
    t.d("m")
    t.tap("3")  # Sym layer: & (Shift+7); Shift is already down, so no Shift events
    t.u("m")
    t.tap("2")  # q, with Shift still held
    assert t.take() == "+SFT +7 -7 +q -q"


def test_releasing_one_of_two_ctrl_keys_keeps_ctrl() -> None:
    t = Harness()
    t.d("e")  # left Ctrl (s)
    t.d("p")  # right Ctrl (e), other hand
    t.timeout_last()
    t.timeout_last()  # both held: Ctrl goes down once
    t.u("p")  # one released: Ctrl stays down
    t.tap("8")  # Ctrl + j
    t.u("e")  # the last one released: Ctrl up
    assert t.take() == "+CTL +j -j -CTL"


# ---- chords ---------------------------------------------------------------------------


def test_tap_hold_chords_release_only_the_modifiers_they_added() -> None:
    redo = TapHold(Chord(Key.Z, frozenset({Mod.CTRL, Mod.SHIFT})), Layer.SYM)
    cell = slot(sc("2"))
    assert isinstance(cell, int)
    row = list(DEFAULT_CONFIGURATION.actions[None])
    row[cell] = redo
    t = Harness(replace(DEFAULT_CONFIGURATION, actions={**DEFAULT_CONFIGURATION.actions, None: tuple(row)}))
    t.e.press(t.h, Mod.CTRL, 0)
    assert t.take() == "+CTL"
    t.tap("2")
    assert t.take() == "+SFT +z -SFT -z"
    t.e.release(t.h, Mod.CTRL)
    assert t.take() == "-CTL"


def test_overlapping_layers_release_the_most_recent_copy_and_preserve_other_layers() -> None:
    t = Harness()
    for layer in (Layer.NAV, Layer.NUM, Layer.NAV):
        t.e.press(t.h, layer, 0)
    t.e.release(t.h, Layer.NAV)
    assert t.e.layer() is Layer.NUM
    t.tap("w")
    assert t.take() == "+4 -4"
    t.e.press(t.h, Layer.NAV, 0)
    t.e.release(t.h, Layer.NUM)  # removing a layer below the top must preserve both NAV holds
    t.e.release(t.h, Layer.NAV)
    assert t.e.layer() is Layer.NAV
    t.tap("o")
    assert t.take() == "+left -left"
    t.e.release(t.h, Layer.NAV)
    assert t.e.layer() is None


def test_held_undo_repeats_like_any_key() -> None:
    t = Harness()
    t.d("c")
    t.timeout_last()  # Nav layer held
    t.d("=")  # Undo: Ctrl + z, with z held
    t.d("=")  # auto-repeat: another Ctrl + z
    t.u("=")  # z up
    t.u("c")
    assert t.take() == "+CTL +z -CTL +CTL +z -CTL -z"


# ---- push-to-talk ----------------------------------------------------------------------


def test_voice_buttons_request_their_tool_once_per_press_with_any_modifier() -> None:
    for scancode, tool in ((TALK, "dictate"), (DICTATE_TOGGLE, "dictate_toggle"), (AGENT, "agent_voice")):
        for mods in ((), (Mod.CTRL,), (Mod.SHIFT,), (Mod.GUI,), (Mod.CTRL, Mod.SHIFT)):
            t = Harness()
            t.e.mods.counts.update(dict.fromkeys(mods, 1))
            assert t.key(scancode, down=True, now=0) is Verdict.SWALLOW
            assert t.take() == f"?{tool}+"
            assert t.key(scancode, down=True, now=30) is Verdict.SWALLOW
            assert t.take() == ""
            assert t.key(scancode, down=False, now=900) is Verdict.SWALLOW
            assert t.key(scancode, down=False, now=901) is Verdict.SWALLOW
            assert t.take() == f"?{tool}-"


def test_voice_keys_are_plain_when_disabled() -> None:
    t = Harness()
    t.e.enabled = False
    for key in (TALK, DICTATE_TOGGLE, AGENT):
        assert t.key(key, down=True, now=20) is Verdict.PASS
        assert t.key(key, down=False, now=30) is Verdict.PASS


def test_switching_off_and_quitting_release_every_voice_request() -> None:
    for quitting in (False, True):
        t = Harness()
        for key in (TALK, DICTATE_TOGGLE, AGENT):
            t.key(key, down=True, now=0)
        t.take()
        t.key(ESC, down=True, now=10)
        verdict = t.key(ESC, down=False, now=10 + (QUIT_HOLD_MS if quitting else 10))
        assert verdict is (Verdict.QUIT if quitting else Verdict.SWALLOW)
        assert t.take() == "?dictate- ?dictate_toggle- ?agent_voice-" + ("" if quitting else " !OFF")
        t.e.release_all(t.h)
        assert t.take() == ""


def test_voice_preserves_a_pending_modifier_or_layer_without_sending_it_to_the_app() -> None:
    for physical in ("e", "m"):
        t = Harness()
        t.d(physical)
        pending = t.e.pending
        t.key(TALK, down=True, now=1)
        assert t.take() == "?dictate+"
        assert t.e.pending is pending
        t.key(TALK, down=False, now=10)
        assert t.take() == "?dictate-"
        t.u(physical)
        assert t.take() == ("+s -s" if physical == "e" else "+0xd -0xd")


def test_dedicated_voice_buttons_work_on_every_layer() -> None:
    layers: list[Layer | None] = [None, *list(Layer)]
    for layer in layers:
        for key, tool in ((TALK, "dictate"), (DICTATE_TOGGLE, "dictate_toggle"), (AGENT, "agent_voice")):
            t = Harness()
            t.e.locked = layer
            t.key(key, down=True, now=0)
            assert t.take() == f"?{tool}+"
            t.e.locked = None
            t.key(key, down=False, now=300)
            assert t.take() == f"?{tool}-"


def test_f6_remains_a_native_laptop_function() -> None:
    t = Harness()
    t.key(Scancode(0x40), down=True, now=0)
    t.key(Scancode(0x40), down=True, now=10)
    t.key(Scancode(0x40), down=False, now=20)
    assert t.take() == ""


def test_apps_directions_keep_ordinary_tiling_focus_with_modifiers() -> None:
    for modifier in ("p", "o"):
        for direction, tool in (("8", Tool.TILE_FOCUS_LEFT), ("9", Tool.TILE_FOCUS_DOWN), ("0", Tool.TILE_FOCUS_UP), ("-", Tool.TILE_FOCUS_RIGHT)):
            t = Harness()
            t.d(".")
            t.timeout_last()
            t.d(modifier)
            t.tap(direction)
            t.u(modifier)
            t.u(".")
            requests = [line for line in t.h.log if line.startswith("?")]
            assert requests == [f"?{tool.name.lower()}+", f"?{tool.name.lower()}-"]
            assert t.e.layer() is None and not t.e.mods.counts


def test_apps_search_is_available_without_the_function_row() -> None:
    t = Harness()
    t.d(".")
    t.timeout_last()
    t.tap("x")
    t.u(".")
    assert t.take() == "?window_switcher+ ?window_switcher-"


def test_physical_arrows_compose_with_pending_apps_and_pair_release_after_layer_exit() -> None:
    t = Harness()
    assert not t.e.native_direction(t.h, Key.LEFT, down=True, now=0)
    t.d(".")
    assert t.e.native_direction(t.h, Key.RIGHT, down=True, now=10)
    assert t.e.native_direction(t.h, Key.RIGHT, down=True, now=20)
    t.u(".")
    assert t.e.native_direction(t.h, Key.RIGHT, down=False, now=30)
    assert t.take() == "?tile_focus_right+ ?tile_focus_right-"
    assert not t.e.desktop_held and t.e.layer() is None
    t.d(".")
    assert t.e.native_direction(t.h, Key.DOWN, down=True, now=40)
    t.e.toggle(t.h)
    assert t.take() == "?tile_focus_down+ ?tile_focus_down- !OFF"
    assert not t.e.desktop_held


# ---- tools and apps layers ---------------------------------------------------------------


def test_tools_layer_key_requests_its_tool() -> None:
    t = Harness()
    t.d("v")  # Tab thumb: Tools while held
    t.tap("9")  # Fix (right hand, top row)
    t.u("v")
    assert t.take() == "?fix+ ?fix-"


def test_hold_to_talk_tools_keep_going_while_held() -> None:
    t = Harness()
    t.d("v")
    t.timeout_last()  # Tools held
    t.d("i")  # Dictate (tidied): first key of the right home row
    t.u("v")  # letting go of the thumb first doesn't cut it short
    t.u("i")
    assert t.take() == "?dictate_clean+ ?dictate_clean-"


def test_tab_still_taps() -> None:
    t = Harness()
    t.tap("v")
    assert t.take() == "+0x9 -0x9"


def test_apps_layer_key_requests_its_app() -> None:
    t = Harness()
    t.d(".")  # Delete thumb: Apps while held
    t.tap("2")  # the first app (left hand, top row)
    t.u(".")
    assert t.take() == "?app:terminal+ ?app:terminal-"


def test_window_keys_are_on_the_apps_layer() -> None:
    t = Harness()
    t.d(".")
    t.tap("caps")  # bottom row, left: snap left
    t.u(".")
    assert t.take() == "?snap_left+ ?snap_left-"


# ---- snippets --------------------------------------------------------------------------

BACKSPACES = " ".join(["+bksp -bksp"] * 5)


def type_thx(t: Harness) -> None:
    for name in (";", ";", "r", "l", "a"):  # , , t h x
        t.tap(name)


def test_snippet_replaces_its_trigger() -> None:
    t = Harness()
    type_thx(t)
    assert t.take() == f"+0xbc -0xbc +0xbc -0xbc +t -t +h -h +x {BACKSPACES} ~Thanks! -x"
    assert "snippet:,,thx" in t.h.used_features


def test_snippets_can_include_shifted_characters() -> None:
    t = Harness(replace(DEFAULT_CONFIGURATION, snippets=(("ABC", "Expanded."),)))
    for key in (Key.A, Key.B, Key.C):
        chord = Chord(key, frozenset({Mod.SHIFT}))
        t.e.press(t.h, chord, 0)
        t.e.release(t.h, chord)
    assert "~Expanded." in t.take() and "snippet:ABC" in t.h.used_features


def test_disabled_snippets_do_not_accumulate_an_unbounded_typing_buffer() -> None:
    t = Harness(replace(DEFAULT_CONFIGURATION, snippets=()))
    for _ in range(100):
        type_thx(t)
    assert "~Thanks!" not in t.take() and not t.e.typed
    ordinary = Harness()
    type_thx(ordinary)
    assert "~Thanks!" in ordinary.take(), "One engine's configuration must not change another engine."


def test_snippet_survives_a_corrected_typo() -> None:
    t = Harness()
    for name in (";", ";", "r", "l", "s"):  # , , t h c
        t.tap(name)
    t.tap(",")  # Backspace thumb, tapped
    t.tap("a")  # x
    assert t.take().endswith(f"+x {BACKSPACES} ~Thanks! -x")


def test_snippet_is_forgotten_after_moving_the_cursor() -> None:
    t = Harness()
    t.tap(";")
    t.tap(";")
    t.d("c")  # Space thumb: Nav
    t.timeout_last()
    t.tap("o")  # Left arrow
    t.u("c")
    for name in ("r", "l", "a"):
        t.tap(name)
    assert "~" not in t.take()


# ---- usage counts ----------------------------------------------------------------------


def test_usage_counts_layer_keys_holds_and_features() -> None:
    t = Harness()
    t.d("c")
    t.timeout_last()  # Space held: Nav
    t.tap("o")  # Left
    t.u("c")
    t.d("r")
    t.timeout_last()  # Shift held
    t.u("r")
    both_shifts(t)
    assert t.h.used_features == ["layer:nav", "nav:left", "hold:shift", "hold:shift", "hold:shift", "caps_word"]


# ---- the layer indicator ---------------------------------------------------------------


def test_indicator_shows_a_held_layer_while_held() -> None:
    t = Harness()
    t.d("c")
    t.timeout_last()  # Space held: Nav
    t.tap("o")
    t.u("c")
    assert t.h.indicated == ["nav", "-"]


def test_indicator_stays_quiet_for_taps_and_typing() -> None:
    t = Harness()
    t.tap("c")  # Space, tapped
    for name in ("2", "3", "r"):
        t.tap(name)
    assert t.h.indicated == []


def test_indicator_shows_a_locked_layer_until_unlocked() -> None:
    t = Harness()
    t.d(",")
    t.timeout_last()  # Backspace held: Num
    t.tap("=")  # Lock, right top-row pinky
    t.u(",")  # still locked
    t.tap("=")  # unlock
    assert t.h.indicated == ["num", "num locked", "-"]


def test_indicator_shows_caps_word() -> None:
    t = Harness()
    both_shifts(t)
    t.tap("c")  # Space ends caps word
    assert t.h.indicated[-2:] == ["caps", "-"]


def test_switching_off_clears_the_indicator() -> None:
    t = Harness()
    t.d("c")
    t.timeout_last()
    t.key(ESC, down=True, now=0)
    t.key(ESC, down=False, now=10)
    assert t.h.indicated == ["nav", "-"]


def test_native_function_key_invalidates_partial_snippets() -> None:
    t = Harness()
    for name in (";", ";", "r"):
        t.tap(name)
    assert t.e.typed == ",,t"
    assert t.key(Scancode(0x3B), down=True, now=1) is Verdict.PASS  # F1 can change focus or open application help.
    for name in ("l", "a"):
        t.tap(name)
    assert "~Thanks!" not in t.take()
