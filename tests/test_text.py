"""What the assistant types, made safe and tidy."""

from assistant.text import typed_text
from winapi.shapes import require_input_count, utf16_units


def test_typed_text_never_contains_a_newline() -> None:
    # A newline would press Enter, and in a terminal run whatever was dictated.
    assert typed_text("git status\nrm -rf build\r\n") == "git status rm -rf build "


def test_typed_text_collapses_whitespace_and_drops_control_characters() -> None:
    assert typed_text("  hej\t\tdå \x1b[2J ") == "hej då [2J "


def test_typed_text_of_nothing_is_nothing() -> None:
    assert typed_text(" \n ") == ""


def test_utf16_units() -> None:
    assert utf16_units("aå") == [0x61, 0xE5]
    assert utf16_units("😀") == [0xD83D, 0xDE00]  # outside the BMP: a surrogate pair


def test_rejected_and_partial_input_are_reported() -> None:
    # Dictation must not report text as typed when Windows accepted none or only part of it.
    for sent in (0, 1):
        try:
            require_input_count(sent, 2)
        except OSError as error:
            assert str(sent) in str(error)
        else:
            raise AssertionError("incomplete input must fail")
    require_input_count(2, 2)
