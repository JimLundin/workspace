"""The desktop's control decisions: events in, a new state and effects out.

The tray, the keyboard's messages, dictation, meetings and the bar all report
what happened as an `Event`; none calls back into the application. The Qt thread
folds each event through `transition`, which returns the next `DesktopState` and
the `Effect`s to perform, lazily and in order. Only `desktop_ui.desktop_app`
performs effects, and an effect can report a result as a new event (a menu choice,
the voice state it resolved), so every decision here can be checked with values alone.

An event is either a fact whose reaction depends on the state, or a request that
is its own effect and passes straight through.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Final, assert_never

import protocol
import winapi.shapes
from contracts.hotkeys import ROUTES, Route
from contracts.recording_state import RecordingAction, RecordingState
from contracts.status import Job, State
from desktop_ui.bar_events import DictationShown, JobShown, RecordingShown
from desktop_ui.keymap import indicator_text
from desktop_ui.navigation import AppKey, Order, keyed
from desktop_ui.overlay import OverlayState
from keyboard.layout import Layer, Scancode
from protocol import App, LayoutState, Request, Tool, decode_indicator
lazy from winapi.shell import MenuItem

# ---- the tray menu ------------------------------------------------------------------


class Menu(Enum):
    KEYMAP = 9
    TOGGLE_LAYOUT = 1
    RESTART_LAYOUT = 2
    LOGS = 7
    QUIT = 8
    OVERLAY = 11
    MEETING = 12
    TRANSCRIPTS = 13
    TASKBAR = 15
    RESTART_DESKTOP = 19


@dataclass(frozen=True, slots=True, kw_only=True)
class MenuState:
    """The three observations that decide the tray's choices and labels."""

    layout: LayoutState | None
    overlay_enabled: bool
    capturing: bool


@dataclass(frozen=True, slots=True)
class TrayAction:
    action: Menu
    label: str = ""
    """Its words; the layout and meeting items word their state themselves."""
    key: str = ""
    """A key hint at the trailing edge."""


@dataclass(frozen=True, slots=True)
class Separator:
    pass


TRAY: Final[tuple[TrayAction | Separator, ...]] = (
    TrayAction(Menu.TOGGLE_LAYOUT),
    TrayAction(Menu.RESTART_LAYOUT),
    TrayAction(Menu.OVERLAY, "Keyboard overlay"),
    TrayAction(Menu.KEYMAP, "Key map"),
    Separator(),
    TrayAction(Menu.TASKBAR, "Toggle Windows taskbar", "Windows key"),
    TrayAction(Menu.MEETING),
    TrayAction(Menu.TRANSCRIPTS, "Open meeting transcripts"),
    Separator(),
    TrayAction(Menu.LOGS, "Open logs folder"),
    Separator(),
    TrayAction(Menu.RESTART_DESKTOP, "Restart desktop"),
    TrayAction(Menu.QUIT, "Quit Workspace"),
)
"""The tray icon's menu, top to bottom. The layout and meeting items word their own state."""


def tray_item(item: TrayAction, state: MenuState) -> MenuItem:
    """One item as it reads in `state`: its words, hint, and whether it's enabled or checked."""
    running = state.layout in (LayoutState.ON, LayoutState.OFF)
    hint = f"\t{item.key}" if item.key else ""
    match item.action:
        case Menu.TOGGLE_LAYOUT:
            status = "on" if state.layout is LayoutState.ON else "off" if state.layout is LayoutState.OFF else "not running"
            text = f"Layout: {status}" + ("\tTap §" if running else "")
            return MenuItem(item.action.value, text, enabled=running, checked=state.layout is LayoutState.ON)
        case Menu.RESTART_LAYOUT:
            return MenuItem(item.action.value, "Restart layout" if running else "Start layout")
        case Menu.MEETING:
            return MenuItem(item.action.value, "Stop recording" if state.capturing else "Record a meeting")
        case Menu.OVERLAY:
            return MenuItem(item.action.value, item.label + hint, checked=state.overlay_enabled)
        case Menu.KEYMAP | Menu.TASKBAR | Menu.TRANSCRIPTS | Menu.LOGS | Menu.RESTART_DESKTOP | Menu.QUIT:
            return MenuItem(item.action.value, item.label + hint)
        case _:
            assert_never(item.action)


def menu_items(state: MenuState) -> Iterator[MenuItem]:
    """The tray menu as it reads in `state`; a separator is item 0."""
    for item in TRAY:
        match item:
            case TrayAction():
                yield tray_item(item, state)
            case Separator():
                yield MenuItem(0)
            case _:
                assert_never(item)


# ---- the control window's messages --------------------------------------------------


@dataclass(frozen=True, slots=True)
class PhysicalKey:
    scancode: Scancode
    down: bool = field(kw_only=True)

    @property
    def reset(self) -> bool:
        return self.scancode == 0


@dataclass(frozen=True, slots=True)
class FeatureRequest:
    """A key edge from the layout, or a press (`down`) from a Workspace menu."""

    request: Request
    down: bool = field(kw_only=True)


type ControlAction = PhysicalKey | FeatureRequest


def control_event(message: int, wparam: int, lparam: int, apps: Sequence[App]) -> ControlAction | None:
    """A key state or request message to the control window, keeping key edges and requests' presses and releases."""
    if message == protocol.WM_KEY_STATE:
        return PhysicalKey(Scancode(wparam), down=bool(lparam))
    if message == protocol.WM_REQUEST and (request := protocol.decode(wparam, apps)) is not None:
        return FeatureRequest(request, down=bool(lparam))
    return None


# ---- the fold -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Shown:
    """What dictation and meetings last reported that the tray and its menu read."""

    state: State = State.LAYOUT_OFF
    recording: RecordingState = field(default_factory=RecordingState)
    """The meeting recorder's last state, which also tells an interruption from a finish."""


@dataclass(frozen=True, slots=True)
class DesktopState:
    shown: Shown = field(default_factory=Shown)
    overlay: OverlayState = field(default_factory=OverlayState)
    layout: LayoutState | None = None
    """What the layout last reported; None until it does."""


# ---- facts --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VoiceShown:
    """What the tray and the bar show of dictation, once listening has taken precedence."""

    state: State


@dataclass(frozen=True, slots=True)
class JobChanged:
    """The quick job dictation runs, for the bar; None once it has finished."""

    job: Job | None


@dataclass(frozen=True, slots=True)
class Notified:
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class RecordingChanged:
    recording: RecordingState


@dataclass(frozen=True, slots=True)
class MenuRequested:
    pass


@dataclass(frozen=True, slots=True)
class MenuChosen:
    choice: int
    """What `shell.show_menu` returned: a `Menu` value, or 0 when dismissed."""


@dataclass(frozen=True, slots=True)
class Controlled:
    """A key edge, a feature request or a menu choice from the control window."""

    action: ControlAction | None


@dataclass(frozen=True, slots=True)
class Indicated:
    code: int
    """The layout's indicator word: layer, lock and caps-word bits."""


@dataclass(frozen=True, slots=True)
class LayoutReported:
    value: int
    """The layout's raw `LayoutState`; an unknown value keeps the last known one."""


@dataclass(frozen=True, slots=True)
class OverlayToggled:
    pass


@dataclass(frozen=True, slots=True)
class Problem:
    """Something failed that the user should hear about; it is also logged."""

    message: str


type Fact = (
    VoiceShown
    | JobChanged
    | Notified
    | RecordingChanged
    | MenuRequested
    | MenuChosen
    | Controlled
    | Indicated
    | LayoutReported
    | OverlayToggled
    | Problem
)

# ---- requests: their own effect -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShowVoice:
    """Show `state` in the tray and the bar, unless listening takes precedence."""

    state: State


@dataclass(frozen=True, slots=True)
class ShowIdle:
    """Show listening, ready or layout-off, whichever state the keys are in."""


@dataclass(frozen=True, slots=True)
class Record:
    action: RecordingAction


@dataclass(frozen=True, slots=True)
class ExpireCapture:
    """The control window's capture timer fired."""

    at: float


@dataclass(frozen=True, slots=True)
class RestoreTray:
    """Explorer restarted: register the tray icon again."""


@dataclass(frozen=True, slots=True)
class Chord:
    held: bool


@dataclass(frozen=True, slots=True)
class ToggleTaskbar:
    pass


@dataclass(frozen=True, slots=True)
class Quit:
    pass


@dataclass(frozen=True, slots=True)
class ShowSwitcher:
    """The window list was read off the Qt thread: show the switcher over it."""

    choices: tuple[winapi.shapes.Window, ...]


type Instruction = ShowVoice | ShowIdle | Record | ExpireCapture | RestoreTray | Chord | ToggleTaskbar | Quit | ShowSwitcher

type Event = Fact | Instruction

# ---- effects only reactions produce -------------------------------------------------


@dataclass(frozen=True, slots=True)
class Log:
    text: str


@dataclass(frozen=True, slots=True)
class Beep:
    pass


@dataclass(frozen=True, slots=True)
class TrayNotify:
    title: str
    text: str
    warning: bool


@dataclass(frozen=True, slots=True)
class TrayShow:
    state: State


@dataclass(frozen=True, slots=True)
class ShowActivity:
    """The bar shows what dictation or a meeting is doing."""

    change: DictationShown | JobShown | RecordingShown


@dataclass(frozen=True, slots=True)
class HandleKey:
    """A dictation or transcript key's edge, or its press from a menu."""

    tool: Tool
    down: bool


@dataclass(frozen=True, slots=True)
class ToggleMeeting:
    pass


@dataclass(frozen=True, slots=True)
class UseLayout:
    """Dictation follows the layout: it stops a capture when the layout goes off."""

    on: bool


@dataclass(frozen=True, slots=True)
class ShowMenu:
    """Show the tray menu and report the choice."""

    state: MenuState


@dataclass(frozen=True, slots=True)
class Navigate:
    order: Order


@dataclass(frozen=True, slots=True)
class SwitchWindows:
    pass


@dataclass(frozen=True, slots=True)
class ShowOverlay:
    overlay: OverlayState


@dataclass(frozen=True, slots=True)
class OverlayEnabled:
    """The bar shows whether the overlay is enabled, and the setting is saved."""

    enabled: bool


@dataclass(frozen=True, slots=True)
class Flash:
    text: str


@dataclass(frozen=True, slots=True)
class LayoutShown:
    enabled: bool


@dataclass(frozen=True, slots=True)
class PressedKeys:
    pressed: frozenset[Scancode]
    reset: bool


@dataclass(frozen=True, slots=True)
class Indicate:
    text: str | None
    """The indicator's words; None hides it."""


@dataclass(frozen=True, slots=True)
class ToggleLayout:
    pass


@dataclass(frozen=True, slots=True)
class Launch:
    """Run the launcher on its own: `restart` with program names, or `stop`."""

    command: str
    names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ShowKeymap:
    pass


@dataclass(frozen=True, slots=True)
class OpenLogs:
    pass


type Effect = (
    Instruction
    | Log
    | Beep
    | TrayNotify
    | TrayShow
    | ShowActivity
    | HandleKey
    | ToggleMeeting
    | UseLayout
    | ShowMenu
    | Navigate
    | SwitchWindows
    | ShowOverlay
    | OverlayEnabled
    | Flash
    | LayoutShown
    | PressedKeys
    | Indicate
    | ToggleLayout
    | Launch
    | ShowKeymap
    | OpenLogs
)


def tray_state(shown: Shown) -> State:
    return State.RECORDING if shown.recording.capturing else shown.state


def idle_state(*, listening: Tool | None, layout_on: bool) -> State:
    """What the keys rest in: listening, ready, or the layout switched off."""
    return State.LISTENING if listening is not None else State.READY if layout_on else State.LAYOUT_OFF


def recording_notice(prior: RecordingState, recording: RecordingState) -> Notified | None:
    """A warning when a recording pauses, is interrupted, or a capture ends with a problem."""
    failed_capture = prior.capturing and recording.phase == "finishing" and bool(recording.detail)
    if (prior.phase != recording.phase and recording.phase in ("paused", "interrupted")) or failed_capture:
        return Notified("Meeting transcript", recording.detail or "Recording was interrupted. Choose Open meeting transcripts for the saved part.")
    return None


def _requested(request: Request, *, down: bool) -> Iterator[Effect]:
    """A key edge or a menu press: the desktop's own keys act on press, dictation's keys get both edges."""
    match request:
        case App():
            if down:
                yield Navigate(AppKey(request))
        case Tool():
            route = ROUTES[request]
            match route:
                case Route.HOLD | Route.TOGGLE | Route.TRANSCRIPT:
                    yield HandleKey(request, down=down)
                case _ if not down:
                    pass
                case Route.NAVIGATE:
                    if (order := keyed(request)) is not None:
                        yield Navigate(order)
                case Route.SWITCHER:
                    yield SwitchWindows()
                case Route.MEETING:
                    yield ToggleMeeting()
                case _:
                    assert_never(route)
        case _:
            assert_never(request)


def _controlled(action: ControlAction | None, overlay: OverlayState) -> Iterator[Effect]:
    match action:
        case PhysicalKey():
            yield PressedKeys(overlay.pressed, reset=action.reset)
        case FeatureRequest(request=request, down=down):
            yield from _requested(request, down=down)
        case None:
            pass
        case _:
            assert_never(action)


def _overlay_after(action: ControlAction | None, overlay: OverlayState) -> OverlayState:
    match action:
        case PhysicalKey(scancode=scancode, down=down):
            return overlay.key(scancode, down=down)
        case _:
            return overlay


def indicated(code: int, overlay: OverlayState) -> tuple[str | None, OverlayState]:
    """The indicator's words and the overlay after the layout's indicator word."""
    index, locked, caps_word = decode_indicator(code)
    layer = next((layer for layer in Layer if layer.value == index), None)
    return indicator_text(layer, locked=locked, caps_word=caps_word), overlay.indicate(layer, locked=locked, caps_word=caps_word)


def _layout(value: int, known: LayoutState | None) -> LayoutState | None:
    try:
        return LayoutState(value)
    except ValueError:
        return known


def _chosen(choice: int) -> Iterator[Effect]:
    """What a tray menu choice does."""
    try:
        chosen = Menu(choice)
    except ValueError:
        return
    match chosen:
        case Menu.TOGGLE_LAYOUT:
            yield ToggleLayout()
        case Menu.RESTART_LAYOUT:
            yield Launch("restart", ("layout",))
        case Menu.RESTART_DESKTOP:
            # The launcher closes this program and starts it again.
            yield Launch("restart", ("desktop",))
        case Menu.OVERLAY:
            pass  # `transition` folds it as `OverlayToggled`.
        case Menu.KEYMAP:
            yield ShowKeymap()
        case Menu.TASKBAR:
            yield ToggleTaskbar()
        case Menu.MEETING:
            yield ToggleMeeting()
        case Menu.TRANSCRIPTS:
            yield Record("folder")
        case Menu.LOGS:
            yield OpenLogs()
        case Menu.QUIT:
            # The launcher asks every program to quit, this one last.
            yield Launch("stop")
        case _:
            assert_never(chosen)


def _reacted(state: DesktopState, after: DesktopState, fact: Fact) -> Iterator[Effect]:
    """The effects of `fact`, given the state before it and after it."""
    match fact:
        case VoiceShown(shown):
            yield ShowActivity(DictationShown(active=shown is State.LISTENING))
            yield TrayShow(tray_state(after.shown))
        case JobChanged(job):
            yield ShowActivity(JobShown(job))
        case Notified(title, text):
            yield TrayNotify(title, text, warning=False)
        case RecordingChanged(recording):
            yield ShowActivity(RecordingShown(recording))
            yield TrayShow(tray_state(after.shown))
            if (notice := recording_notice(state.shown.recording, recording)) is not None:
                yield Beep()
                yield TrayNotify(notice.title, notice.text, warning=True)
            yield ShowIdle()
        case MenuRequested():
            menu = MenuState(layout=state.layout, overlay_enabled=state.overlay.enabled, capturing=state.shown.recording.capturing)
            yield ShowMenu(menu)
        case MenuChosen(choice):
            yield from _chosen(choice)
        case Controlled(action):
            yield from _controlled(action, after.overlay)
        case Indicated(code):
            yield Indicate(indicated(code, state.overlay)[0])
            yield ShowOverlay(after.overlay)
        case LayoutReported():
            on = after.layout is LayoutState.ON
            if after.layout is not LayoutState.QUIT:
                yield Flash("Layout on" if on else "Layout off")
            yield LayoutShown(enabled=on)
            yield PressedKeys(after.overlay.pressed, reset=True)
            yield ShowOverlay(after.overlay)
            yield UseLayout(on=on)
        case OverlayToggled():
            yield ShowOverlay(after.overlay)
            yield OverlayEnabled(enabled=after.overlay.enabled)
        case Problem(message):
            yield Log(message)
            yield Beep()
            yield TrayNotify("Workspace", message, warning=True)
        case _:
            assert_never(fact)


def _remembered(state: DesktopState, fact: Fact) -> DesktopState:
    match fact:
        case VoiceShown(shown):
            return replace(state, shown=replace(state.shown, state=shown))
        case RecordingChanged(recording):
            return replace(state, shown=replace(state.shown, recording=recording))
        case Controlled(action):
            return replace(state, overlay=_overlay_after(action, state.overlay))
        case Indicated(code):
            return replace(state, overlay=indicated(code, state.overlay)[1])
        case LayoutReported(value):
            layout = _layout(value, state.layout)
            return replace(state, layout=layout, overlay=state.overlay.set_layout(on=layout is LayoutState.ON))
        case OverlayToggled():
            return replace(state, overlay=replace(state.overlay, enabled=not state.overlay.enabled))
        case JobChanged() | Notified() | MenuRequested() | MenuChosen() | Problem():
            return state
        case _:
            assert_never(fact)


def transition(state: DesktopState, event: Event) -> tuple[DesktopState, Iterator[Effect]]:
    """The state after `event` and the effects it calls for, in order, produced lazily."""
    match event:
        case ShowVoice() | ShowIdle() | Record() | ExpireCapture() | RestoreTray() | Chord() | ToggleTaskbar() | Quit() | ShowSwitcher():
            return state, iter((event,))
        case MenuChosen(Menu.OVERLAY.value):
            return transition(state, OverlayToggled())
        case _:
            after = _remembered(state, event)
            return after, _reacted(state, after, event)
