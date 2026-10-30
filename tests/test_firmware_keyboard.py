"""Detect selecting unrelated keyboards or losing the device across USB ports."""

from miryoku.firmware import connected


def test_only_the_configured_firmware_keyboard_suspends_remapping() -> None:
    other = (r"\\?\HID#VID_1050&PID_0407&MI_00#yubikey", r"\\?\HID#INTC816&COL01#laptop")
    assert not connected(other)
    for path in (r"\\?\HID#VID_A8F8&PID_1832&MI_00#port-one", r"\\?\hid#vid_a8f8&pid_1832&mi_00#port-two"):
        assert connected((*other, path))
    assert not connected((r"\\?\HID#VID_A8F8&PID_1833&MI_00#other-product",))
