"""The message protocol both programs share."""

from protocol import App, Installed, Request, Tool, decode, decode_indicator, encode, encode_indicator
from tests.layouts import APPS

# ---- protocol --------------------------------------------------------------------------


def test_tools_and_apps_round_trip() -> None:
    requests: list[Request] = [*list(Tool), *APPS]
    for request in requests:
        assert decode(encode(request, APPS), APPS) == request


def test_unknown_codes_decode_to_nothing() -> None:
    assert decode(0, APPS) is None
    assert decode(999, APPS) is None
    assert decode(1000 + len(APPS), APPS) is None


def test_an_app_not_in_the_list_cannot_be_sent() -> None:
    stranger = App("stranger", Installed("stranger.exe", "stranger.exe"))
    try:
        encode(stranger, APPS)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_indicator_round_trips() -> None:
    for layer in range(6):
        for caps in (False, True):
            assert decode_indicator(encode_indicator(layer, caps_word=caps)) == (layer, caps)
