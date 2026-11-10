"""The hook's routing policy, as values: each rule sees only the keys the ones before it let through."""

from dataclasses import replace

from keyboard import settings
from keyboard.bindings import Bindings
from keyboard.engine import EngineState
from keyboard.firmware import ConsumedKey, FirmwareKeyboard
from keyboard.settings import APPS_KEY
from keyboard.win import HookState, Route, Routing, identity, owes, route
from protocol import Origin
from winapi.inputs import LLKHF_EXTENDED, LLKHF_INJECTED, KeyEvent

LETTER = KeyEvent(0x41, 0x1E, 0, 0, 0)
ARROW = KeyEvent(0x25, 0x4B, LLKHF_EXTENDED, 0, 0)
NUMPAD_ENTER = KeyEvent(0x0D, 0x1C, LLKHF_EXTENDED, 0, 0)
TAB = KeyEvent(0x09, 0x0F, 0, 0, 0)
ESCAPE_KEY = KeyEvent(0xC0, 0x29, 0, 0, 0)
OFF = HookState(engine=EngineState(enabled=False))
ROUTING = Routing.of(settings.LAYOUT, Bindings.of(settings.LAYOUT))


def test_our_own_output_and_keys_during_an_engine_step_are_never_routed() -> None:
    # Defects: the layout remaps its own injected keys, or a key the engine sends while it
    # runs re-enters it, even with the Charybdis connected.
    for state in (HookState(), HookState(firmware=FirmwareKeyboard(resume_layout=True))):
        assert route(replace(LETTER, extra=Origin.LAYOUT), state, ROUTING, down=True) is Route.OWN
        assert route(LETTER, replace(state, busy=True), ROUTING, down=True) is Route.OWN
    assert route(replace(LETTER, flags=LLKHF_INJECTED, extra=Origin.DESKTOP), HookState(), ROUTING, down=True) is Route.OWN


def test_a_captured_shortcut_key_stays_captured_after_the_charybdis_is_unplugged() -> None:
    # Defect: the release of a shortcut pressed before unplugging reaches the engine or an application.
    state = HookState(shortcuts=(ConsumedKey(identity(LETTER)),))
    assert route(LETTER, state, ROUTING, down=False) is Route.SHORTCUT_HELD
    connected = HookState(firmware=FirmwareKeyboard(resume_layout=True))
    assert route(KeyEvent(APPS_KEY, 0x38, LLKHF_EXTENDED, 0, 0), connected, ROUTING, down=True) is Route.APPS_THUMB
    assert route(LETTER, connected, ROUTING, down=True) is Route.FIRMWARE


def test_an_owed_key_up_passes_before_any_other_rule_can_claim_it() -> None:
    # Defects: the up of a key pressed while the layout was off is remapped or blocked
    # once it is on (an extended key is blocked while on), leaving Windows with it held.
    for key in (LETTER, NUMPAD_ENTER, TAB):
        owed = HookState(owed=frozenset({identity(key)}))
        assert route(key, owed, ROUTING, down=False) is Route.OWED_UP
    assert route(NUMPAD_ENTER, HookState(), ROUTING, down=False) is Route.EXTENDED
    assert route(LETTER, HookState(), ROUTING, down=True) is Route.LAYOUT


def test_the_switcher_keeps_its_keys_only_while_it_is_in_front() -> None:
    # Defect: Tab or Enter is remapped while the window switcher reads them, or stays native after it closes.
    assert route(TAB, HookState(switcher=True), ROUTING, down=True) is Route.NATIVE
    assert route(TAB, HookState(), ROUTING, down=True) is Route.LAYOUT
    assert route(ARROW, HookState(), ROUTING, down=True) is Route.NATIVE


def test_downs_the_layout_will_not_own_are_owed_their_up() -> None:
    # Defects: a key held while the layout is off sticks once it turns on, the escape
    # press that turns it on is owed instead of handled, or injected input is owed.
    assert owes(LETTER, OFF, ROUTING, down=True)
    assert not owes(ESCAPE_KEY, OFF, ROUTING, down=True)
    assert not owes(LETTER, OFF, ROUTING, down=False)
    assert not owes(replace(LETTER, flags=LLKHF_INJECTED), OFF, ROUTING, down=True)
    assert owes(TAB, HookState(switcher=True), ROUTING, down=True)
    assert not owes(LETTER, HookState(), ROUTING, down=True)
