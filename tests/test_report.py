"""The usage report knows every feature, so it can list the ones never used."""

from desktop_ui.report import known_features


def test_known_features_cover_both_programs() -> None:
    known = set(known_features())
    assert {"assistant/dictate", "assistant/app:terminal", "assistant/agent"} <= known
    assert {"layout/nav:left", "layout/sym:&", "layout/hold:shift", "layout/layer:apps", "layout/snippet:,,date"} <= known
    assert {"layout/caps_word", "layout/layer_lock"} <= known
    assert not any(name.endswith(":nothing") for name in known)
