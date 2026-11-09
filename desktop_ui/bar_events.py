"""The bar's decisions: what the person did and what was published, folded into what the bar shows.

The bar window, the views' publisher and the bar's own timers report what
happened as an `Event`; `transition` returns the next `BarModel` and the `Effect`s
to perform, lazily and in order. Measuring and painting stay with the bar: it
performs them and reports what they computed (`Retargeted`, `Framed`) as facts,
so even the motion it draws changes only through the fold.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Final, assert_never

from config import DARK_WHEN_IDLE_MINUTES
from contracts.recording_state import RecordingAction, RecordingState
from contracts.status import Job
from desktop_ui import island_menu
from desktop_ui.ambient import Ambient, SystemStatus
from desktop_ui.application_observer import EMPTY_ARRANGEMENT, Arrangement
from desktop_ui.island_menu import (
    CONTROLS,
    DISMISSED,
    Applied,
    Chosen,
    Command,
    Controls,
    Menu,
    Slider,
    ToolChoice,
    TrayChoice,
    Volume,
    entries,
    restores_focus,
)
from desktop_ui.island_model import Action, CapsuleView, Key, Marker, capture
from desktop_ui.island_motion import IslandMotion, advance, finish, settled
from desktop_ui.navigation import Order, Placing
from protocol import Tool
from winapi import appearance
from winapi.machine_status import PowerUnavailable, Speakers
from winapi.shapes import Rect
from winapi.tray_host import Click

NO_SCREEN: Final = Rect(0, 0, 0, 0)
"""Before the first tick reads the primary screen."""


@dataclass(frozen=True, slots=True)
class Surroundings:
    """What the tick observed of the desktop, the shell and the system, as the bar shows it."""

    system: SystemStatus = field(default_factory=SystemStatus)
    ambient: Ambient = field(default_factory=lambda: Ambient("", PowerUnavailable.UNKNOWN))
    preference: appearance.Preference = appearance.Material.SOLID
    frost: appearance.Frost = appearance.Frost.SMOKED
    arrangement: Arrangement = EMPTY_ARRANGEMENT
    dark_when_away: bool | None = None
    """Whether screens go dark while away; None without the native shell."""
    tray_tips: tuple[str, ...] = ()
    screen: Rect = NO_SCREEN
    """The primary screen, which the bar spans."""
    scale: float = 1.0
    """The bar window's device pixels per DIP."""


@dataclass(frozen=True, slots=True)
class BarModel:
    """Everything the bar shows and decides from; replaced whole on the Qt thread."""

    closed: bool = False
    opened: Menu | None = None
    """The controls menu, while it is open."""
    menu_target: int = 0
    """The window that had the keyboard before the menu opened."""
    hovered: Key | None = None
    # Each activity comes from its own owner: dictation and quick jobs from the
    # voice controller, the recording from the meeting recorder.
    dictating: bool = False
    overlay_enabled: bool = False
    job: Job | None = None
    recording: RecordingState = field(default_factory=RecordingState)
    chord_held: bool = False
    """Either keyboard is holding its Apps key."""
    layout_enabled: bool = True
    seen: Surroundings = field(default_factory=Surroundings)
    """What the tick last observed."""
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
    seen = model.seen
    sound = Slider("Sound", seen.system.volume, muted=seen.system.speakers is Speakers.MUTED)
    built = Menu(
        entries(
            Controls(
                recorded.title if recorded is not None else None,
                overlay=model.overlay_enabled,
                placement_paused=seen.arrangement.paused,
                dark_when_away=DARK_WHEN_IDLE_MINUTES if seen.dark_when_away else None,
                sound=sound,
                tray=seen.tray_tips,
            ),
            CONTROLS,
        )
    )
    return replace(built, selected=model.opened.selected) if model.opened is not None else built


# ---- facts --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pressed:
    action: Action


@dataclass(frozen=True, slots=True)
class Hovered:
    key: Key | None


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
class VolumeSet:
    level: float


@dataclass(frozen=True, slots=True)
class TrayClicked:
    slot: int
    click: Click


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
class RecordingShown:
    recording: RecordingState


@dataclass(frozen=True, slots=True)
class LayoutShown:
    enabled: bool


# The views' publisher changed one of the activities the bar shows.
type ActivityChange = OverlayShown | DictationShown | JobShown | RecordingShown | LayoutShown


@dataclass(frozen=True, slots=True)
class ChordHeld:
    held: bool


@dataclass(frozen=True, slots=True)
class Opening:
    """The bar took the keyboard to show `opened`; `target` had it before, when it was closed."""

    opened: Menu
    target: int | None


@dataclass(frozen=True, slots=True)
class Ticked:
    """What the tick observed, and when it next reads power and the material."""

    seen: Surroundings
    next_power: float
    next_material: float


@dataclass(frozen=True, slots=True)
class Retargeted:
    """The window measured the bar: its views and their motion's new targets."""

    views: tuple[CapsuleView, ...]
    motion: IslandMotion
    opened: Menu | None


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


type Event = (
    Pressed
    | Hovered
    | Selected
    | Picked
    | MenuKey
    | Deactivated
    | VolumeSet
    | TrayClicked
    | ActivityChange
    | ChordHeld
    | Opening
    | Ticked
    | Retargeted
    | Framed
    | Sampled
    | Closing
)

# ---- effects ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Render:
    """Measure the bar and retarget its motion at what it should show now."""


@dataclass(frozen=True, slots=True)
class Expand:
    """Take the keyboard (remembering who had it, if the menu was closed) and open `opened`."""

    opened: Menu
    remember: bool


@dataclass(frozen=True, slots=True)
class Release:
    """Give the keyboard back to `target` (0: to no one) as the menu closes."""

    target: int


@dataclass(frozen=True, slots=True)
class Record:
    action: RecordingAction


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


@dataclass(frozen=True, slots=True)
class Navigate:
    order: Order


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


type Effect = (
    Render
    | Expand
    | Release
    | Record
    | Keyboard
    | Overlay
    | AllControls
    | UseTool
    | Navigate
    | ToggleAway
    | NotificationSettings
    | SetVolume
    | ClickTray
    | ShowHints
)


def _closed(model: BarModel, *, restore: bool) -> tuple[BarModel, tuple[Effect, ...]]:
    """The menu closes, giving the keyboard back to who had it if `restore`."""
    if model.opened is None:
        return model, ()
    return replace(model, opened=None), (Release(model.menu_target if restore else 0), Render())


def _ran(model: BarModel, choice: island_menu.Choice) -> tuple[BarModel, tuple[Effect, ...]]:
    """What a menu choice does."""
    match choice:
        case ToolChoice(tool=tool):
            return model, (UseTool(tool),)
        case Command.RECORD:
            return model, (Record("start"),)
        case Command.STOP_RECORDING:
            return model, (Record("stop"),)
        case Command.KEYMAP:
            return model, (Keyboard(),)
        case Command.OVERLAY:
            return model, (Overlay(),)
        case Command.PLACEMENT:
            return model, (Navigate(Placing.TOGGLE_PAUSE),)
        case Command.DARK_WHEN_AWAY:
            return model, (ToggleAway(),)
        case Command.NOTIFICATIONS:
            return model, (NotificationSettings(),)
        case Command.ALL_CONTROLS:
            return model, (AllControls(),)
        case Volume(level=level):
            return _volume(model, level)
        case TrayChoice(slot=slot):
            return _tray(model, slot, Click.LEFT)
        case _:
            assert_never(choice)


def _volume(model: BarModel, level: float) -> tuple[BarModel, tuple[Effect, ...]]:
    """The status observer applies it; the slider follows at once rather than at the next reading."""
    seen = replace(model.seen, system=replace(model.seen.system, volume=level))
    return replace(model, seen=seen), (SetVolume(level), Render())


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
        case _ if outcome is DISMISSED:
            return _closed(model, restore=True)
        case _:
            assert_never(outcome)


def _pressed(model: BarModel, action: Action) -> tuple[BarModel, tuple[Effect, ...]]:
    match action:
        case Action.OPEN_MENU:
            if model.closed:
                return model, ()
            return model, (Expand(menu(replace(model, opened=None)), remember=model.opened is None),)
        case Action.CLOSE_MENU:
            return _closed(model, restore=True)
        case Action.STOP_DICTATION:
            # The dictation toggle stops a capture that is listening.
            return model, (UseTool(Tool.DICTATE_TOGGLE),)
        case Action.STOP_RECORDING:
            return _ran(model, Command.STOP_RECORDING)
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
        case RecordingShown(recording):
            return replace(model, recording=recording)
        case LayoutShown(enabled):
            return replace(model, layout_enabled=enabled)
        case _:
            assert_never(change)


def _changed(before: BarModel, after: BarModel) -> tuple[BarModel, tuple[Effect, ...]]:
    """`after`, rendered only when it differs from `before`."""
    return after, ((Render(),) if after != before else ())


def _folded(model: BarModel, event: Event) -> tuple[BarModel, tuple[Effect, ...]]:
    match event:
        case Pressed(action):
            return _pressed(model, action)
        case Hovered(key):
            return _changed(model, replace(model, hovered=key))
        case Selected(index):
            if model.opened is None:
                return model, ()
            return _changed(model, replace(model, opened=replace(model.opened, selected=index)))
        case Picked(index):
            if model.opened is None:
                return model, ()
            return _settled(model, island_menu.choose(model.opened, model.opened.cells[index].entry))
        case MenuKey(press):
            if model.opened is None:
                return model, ()
            return _settled(model, island_menu.press(model.opened, press))
        case Deactivated():
            return _closed(model, restore=False)
        case VolumeSet(level):
            return _volume(model, level)
        case TrayClicked(slot, click):
            return _tray(model, slot, click)
        case OverlayShown() | DictationShown() | JobShown() | RecordingShown() | LayoutShown():
            return _changed(model, _shown(model, event))
        case ChordHeld(held):
            return replace(model, chord_held=held), (ShowHints(),)
        case Opening(opened, target):
            return replace(model, opened=opened, menu_target=target if target is not None else model.menu_target), (Render(),)
        case Ticked(seen, next_power, next_material):
            # A changed reading re-measures, so a growing timer pushes its neighbours out.
            rendered = (Render(),) if seen != model.seen else ()
            return replace(model, seen=seen, next_power=next_power, next_material=next_material), rendered
        case Retargeted(views, motion, opened):
            return replace(model, views=views, motion=motion, opened=opened), ()
        case Framed(motion, last_frame):
            return replace(model, motion=motion, last_frame=last_frame), ()
        case Sampled(at):
            return replace(model, sampled_at=at), ()
        case Closing():
            return replace(model, closed=True), ()
        case _:
            assert_never(event)


def transition(model: BarModel, event: Event) -> tuple[BarModel, Iterator[Effect]]:
    """The model after `event` and the effects it calls for, in order."""
    model, effects = _folded(model, event)
    return model, iter(effects)


# ---- frames -------------------------------------------------------------------------


def spinning(model: BarModel) -> bool:
    """Work is running where the bar shows it: a capsule's dots."""
    return any(part is Marker.DOTS for view in model.views for slot in view.slots for part in slot)


@dataclass(frozen=True, slots=True)
class Frame:
    """What one frame draws, and whether another frame should follow."""

    motion: IslandMotion
    spin_angle: float
    """Degrees; 90 is the dots at rest."""
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
