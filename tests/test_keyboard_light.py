"""What Workspace puts back when the Charybdis's backlight comes back with the screens."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from desktop_ui.keyboard_light import KeyboardLight
from usage import Detail
from winapi import via


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

    return KeyboardLight(keyboard, record)


def test_darkening_turns_the_lights_off_and_restoring_puts_back_the_effect_the_person_set() -> None:
    # Defects: restoring writes a fixed effect instead of the person's, or the lights stay off.
    keyboard = Keyboard(current=7)
    owner = light(keyboard).darken()
    assert keyboard.current == 0
    owner.restore()
    assert keyboard.current == 7


def test_darkening_twice_keeps_the_original_effect_to_restore() -> None:
    # Defect: a second darkening reads "off" and remembers it, so the lights never come back.
    keyboard = Keyboard(current=1)
    light(keyboard).darken().darken().restore()
    assert keyboard.current == 1


def test_restoring_what_was_never_darkened_leaves_the_keyboard_alone() -> None:
    # Defect: a keyboard plugged in while away gets an effect Workspace never read written to it.
    keyboard = Keyboard(current=1)
    light(keyboard).restore()
    assert keyboard.sets == []


def test_an_unplug_while_dark_does_not_carry_a_stale_effect_to_the_next_darkening() -> None:
    # Defect: a failed restore keeps the old effect and the next darkening skips reading the new setting.
    keyboard = Keyboard(current=1)
    owner = light(keyboard).darken()
    keyboard.attached = False
    owner = owner.restore()
    keyboard.attached, keyboard.current = True, 5  # Replugged: lit from its saved setting, then changed.
    owner.darken().restore()
    assert keyboard.current == 5


def test_the_effect_is_read_from_the_answer_to_the_same_request() -> None:
    # Defects: the effect is read from the wrong byte, or a refusal or another command's report counts as an answer.
    sent = via.effect_message(read=True)
    assert via.effect_reply(sent, bytes((0x08, 3, 2, 9)).ljust(32, b"\0")) == via.Effect(9)
    assert via.effect_reply(sent, bytes((0xFF, 3, 2, 9)).ljust(32, b"\0")) == via.Absent()
    assert via.effect_reply(sent, bytes((0x12, 0, 0, 9)).ljust(32, b"\0")) == via.Absent()


def test_a_restart_while_dark_never_remembers_off_as_the_persons_effect() -> None:
    # Defect: Workspace restarted while away reads the dark keyboard's 0, saves it,
    # and "restores" 0, leaving the backlight off once the person comes back.
    keyboard = Keyboard(current=0)
    owner = light(keyboard).darken()
    assert owner.restore_to is None and keyboard.sets == []
    owner.restore()
    assert keyboard.sets == []
