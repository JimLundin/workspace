"""What Workspace puts back when the Charybdis's backlight comes back with the screens."""

from dataclasses import dataclass, field

from desktop_ui.keyboard_light import KeyboardLight
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


@dataclass(slots=True)
class Memory:
    """The kept effect, as a file on disk would keep it across a restart."""

    value: int | None = None

    def load(self) -> int | None:
        return self.value

    def save(self, value: int) -> None:
        self.value = value

    def clear(self) -> None:
        self.value = None


def light(keyboard: Keyboard, memory: Memory | None = None) -> KeyboardLight:
    return KeyboardLight.resume(keyboard, memory if memory is not None else Memory())


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


def test_a_restart_while_dark_puts_back_the_effect_the_person_set() -> None:
    # Defect: Workspace restarted while locked finds the keyboard already off, has nothing
    # to put back, and leaves the backlight dark once the person unlocks.
    keyboard, memory = Keyboard(current=7), Memory()
    light(keyboard, memory).darken()
    restarted = light(keyboard, memory)
    restarted.darken().restore()
    assert keyboard.current == 7 and memory.value is None


def test_a_keyboard_the_person_turned_off_stays_off() -> None:
    # Defect: "off" is remembered as something to put back, or a later restore writes an effect they never chose.
    keyboard, memory = Keyboard(current=0), Memory()
    light(keyboard, memory).darken().restore()
    assert keyboard.sets == [] and memory.value is None
