"""The desktop's control decisions: events in, a new state and effects out.

The tray, the keyboard's messages, the assistant's link and the bar all report
what happened as an `Event`; none calls back into the application. The Qt thread
folds each event through `transition`, which returns the next `DesktopState` and
the `Effect`s to perform, lazily and in order. Only `desktop_ui.desktop_app`
performs effects, and an effect can report a result as a new event (a menu choice,
a refused send), so every decision here can be checked with values alone.

An event is either a fact whose reaction depends on the state, or a request that
is its own effect and passes straight through.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import assert_never

from contracts.desktop_link import MicLevel, Notify, Record, RecordingChanged, SessionChanged, ToAssistant, ToDesktop, UseTool, VoiceChanged
from contracts.status import State
from desktop_ui.desktop_controls import ChosenTool, ControlAction, FeatureRequest, Menu, MenuState, PhysicalKey, TraySpec
from desktop_ui.keymap import indicator_text
from desktop_ui.navigation import AppKey, Order, Source, keyed
from desktop_ui.overlay import OverlayState
from link.client import Status
from miryoku.layout import Layer, Scancode
from protocol import App, LayoutState, Request, Side, Tool, decode_indicator, owner


@dataclass(frozen=True, slots=True)
class Shown:
    """What the assistant last published that the tray and its menu read."""

    state: State = State.LAYOUT_OFF
    capturing: bool = False
    agent_running: bool = False
    connected: bool = False


@dataclass(frozen=True, slots=True)
class DesktopState:
    shown: Shown = field(default_factory=Shown)
    overlay: OverlayState = field(default_factory=OverlayState)
    layout: LayoutState | None = None
    """What the layout last reported; None until it does."""
    level: float | None = None
    """The microphone's latest level from the assistant, for the bar's trace."""
    tray_spec: TraySpec | None = None
    """The tray menu's last good spec; None until the menu first opens."""


# ---- facts --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssistantSaid:
    message: ToDesktop


@dataclass(frozen=True, slots=True)
class Connection:
    status: Status


@dataclass(frozen=True, slots=True)
class MenuRequested:
    pass


@dataclass(frozen=True, slots=True)
class MenuChosen:
    choice: int
    """What `shell.show_menu` returned: a `Menu` value, or 0 when dismissed."""


@dataclass(frozen=True, slots=True)
class SpecLoaded:
    spec: TraySpec


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


@dataclass(frozen=True, slots=True)
class OverlayToggled:
    pass


@dataclass(frozen=True, slots=True)
class Problem:
    message: str


type Fact = AssistantSaid | Connection | MenuRequested | MenuChosen | SpecLoaded | Controlled | Indicated | LayoutReported | OverlayToggled | Problem

# ---- requests: their own effect -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Send:
    """A command for the assistant; refused while it is unreachable."""

    command: ToAssistant


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


type Instruction = Send | RestoreTray | Chord | ToggleTaskbar | Quit

type Event = Fact | Instruction

# ---- effects only reactions produce -------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fold:
    """Fold another event next, as if it had just been reported."""

    event: Event


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
class ShowViews:
    """The views show what the assistant published."""

    message: ToDesktop


@dataclass(frozen=True, slots=True)
class ShowMenu:
    """Load the tray spec (keeping the last good one), then show the menu and report the choice."""

    state: MenuState
    spec: TraySpec | None


@dataclass(frozen=True, slots=True)
class Navigate:
    order: Order


@dataclass(frozen=True, slots=True)
class RecordUse:
    feature: str


@dataclass(frozen=True, slots=True)
class OpenInbox:
    pass


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
class ShowCanvas:
    pass


@dataclass(frozen=True, slots=True)
class OpenUsage:
    pass


@dataclass(frozen=True, slots=True)
class OpenLogs:
    pass


type Effect = (
    Instruction
    | Fold
    | Log
    | Beep
    | TrayNotify
    | TrayShow
    | ShowViews
    | ShowMenu
    | Navigate
    | RecordUse
    | OpenInbox
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
    | ShowCanvas
    | OpenUsage
    | OpenLogs
)


def tray_state(shown: Shown) -> State:
    return State.RECORDING if shown.capturing else shown.state if shown.connected else State.LAYOUT_OFF


def _said(shown: Shown, message: ToDesktop) -> Shown:
    match message:
        case SessionChanged(session=session):
            return replace(shown, agent_running=session.busy)
        case VoiceChanged(state=state):
            return replace(shown, state=state)
        case RecordingChanged(recording=recording):
            return replace(shown, capturing=recording.capturing)
        case _:
            return shown


def _connected(state: DesktopState, status: Status) -> DesktopState:
    match status:
        case Status.CONNECTED:
            return replace(state, shown=replace(state.shown, connected=True))
        case Status.DISCONNECTED:
            return replace(state, shown=replace(state.shown, connected=False, agent_running=False), level=None)
        case _:
            assert_never(status)


def _requested(request: Request) -> Iterator[Effect]:
    """A request the desktop owns: an app key, a window key, the inbox or the switcher."""
    match request:
        case App():
            yield Navigate(AppKey(request, Source.KEY))
            yield RecordUse(f"app:{request.name}")
        case Tool.OPEN_INBOX:
            yield OpenInbox()
        case Tool.WINDOW_SWITCHER:
            yield SwitchWindows()
        case Tool():
            if (order := keyed(request)) is not None:
                yield Navigate(order)
            yield RecordUse(request.name.lower())
        case _:
            assert_never(request)


def _controlled(action: ControlAction | None, overlay: OverlayState) -> Iterator[Effect]:
    match action:
        case PhysicalKey():
            yield PressedKeys(overlay.pressed, reset=action.reset)
        case FeatureRequest(request=request, down=down):
            if down and owner(request) is Side.DESKTOP:
                yield from _requested(request)
        case ChosenTool(tool=tool):
            match owner(tool):
                case Side.DESKTOP:
                    yield from _requested(tool)
                case Side.ASSISTANT:
                    yield Send(UseTool(tool))
                case _:
                    assert_never(owner(tool))
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
        case Menu.RESTART_ASSISTANT:
            yield Launch("restart", ("assistant",))
        case Menu.RESTART_DESKTOP:
            # The launcher closes this program and starts it again; the assistant keeps working meanwhile.
            yield Launch("restart", ("desktop",))
        case Menu.OVERLAY:
            yield Fold(OverlayToggled())
        case Menu.KEYMAP:
            yield ShowKeymap()
        case Menu.AGENT:
            yield Send(UseTool(Tool.AGENT_TYPED))
        case Menu.WORK:
            yield ShowCanvas()
        case Menu.TASKBAR:
            yield ToggleTaskbar()
        case Menu.STOP_AGENT:
            yield Send(UseTool(Tool.STOP))
        case Menu.MEETING:
            yield Send(UseTool(Tool.MEETING_TOGGLE))
        case Menu.TRANSCRIPTS:
            yield Send(Record("folder"))
        case Menu.USAGE:
            yield OpenUsage()
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
        case AssistantSaid(message):
            if isinstance(message, Notify):
                if message.warning:
                    yield Beep()
                yield TrayNotify(message.title, message.text, message.warning)
            yield ShowViews(message)
            yield TrayShow(tray_state(after.shown))
        case Connection():
            yield TrayShow(tray_state(after.shown))
        case MenuRequested():
            menu = MenuState(
                layout=state.layout, overlay_enabled=state.overlay.enabled, agent_running=state.shown.agent_running, capturing=state.shown.capturing
            )
            yield ShowMenu(menu, state.tray_spec)
        case MenuChosen(choice):
            yield from _chosen(choice)
        case SpecLoaded():
            pass
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
        case AssistantSaid(MicLevel(level=level)):
            return replace(state, level=level)
        case AssistantSaid(message):
            return replace(state, shown=_said(state.shown, message))
        case Connection(status):
            return _connected(state, status)
        case SpecLoaded(spec):
            return replace(state, tray_spec=spec)
        case Controlled(action):
            return replace(state, overlay=_overlay_after(action, state.overlay))
        case Indicated(code):
            return replace(state, overlay=indicated(code, state.overlay)[1])
        case LayoutReported(value):
            layout = _layout(value, state.layout)
            return replace(state, layout=layout, overlay=state.overlay.set_layout(on=layout is LayoutState.ON))
        case OverlayToggled():
            return replace(state, overlay=replace(state.overlay, enabled=not state.overlay.enabled))
        case MenuRequested() | MenuChosen() | Problem():
            return state
        case _:
            assert_never(fact)


def transition(state: DesktopState, event: Event) -> tuple[DesktopState, Iterator[Effect]]:
    """The state after `event` and the effects it calls for, in order, produced lazily."""
    match event:
        case Send() | RestoreTray() | Chord() | ToggleTaskbar() | Quit():
            return state, iter((event,))
        case _:
            after = _remembered(state, event)
            return after, _reacted(state, after, event)
