"""The desktop's control decisions: tray menu items, the overlay preference, and window messages decoded into actions."""

from components import LAYOUT
from config import APPS
from desktop_ui.desktop_controls import (
    WM_TOOL_CHOSEN,
    ChosenTool,
    FeatureRequest,
    Menu,
    MenuState,
    PhysicalKey,
    WindowInput,
    control_event,
    menu_items,
    toggle_layout,
)
from desktop_ui.spec.tray import TRAY
from miryoku.layout import Scancode
from protocol import WM_KEY_STATE, WM_REQUEST, WM_TOGGLE_LAYOUT, LayoutState, Tool


def test_physical_key_messages_become_key_actions_with_a_reset_marker() -> None:
    """Detect native key messages routed as tools or losing their reset marker."""
    actions = tuple(control_event(WindowInput(WM_KEY_STATE, key, down), APPS) for key, down in ((0x32, 1), (0x10, 1), (0x10, 0), (0, 0)))
    assert actions == (
        PhysicalKey(Scancode(0x32), down=True),
        PhysicalKey(Scancode(0x10), down=True),
        PhysicalKey(Scancode(0x10), down=False),
        PhysicalKey(Scancode(0), down=False),
    )
    assert tuple(action.reset for action in actions if isinstance(action, PhysicalKey)) == (False, False, False, True)


class LayoutFixture:
    """Own observed layout identity and native-effect receipts for this interface."""

    def __init__(self, handle: int | None) -> None:
        self.handle = handle
        self.messages: tuple[tuple[int, int, int, int], ...] = ()
        self.timeline: tuple[str, ...] = ()

    def find_window(self, title: str) -> int | None:
        assert title == LAYOUT.window.title
        self.timeline += ("find layout",)
        return self.handle

    # The four fields belong to one native message, not independent options.
    def post(self, handle: int, message: int, wparam: int, lparam: int) -> bool:
        self.messages += ((handle, message, wparam, lparam),)
        self.timeline += ("post layout",)
        return True

    def start_timer(self, handle: int) -> int:
        assert handle == 7
        self.timeline += ("timer",)
        return 17

    def start_workers(self) -> None:
        assert self.timeline == ("timer",)
        self.timeline += ("workers",)


def test_layout_status_is_the_toggle_and_shows_its_hotkey() -> None:
    for layout in (LayoutState.ON, LayoutState.OFF):
        state = MenuState(layout=layout, overlay_enabled=True, capturing=False)
        item = menu_items(state, TRAY)[0]
        assert item.id == Menu.TOGGLE_LAYOUT.value
        assert item.text == f"Layout: {layout.name.lower()}\tTap §"
        assert item.enabled and item.checked == (layout is LayoutState.ON)
        effects = LayoutFixture(2)
        assert toggle_layout(effects)
        assert effects.messages == ((2, WM_TOGGLE_LAYOUT, 0, 0),)


def test_stopped_layout_has_a_start_action_and_no_active_toggle_hotkey() -> None:
    for layout in (None, LayoutState.QUIT):
        state = MenuState(layout=layout, overlay_enabled=True, capturing=False)
        items = menu_items(state, TRAY)
        assert items[0].text == "Layout: not running"
        assert not items[0].enabled and not items[0].checked
        assert items[1].id == Menu.RESTART_LAYOUT.value and items[1].text == "Start layout" and items[1].enabled
    unavailable = LayoutFixture(None)
    assert not toggle_layout(unavailable) and not unavailable.messages


def test_tray_keeps_saved_meeting_transcripts_reachable_while_recording_or_idle() -> None:
    # Defect: the transcripts entry is dropped or disabled during capture. It is the
    # only way to browse saved meetings.
    for capturing in (False, True):
        state = MenuState(layout=LayoutState.ON, overlay_enabled=True, capturing=capturing)
        item = next(item for item in menu_items(state, TRAY) if item.id == Menu.TRANSCRIPTS.value)
        assert (item.text, item.enabled) == ("Open meeting transcripts", True)


def test_tray_overlay_item_is_checked_exactly_when_the_overlay_is_enabled() -> None:
    # Defect: the tray shows the overlay as on after the user turned it off, or the reverse.
    for enabled in (False, True):
        state = MenuState(layout=LayoutState.ON, overlay_enabled=enabled, capturing=False)
        item = next(item for item in menu_items(state, TRAY) if item.id == Menu.OVERLAY.value)
        assert item.checked is enabled


def test_control_event_preserves_voice_release_and_rejects_unknown_requests() -> None:
    """Detect dropping a capture's key-up or forwarding an invalid wire request."""
    assert control_event(WindowInput(WM_REQUEST, Tool.DICTATE.value, 0), APPS) == FeatureRequest(Tool.DICTATE, down=False)
    assert control_event(WindowInput(WM_REQUEST, 999, 1), APPS) is None


def test_menu_tool_message_decodes_its_tool_and_rejects_other_requests() -> None:
    # Defects: decoding drops the chosen tool, accepts a non-Tool wire request,
    # or handles another private message as a choice.
    assert control_event(WindowInput(WM_TOOL_CHOSEN, Tool.WINDOW_SWITCHER.value, 0), APPS) == ChosenTool(Tool.WINDOW_SWITCHER)
    assert control_event(WindowInput(WM_TOOL_CHOSEN, 999, 0), APPS) is None
    assert control_event(WindowInput(WM_TOOL_CHOSEN, 1000, 0), APPS) is None
    assert control_event(WindowInput(0x8056, Tool.WINDOW_SWITCHER.value, 0), APPS) is None
