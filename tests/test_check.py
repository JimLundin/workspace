import sys

from scripts.check import windows_only


def test_a_missing_native_dependency_is_excused_only_off_windows() -> None:
    assert windows_only(ModuleNotFoundError("No module named 'PySide6'")) is (
        sys.platform != "win32"
    )
    assert not windows_only(
        ModuleNotFoundError("No module named 'no_such_thing'")
    )
    assert not windows_only(RuntimeError("PySide6 initialization failed"))
