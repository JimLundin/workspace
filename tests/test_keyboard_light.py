"""When Workspace turns the Charybdis's backlight off and on around the lock, and what it puts back."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from desktop_ui.keyboard_light import KeyboardLight, started
from usage import Detail
from winapi import session, via

LOCK = (session.WM_WTSSESSION_CHANGE, 7)
UNLOCK = (session.WM_WTSSESSION_CHANGE, 8)


@dataclass(slots=True)
class Keyboard:
    """A VIA backlight that remembers its effect, and can be unplugged."""

    current: int
    attached: bool = True
    sets: list[int] = field(default_factory=list[int])

    def effect(self) -> via.Effect | via.Absent:
        return via.Effect(self.current) if self.attached else via.Absent()

    def set_effect(self, effect: int) -> via.Effect | via.Absent:
        if not self.attached:
            return via.Absent()
        self.sets.append(effect)
        self.current = effect
        return via.Effect(effect)


def light(keyboard: Keyboard) -> KeyboardLight:
    def record(feature: str, details: Mapping[str, Detail]) -> None:
        pass

    return started(keyboard, record)


def test_lock_turns_the_lights_off_and_unlock_puts_back_the_effect_the_person_set() -> None:
    # Defects: unlock restores a fixed effect instead of the person's, or the lights stay off.
    keyboard = Keyboard(current=7)
    owner = light(keyboard)
    owner = owner.message(*LOCK)
    assert keyboard.current == 0
    owner = owner.message(*UNLOCK)
    assert keyboard.current == 7


def test_a_repeated_lock_keeps_the_original_effect_to_restore() -> None:
    # Defect: a second lock notification reads "off" and remembers it, so the lights never come back.
    keyboard = Keyboard(current=1)
    owner = light(keyboard)
    owner = owner.message(*LOCK)
    owner = owner.message(*LOCK)
    owner = owner.message(*UNLOCK)
    assert keyboard.current == 1


def test_an_unlock_without_a_darkening_leaves_the_keyboard_alone() -> None:
    # Defect: unlocking after the keyboard was plugged in during the lock writes an effect it never read.
    keyboard = Keyboard(current=1)
    owner = light(keyboard)
    owner = owner.message(*UNLOCK)
    assert keyboard.sets == []


def test_an_unplug_while_locked_does_not_carry_a_stale_effect_to_the_next_lock() -> None:
    # Defect: a failed restore keeps the old effect and the next lock skips reading the new setting.
    keyboard = Keyboard(current=1)
    owner = light(keyboard)
    owner = owner.message(*LOCK)
    keyboard.attached = False
    owner = owner.message(*UNLOCK)
    keyboard.attached, keyboard.current = True, 5  # Replugged: lit from its saved setting, then changed.
    owner = owner.message(*LOCK)
    owner = owner.message(*UNLOCK)
    assert keyboard.current == 5


def test_the_effect_is_read_from_the_answer_to_the_same_request() -> None:
    # Defects: the effect is read from the wrong byte, or a refusal or another command's report counts as an answer.
    sent = via.effect_message(read=True)
    assert via.effect_reply(sent, bytes((0x08, 3, 2, 9)).ljust(32, b"\0")) == via.Effect(9)
    assert via.effect_reply(sent, bytes((0xFF, 3, 2, 9)).ljust(32, b"\0")) == via.Absent()
    assert via.effect_reply(sent, bytes((0x12, 0, 0, 9)).ljust(32, b"\0")) == via.Absent()
