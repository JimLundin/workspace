"""The message protocol both programs share."""

from protocol import Request, Slot, Tool, decode, decode_indicator, encode, encode_indicator, reaching
from tests.layouts import APPS

# ---- protocol --------------------------------------------------------------------------


def test_tools_and_slots_round_trip() -> None:
    # Defect: a request decodes as another tool or slot than the one sent.
    requests: list[Request] = [*list(Tool), *(Slot(index) for index in range(10))]
    for request in requests:
        assert decode(encode(request)) == request


def test_unknown_codes_decode_to_nothing() -> None:
    # Defect: a code no tool has is taken for one.
    assert decode(0) is None
    assert decode(999) is None


def test_a_slot_reaches_the_app_in_it_and_an_empty_slot_nothing() -> None:
    # Defects: a slot reaches the wrong app, or a slot past the last app reaches one anyway.
    assert reaching(Slot(1), APPS) == APPS[1]
    assert reaching(Slot(len(APPS)), APPS) is None
    assert reaching(Tool.ZOOM, APPS) is Tool.ZOOM


def test_indicator_round_trips() -> None:
    for layer in range(6):
        for caps in (False, True):
            assert decode_indicator(encode_indicator(layer, caps_word=caps)) == (layer, caps)
