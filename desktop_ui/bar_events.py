"""The bar's decisions: what the person did and what was published, folded into what the bar shows.

The bar window, the views' publisher and the bar's own timers report what
happened as an `Event`; `transition` returns the next `BarModel` and the `Effect`s
to perform, lazily and in order. Measuring and painting stay with the window: the
bar performs them and reports what they computed (`Retargeted`, `Framed`) as
facts, so even the motion it draws changes only through the fold.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Final, assert_never

from config import DARK_WHEN_IDLE_MINUTES
from contracts.canvas_activity import CanvasRequest
from contracts.meeting_detection import AutomaticStatus
from contracts.recording_state import RecordingAction, RecordingState
from contracts.status import Job
from desktop_ui import island_menu, island_moment, ui_spec
from desktop_ui.agent_progress import Phase, coalesced, hint, stable_phases
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.application_observer import EMPTY_ARRANGEMENT, Arrangement
from desktop_ui.island_menu import (
    Applied,
    Chosen,
    Command,
    Controls,
    Dismissed,
    Menu,
    Slider,
    ToolChoice,
    TrayChoice,
    Volume,
    entries,
    restores_focus,
)
from desktop_ui.island_model import Action, Agent, CapsuleView, Key, Marker, Spinner, capture
from desktop_ui.island_moment import Asked, Inbox, Notice, Notices, Row
from desktop_ui.island_motion import IslandMotion, advance, finish, settled
from desktop_ui.navigation import Order, Placing
from desktop_ui.shell_items import EMPTY_SHELF, Shelf
from protocol import Tool
from winapi import appearance
from winapi.machine_status import Power, PowerUnavailable, Speakers
from winapi.shapes import Rect
from winapi.tray_host import Click

type Opened = Menu | Phase | Inbox
"""What the person opened in the island."""


@dataclass(frozen=True, slots=True)
class BarModel:
    """Everything the bar shows and decides from; replaced whole on the Qt thread."""

    specs: ui_spec.Specs
    closed: bool = False
    visible: bool = True
    """Whether the bar's window is meant to be on screen."""
    opened: Opened | None = None
    menu_target: int = 0
    """The window that had the keyboard before the island opened."""
    hovered: Key | None = None
    notices: Notices = field(default_factory=Notices)
    choices: tuple[Phase, ...] = ()
    """The session's phases, for a question opened from the island."""
    # Each activity comes from its own owner: dictation and quick jobs from the
    # voice controller, the agent from its session.
    dictating: bool = False
    automatic: AutomaticStatus = AutomaticStatus.OFF
    overlay_enabled: bool = False
    job: Job | None = None
    agent: Agent | None = None
    recording: RecordingState = field(default_factory=RecordingState)
    chord_held: bool = False
    """Either keyboard is holding its Apps key."""
    layout_enabled: bool = True
    inbox: int = 0
    # What the tick observes.
    system: SystemStatus = field(default_factory=SystemStatus)
    power: Power = PowerUnavailable.UNKNOWN
    ambient: Ambient = field(default_factory=lambda: Ambient("", PowerUnavailable.UNKNOWN))
    preference: appearance.Preference = appearance.Material.SOLID
    frost: appearance.Frost = appearance.Frost.SMOKED
    applications: Shelf = EMPTY_SHELF
    arrangement: Arrangement = EMPTY_ARRANGEMENT
    taskbar_revealed: bool = False
    dark_when_away: bool | None = None
    """Whether screens go dark while away; None without the native shell."""
    tray_tips: tuple[str, ...] = ()
    sample_bounds: Rect | None = None
    next_material: float = 0.0
    next_power: float = 0.0
    # What the window last computed.
    views: tuple[CapsuleView, ...] = ()
    motion: IslandMotion = field(default_factory=IslandMotion)
    """Reassigned each frame; the bar mutates no motion or view record."""
    last_frame: float | None = None
    sampled_at: float | None = None


def menu(model: BarModel) -> Menu:
    """The menu for what's happening now, keeping the current selection."""
    recorded = capture(model.recording) if model.recording.capturing else None
    working = model.agent if model.agent is not None and not model.agent.waiting else None
    sound = Slider("Sound", model.system.volume, muted=model.system.speakers is Speakers.MUTED)
    built = Menu(
        entries(
            Controls(
                recorded.title if recorded is not None else None,
                working.phase if working is not None else None,
                model.automatic,
                overlay=model.overlay_enabled,
                taskbar=model.taskbar_revealed,
                placement_paused=model.arrangement.paused,
                dark_when_away=DARK_WHEN_IDLE_MINUTES if model.dark_when_away else None,
                sound=sound,
                tray=model.tray_tips,
            ),
            model.specs.controls,
        )
    )
    return replace(built, selected=model.opened.selected) if isinstance(model.opened, Menu) else built


# ---- facts --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pressed:
    action: Action


@dataclass(frozen=True, slots=True)
class Hovered:
    key: Key | None
    now: float


@dataclass(frozen=True, slots=True)
class Selected:
    index: int


@dataclass(frozen=True, slots=True)
class Picked:
    index: int


@dataclass(frozen=True, slots=True)
class MenuKey:
    press: island_menu.Press


@dataclass(frozen=True, slots=True)
class Deactivated:
    """Another window took the keyboard: the island closes without taking it back."""


@dataclass(frozen=True, slots=True)
class Chose:
    row: Row


@dataclass(frozen=True, slots=True)
class VolumeSet:
    level: float


@dataclass(frozen=True, slots=True)
class TrayClicked:
    slot: int
    click: Click


@dataclass(frozen=True, slots=True)
class Rerender:
    """The window asks to be laid out again."""


@dataclass(frozen=True, slots=True)
class OverlayShown:
    enabled: bool


@dataclass(frozen=True, slots=True)
class DictationShown:
    active: bool


@dataclass(frozen=True, slots=True)
class JobShown:
    job: Job | None


@dataclass(frozen=True, slots=True)
class AgentShown:
    agent: Agent | None


@dataclass(frozen=True, slots=True)
class InboxShown:
    count: int


@dataclass(frozen=True, slots=True)
class RecordingShown:
    recording: RecordingState


@dataclass(frozen=True, slots=True)
class AutomaticShown:
    status: AutomaticStatus


@dataclass(frozen=True, slots=True)
class LayoutShown:
    enabled: bool


# The views' publisher changed one of the activities the bar shows.
type ActivityChange = OverlayShown | DictationShown | JobShown | AgentShown | InboxShown | RecordingShown | AutomaticShown | LayoutShown


@dataclass(frozen=True, slots=True)
class ChordHeld:
    held: bool


@dataclass(frozen=True, slots=True)
class RequestsShown:
    choices: tuple[Phase, ...]


@dataclass(frozen=True, slots=True)
class NoticesShown:
    current: tuple[Notice, ...]
    now: float


@dataclass(frozen=True, slots=True)
class InboxRequested:
    """The bell's list of these questions and the bar's news; nothing opens with neither."""

    questions: tuple[Phase, ...]


@dataclass(frozen=True, slots=True)
class Opening:
    """The island took the keyboard to show `opened`; `target` had it before, when it was closed."""

    opened: Opened
    target: int | None


@dataclass(frozen=True, slots=True)
class Ticked:
    """What the tick observed of the desktop, the shell and the system."""

    system: SystemStatus
    power: Power
    next_power: float
    ambient: Ambient
    preference: appearance.Preference
    frost: appearance.Frost
    next_material: float
    sample_bounds: Rect | None
    applications: Shelf
    arrangement: Arrangement
    taskbar_revealed: bool
    dark_when_away: bool | None
    tray_tips: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Respecced:
    specs: ui_spec.Specs


@dataclass(frozen=True, slots=True)
class Retargeted:
    """The window measured the bar: its views, their motion's new targets and the notices it advanced."""

    views: tuple[CapsuleView, ...]
    motion: IslandMotion
    notices: Notices
    opened: Opened | None


@dataclass(frozen=True, slots=True)
class Framed:
    motion: IslandMotion
    last_frame: float | None


@dataclass(frozen=True, slots=True)
class Sampled:
    at: float


@dataclass(frozen=True, slots=True)
class Closing:
    pass


@dataclass(frozen=True, slots=True)
class Visibility:
    """The bar was shown or hidden; hidden, it lays out without animating."""

    visible: bool


@dataclass(frozen=True, slots=True)
class TrayShown:
    """The tray icons the menu lists, by their tips."""

    tips: tuple[str, ...]


# ---- requests: their own effect -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class PaintDue:
    """Paint the next frame."""


@dataclass(frozen=True, slots=True)
class TickDue:
    """Observe the desktop, the shell and the system."""


@dataclass(frozen=True, slots=True)
class SampleDue:
    """Sample the microphone for the dictation trace."""


@dataclass(frozen=True, slots=True)
class Navigate:
    order: Order


type Instruction = PaintDue | TickDue | SampleDue | Navigate


type Event = (
    Pressed
    | Hovered
    | Selected
    | Picked
    | MenuKey
    | Deactivated
    | Chose
    | VolumeSet
    | TrayClicked
    | Rerender
    | ActivityChange
    | ChordHeld
    | RequestsShown
    | NoticesShown
    | InboxRequested
    | Opening
    | Ticked
    | Respecced
    | Retargeted
    | Framed
    | Sampled
    | Closing
    | Visibility
    | TrayShown
    | Instruction
)

# ---- effects ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Render:
    """Measure the bar and retarget its motion at what it should show now."""


@dataclass(frozen=True, slots=True)
class Expand:
    """Take the keyboard (remembering who had it, if the island was closed) and open `opened`."""

    opened: Opened
    remember: bool


@dataclass(frozen=True, slots=True)
class Release:
    """Give the keyboard back to `target` (0: to no one) as the island closes."""

    target: int


@dataclass(frozen=True, slots=True)
class SelectRequest:
    request: CanvasRequest | None


@dataclass(frozen=True, slots=True)
class Act:
    """One of the bar's actions."""

    action: BarAction


@dataclass(frozen=True, slots=True)
class Work:
    pass


@dataclass(frozen=True, slots=True)
class Stop:
    pass


@dataclass(frozen=True, slots=True)
class Record:
    action: RecordingAction


@dataclass(frozen=True, slots=True)
class OpenInbox:
    pass


@dataclass(frozen=True, slots=True)
class OpenItem:
    target: str


@dataclass(frozen=True, slots=True)
class Keyboard:
    pass


@dataclass(frozen=True, slots=True)
class Overlay:
    pass


@dataclass(frozen=True, slots=True)
class AllControls:
    pass


@dataclass(frozen=True, slots=True)
class UseTool:
    tool: Tool


type BarAction = Work | Stop | Record | OpenInbox | OpenItem | Keyboard | Overlay | AllControls | UseTool


@dataclass(frozen=True, slots=True)
class ToggleTaskbar:
    pass


@dataclass(frozen=True, slots=True)
class ToggleAway:
    pass


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    pass


@dataclass(frozen=True, slots=True)
class SetVolume:
    level: float


@dataclass(frozen=True, slots=True)
class ClickTray:
    slot: int
    click: Click


@dataclass(frozen=True, slots=True)
class ShowHints:
    pass


@dataclass(frozen=True, slots=True)
class UseSizes:
    sizes: ui_spec.Sizes


type Effect = (
    Instruction
    | Render
    | Expand
    | Release
    | SelectRequest
    | Act
    | ToggleTaskbar
    | ToggleAway
    | NotificationSettings
    | SetVolume
    | ClickTray
    | ShowHints
    | UseSizes
)


def _closed(model: BarModel, *, restore: bool) -> tuple[BarModel, tuple[Effect, ...]]:
    """The island closes, giving the keyboard back to who had it if `restore`."""
    if model.opened is None:
        return model, ()
    return replace(model, opened=None), (SelectRequest(None), Release(model.menu_target if restore else 0), Render())


def _expanded(model: BarModel, opened: Opened) -> tuple[BarModel, tuple[Effect, ...]]:
    return model, (Expand(opened, remember=model.opened is None),)


def _request(model: BarModel, phase: Phase) -> tuple[BarModel, tuple[Effect, ...]]:
    if model.closed:
        return model, ()
    model, effects = _expanded(model, phase)
    return model, (*effects, SelectRequest(phase.request))


def _chose(model: BarModel, row: Row) -> tuple[BarModel, tuple[Effect, ...]]:
    """A question opens in the island; a notice opens its canvas item and counts as read."""
    match row:
        case Asked(phase=phase):
            return _request(model, phase)
        case Notice(identity=identity, target=target):
            model = replace(model, notices=island_moment.read(model.notices, frozenset({identity})))
            model, closing = _closed(model, restore=False)
            opening = Act(OpenItem(target)) if target is not None else Act(Work())
            return model, (*closing, opening, Render())


def _ran(model: BarModel, choice: island_menu.Choice) -> tuple[BarModel, tuple[Effect, ...]]:
    """What a menu choice does."""
    match choice:
        case ToolChoice(tool=tool):
            return model, (Act(UseTool(tool)),)
        case Command.CANVAS:
            return model, (Act(Work()),)
        case Command.RECORD:
            return model, (Act(Record("start")),)
        case Command.STOP_RECORDING:
            return model, (Act(Record("stop")),)
        case Command.AUTOMATIC_RECORDING:
            return model, (Act(Record("automatic")),)
        case Command.STOP_AGENT:
            return model, (Act(Stop()),)
        case Command.KEYMAP:
            return model, (Act(Keyboard()),)
        case Command.OVERLAY:
            return model, (Act(Overlay()),)
        case Command.TASKBAR:
            return model, (ToggleTaskbar(),)
        case Command.PLACEMENT:
            return model, (Navigate(Placing.TOGGLE_PAUSE),)
        case Command.DARK_WHEN_AWAY:
            return model, (ToggleAway(),)
        case Command.NOTIFICATIONS:
            return model, (NotificationSettings(),)
        case Command.ALL_CONTROLS:
            return model, (Act(AllControls()),)
        case Volume(level=level):
            return _volume(model, level)
        case TrayChoice(slot=slot):
            return _tray(model, slot, Click.LEFT)
        case _:
            assert_never(choice)


def _volume(model: BarModel, level: float) -> tuple[BarModel, tuple[Effect, ...]]:
    """The status observer applies it; the slider follows at once rather than at the next reading."""
    return replace(model, system=replace(model.system, volume=level)), (SetVolume(level), Render())


def _tray(model: BarModel, slot: int, click: Click) -> tuple[BarModel, tuple[Effect, ...]]:
    """The application gets the click and the keyboard; the island closes without taking it back."""
    model, closing = _closed(model, restore=False)
    return model, (*closing, ClickTray(slot, click))


def _settled(model: BarModel, outcome: island_menu.Outcome) -> tuple[BarModel, tuple[Effect, ...]]:
    match outcome:
        case Menu() as opened:
            return replace(model, opened=opened), (Render(),)
        case Chosen(choice=choice):
            model, closing = _closed(model, restore=restores_focus(choice))
            model, ran = _ran(model, choice)
            return model, (*closing, *ran)
        case Applied(choice=choice):
            model, ran = _ran(model, choice)
            return model, (*ran, Render())
        case Dismissed.ESCAPE:
            return _closed(model, restore=True)
        case _:
            assert_never(outcome)


def _pressed(model: BarModel, action: Action) -> tuple[BarModel, tuple[Effect, ...]]:
    match action:
        case Action.OPEN_MENU:
            if model.closed:
                return model, ()
            opened = replace(model, opened=None)
            model, expanding = _expanded(model, menu(opened))
            return model, (SelectRequest(None), *expanding)
        case Action.CLOSE_MENU:
            return _closed(model, restore=True)
        case Action.STOP_DICTATION | Action.STOP_AGENT:
            return model, (Act(Stop()),)
        case Action.OPEN_QUESTION:
            # "Needs you" opens the session's own waiting question, wherever else the bell has news.
            phase = next((phase for phase in model.choices if hint(phase.turn)), None)
            return _request(model, phase) if phase is not None else (model, (Act(OpenInbox()),))
        case Action.OPEN_INBOX:
            return model, (Act(OpenInbox()),)
        case Action.OPEN_NOTICE:
            notice = island_moment.shown(model.notices)
            return _chose(model, notice) if notice is not None else (model, ())
        case Action.DISMISS_NOTICE:
            if (notice := island_moment.shown(model.notices)) is None:
                return model, ()
            return replace(model, notices=island_moment.read(model.notices, frozenset({notice.identity}))), (Render(),)
        case Action.OPEN_CANVAS:
            return model, (Act(Work()),)
        case Action.STOP_RECORDING:
            return model, (Act(Record("stop")),)
        case _:
            assert_never(action)


def _shown(model: BarModel, change: ActivityChange) -> BarModel:
    match change:
        case OverlayShown(enabled):
            return replace(model, overlay_enabled=enabled)
        case DictationShown(active):
            return replace(model, dictating=active)
        case JobShown(job):
            return replace(model, job=job)
        case AgentShown(agent):
            return replace(model, agent=agent)
        case InboxShown(count):
            return model if model.closed else replace(model, inbox=count)
        case RecordingShown(recording):
            return replace(model, recording=recording)
        case AutomaticShown(status):
            return replace(model, automatic=status)
        case LayoutShown(enabled):
            return replace(model, layout_enabled=enabled)
        case _:
            assert_never(change)


def _requests(model: BarModel, shown: tuple[Phase, ...]) -> tuple[BarModel, tuple[Effect, ...]]:
    request = model.opened if isinstance(model.opened, Phase) else None
    choices = tuple(coalesced(stable_phases(shown, (request,) if request is not None else ())))
    model = replace(model, choices=choices)
    if request is None:
        return model, ()
    current = next((phase for phase in choices if phase.key == request.key), None)
    if current is None:
        return _closed(model, restore=False)
    if current == request:
        return model, ()
    return replace(model, opened=current), (SelectRequest(current.request), Render())


def _inbox(model: BarModel, questions: tuple[Phase, ...]) -> tuple[BarModel, tuple[Effect, ...]]:
    listed = island_moment.rows(questions, model.notices)
    match listed:
        case ():
            return model, ()
        case (Asked(phase=phase),):
            return _request(model, phase)
        case _:
            read = island_moment.read(model.notices, frozenset(row.identity for row in listed if isinstance(row, Notice)))
            return _expanded(replace(model, notices=read), Inbox(listed))


def inbox_rows(model: BarModel, questions: tuple[Phase, ...]) -> tuple[Row, ...]:
    """What the bell would list; empty, it opens nothing."""
    return island_moment.rows(questions, model.notices)


type Interaction = Pressed | Hovered | Selected | Picked | MenuKey | Deactivated | Chose | VolumeSet | TrayClicked | Rerender
type Observation = (
    ActivityChange
    | ChordHeld
    | RequestsShown
    | NoticesShown
    | InboxRequested
    | Opening
    | Ticked
    | Respecced
    | Retargeted
    | Framed
    | Sampled
    | Closing
    | Visibility
    | TrayShown
)


def _interacted(model: BarModel, event: Interaction) -> tuple[BarModel, tuple[Effect, ...]]:
    """What the person did in the bar window."""
    match event:
        case Pressed(action):
            return _pressed(model, action)
        case Hovered(key, now):
            if model.hovered is key:
                return model, ()
            notices = island_moment.hover(model.notices, inside=key is Key.ISLAND, now=now)
            return replace(model, hovered=key, notices=notices), (Render(),)
        case Selected(index):
            if not isinstance(model.opened, Menu) or model.opened.selected == index:
                return model, ()
            return replace(model, opened=replace(model.opened, selected=index)), (Render(),)
        case Picked(index):
            if not isinstance(model.opened, Menu):
                return model, ()
            return _settled(model, island_menu.choose(model.opened, model.opened.cells[index].entry))
        case MenuKey(press):
            if not isinstance(model.opened, Menu):
                return model, ()
            return _settled(model, island_menu.press(model.opened, press))
        case Deactivated():
            return _closed(model, restore=False)
        case Chose(row):
            return _chose(model, row)
        case VolumeSet(level):
            return _volume(model, level)
        case TrayClicked(slot, click):
            return _tray(model, slot, click)
        case Rerender():
            return model, (Render(),)
        case _:
            assert_never(event)


def _observed(model: BarModel, event: Observation) -> tuple[BarModel, tuple[Effect, ...]]:
    """What was published to the bar, or what its own timers and window computed."""
    match event:
        case OverlayShown() | DictationShown() | JobShown() | AgentShown() | InboxShown() | RecordingShown() | AutomaticShown() | LayoutShown():
            changed = _shown(model, event)
            return changed, ((Render(),) if changed != model else ())
        case Visibility(visible):
            return replace(model, visible=visible), ()
        case ChordHeld(held):
            return replace(model, chord_held=held), (ShowHints(),)
        case RequestsShown(choices):
            return _requests(model, choices)
        case NoticesShown(current, now):
            return replace(model, notices=island_moment.observe(model.notices, current, now)), (Render(),)
        case InboxRequested(questions):
            return _inbox(model, questions)
        case Opening(opened, target):
            return replace(model, opened=opened, menu_target=target if target is not None else model.menu_target), (Render(),)
        case Ticked():
            return _ticked(model, event), (Render(),)
        case Respecced(specs):
            return replace(model, specs=specs), (UseSizes(specs.sizes), Render())
        case Retargeted(views, motion, notices, opened):
            return replace(model, views=views, motion=motion, notices=notices, opened=opened), ()
        case Framed(motion, last_frame):
            return replace(model, motion=motion, last_frame=last_frame), ()
        case Sampled(at):
            return replace(model, sampled_at=at), ()
        case Closing():
            return replace(model, closed=True), ()
        case TrayShown(tips):
            return replace(model, tray_tips=tips), (Render(),)
        case _:
            assert_never(event)


def transition(model: BarModel, event: Event) -> tuple[BarModel, Iterator[Effect]]:
    """The model after `event` and the effects it calls for, in order."""
    match event:
        case Pressed() | Hovered() | Selected() | Picked() | MenuKey() | Deactivated() | Chose() | VolumeSet() | TrayClicked() | Rerender():
            model, effects = _interacted(model, event)
        case PaintDue() | TickDue() | SampleDue() | Navigate():
            effects = (event,)
        case _:
            model, effects = _observed(model, event)
    return model, iter(effects)


def _ticked(model: BarModel, ticked: Ticked) -> BarModel:
    return replace(
        model,
        system=ticked.system,
        power=ticked.power,
        next_power=ticked.next_power,
        ambient=ticked.ambient,
        preference=ticked.preference,
        frost=ticked.frost,
        next_material=ticked.next_material,
        sample_bounds=ticked.sample_bounds,
        applications=ticked.applications,
        arrangement=ticked.arrangement,
        taskbar_revealed=ticked.taskbar_revealed,
        dark_when_away=ticked.dark_when_away,
        tray_tips=ticked.tray_tips,
    )


# ---- frames -------------------------------------------------------------------------


def spinning(model: BarModel) -> bool:
    """Work is running where the bar shows it: a capsule's spinner or dots, or the open menu's spinner."""

    def spinner(part: object) -> bool:
        match part:
            case Spinner() | Marker.DOTS:
                return True
            case _:
                return False

    menu_spinner = isinstance(model.opened, Menu) and model.agent is not None and not model.agent.waiting
    return menu_spinner or any(spinner(part) for view in model.views for slot in view.slots for part in slot)


@dataclass(frozen=True, slots=True)
class Frame:
    """What one frame draws, and whether another frame should follow."""

    motion: IslandMotion
    spin_angle: float
    """Degrees; 90 is the spinner at rest."""
    wave_progress: float
    """How far the dictation wave has moved from its last sample to the next, 0 to 1."""
    indicators: bool
    """An activity indicator or the wave is showing, so their capsules repaint."""
    running: bool
    """Something is still moving: the frame loop keeps going."""


WAVE_SAMPLE_S: Final = 0.05
"""The microphone trace's sampling period: the wave moves across it between samples."""


def next_frame(model: BarModel, now: float, *, animate: bool) -> Frame:
    """The frame at `now`; without `animate` (hidden, or Windows' reduced motion) everything rests."""
    # A frame after the loop was idle starts the motion now, rather than from the last frame.
    elapsed = now - (model.last_frame if model.last_frame is not None else now)
    motion = advance(model.motion, elapsed) if animate else finish(model.motion)
    working = spinning(replace(model, motion=motion))
    spins = animate and working
    waving = animate and model.dictating and model.opened is None
    wave = min(1.0, max(0.0, (now - model.sampled_at) / WAVE_SAMPLE_S)) if waving and model.sampled_at is not None else 1.0
    return Frame(
        motion,
        (90 - now * 300) % 360 if spins else 90.0,
        wave,
        indicators=working or waving,
        running=not settled(motion) or spins or waving,
    )
