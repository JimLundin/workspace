"""Detect selecting unrelated keyboards, losing the device across USB ports, or misreading its shortcuts."""

from keyboard.firmware import connected, shortcut


def test_only_the_configured_firmware_keyboard_suspends_remapping() -> None:
    other = (r"\\?\HID#VID_1050&PID_0407&MI_00#yubikey", r"\\?\HID#INTC816&COL01#laptop")
    assert not connected(other)
    for path in (r"\\?\HID#VID_A8F8&PID_1832&MI_00#port-one", r"\\?\hid#vid_a8f8&pid_1832&mi_00#port-two"):
        assert connected((*other, path))
    assert not connected((r"\\?\HID#VID_A8F8&PID_1833&MI_00#other-product",))


def test_without_the_apps_thumb_and_for_unassigned_keys_keys_keep_their_meaning() -> None:
    # Defects: a key is taken without the Apps thumb held, an unassigned letter
    # or punctuation is swallowed, or Tab gets a chord though the Charybdis holds it for Apps.
    for vk in (0x09, 0xDB, 0x31):
        assert shortcut(vk, apps_held=True) is None
    for vk in (ord("H"), ord("J"), ord("Q")):
        assert shortcut(vk, apps_held=False) is None
