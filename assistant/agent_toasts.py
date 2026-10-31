"""Bounded conversation bubbles and history on the assistant UI thread."""

import time
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Final, TypedDict, assert_never
from urllib.parse import urlsplit

from pydantic import Field, StrictInt, TypeAdapter
lazy from PySide6 import QtCore
lazy from PySide6.QtCore import Qt
lazy from PySide6.QtGui import QFontMetricsF
lazy from PySide6.QtWidgets import QApplication

from assistant.agent_progress import Progress, advance_progress, compact, retain_lifetimes, visible
from assistant.canvas_activity import redirect_session
from assistant.qt_runtime import prepare
from assistant.toast_stack import Active, Column, Measured, Retiring, Stacking, Viewport, fit, frames, reservable
from usage import DIRECTORY
from winapi import appearance, windows
from winapi.shapes import Rect
lazy from assistant import notification_reading
lazy from assistant.agent_session import AgentRequest, Message, Session, Snapshot, pending
lazy from assistant.agent_window import AgentWindow
lazy from assistant.card_actions import AnswerApproval, OpenCanvas, parse
lazy from assistant.feed_desktop import Desktop, NativeDesktop
lazy from assistant.notifications import (
    MAX_VISIBLE,
    Content,
    Entry,
    Frame,
    Key,
    PhaseKey,
    Recording,
    Response,
    Stack,
    Toast,
    Turn,
    advance,
    hide,
    hover,
    next_expiry,
    order_of,
    priority,
    reading_hold,
    results,
    spinning,
)
lazy from assistant.qt_ui import EventLoop, cancel, later
lazy from assistant.toast_card import Card, Measure
lazy from assistant.ui_components.text import font
lazy from automation.task import Approval
lazy from winapi.notification_input import Region, WheelRouter

prepare()

MONITOR: Final = DIRECTORY / "agent-panel.json"


class SavedBounds(TypedDict):
    x: StrictInt
    y: StrictInt
    width: Annotated[StrictInt, Field(gt=0)]
    height: Annotated[StrictInt, Field(gt=0)]


_BOUNDS = TypeAdapter(SavedBounds)


def saved_monitor(path: Path = MONITOR) -> Rect | None:
    """The stack's monitor hint, in physical screen pixels; invalid data uses the default monitor."""
    try:
        values = _BOUNDS.validate_json(path.read_bytes())
    except OSError, ValueError:
        return None
    return Rect(values["x"], values["y"], values["x"] + values["width"], values["y"] + values["height"])


class AgentToasts:
    __slots__ = (
        "__weakref__",
        "agent",
        "animation_timer",
        "canvas_open",
        "capacity",
        "cards",
        "clock",
        "closed",
        "create_card",
        "desktop",
        "environment",
        "expiry_timer",
        "history",
        "loop",
        "materials",
        "measure",
        "monitor",
        "next_material",
        "page",
        "pointer_timer",
        "progress",
        "progress_head",
        "reveal",
        "root",
        "scale",
        "session",
        "spares",
        "stack",
        "viewport",
        "wheel",
        "work",
    )

    def __init__(
        self,
        root: QApplication,
        agent: AgentWindow,
        open_canvas: Callable[[str], None],
        *,
        monitor: Rect | None = None,
        clock: Callable[[], float] = time.monotonic,
        desktop: Desktop | None = None,
        create_card: Callable[[AgentToasts, Toast, int], Card] | None = None,
        environment: appearance.Environment | None = None,
    ) -> None:
        # One view owns cards, desktop observation and motion timer lifetimes.
        # Independent monitor hint, clock, desktop and appearance environment enter
        # at construction so every card shares that ownership; tests consume the
        # same contracts.
        # Bubbles direct the person to the canvas; its opener enters here.
        self.root, self.agent, self.canvas_open, self.clock = root, agent, open_canvas, clock
        self.environment: appearance.Environment = appearance.Environment() if environment is None else environment
        self.desktop: Desktop = NativeDesktop() if desktop is None else desktop
        self.create_card = Card if create_card is None else create_card
        self.materials = appearance.FrostSampler()
        self.monitor = monitor if monitor is not None else saved_monitor()
        self.session = Session()
        self.stack = Stack()
        self.progress = Progress()
        self.progress_head: PhaseKey | None = None
        self.loop = EventLoop(root, self.sync_layers)
        self.measure = Measure()
        self.wheel = WheelRouter()
        self.cards: dict[Key, Card] = {}
        # Qt owns these native resources. Keep at most MAX_VISIBLE surfaces for
        # this view's lifetime; replacing logical content must not rebuild them.
        self.spares: tuple[Card, ...] = ()
        self.closed = False
        self.history = False
        self.page = 0
        self.capacity = MAX_VISIBLE
        self.viewport: Viewport | None = None
        self.reveal = False
        self.work: Rect | None = None
        self.scale = 0.0
        self.expiry_timer: QtCore.QTimer | None = None
        self.animation_timer: QtCore.QTimer | None = None
        self.pointer_timer: QtCore.QTimer | None = None
        self.next_material = 0.0

    def render(self, state: Snapshot) -> None:
        if self.closed:
            return
        if self.stack.identity != state.identity:
            self.clear_cards()
        self.session = state
        self.refresh()

    def observation(self) -> Snapshot:
        # History shows the agent's work as it was; live bubbles only redirect.
        return self.session if self.history else redirect_session(self.session)

    def refresh(self) -> None:
        if self.closed:
            return
        now = self.clock()
        self.project(now, reveal=self.reveal)
        self.page = min(self.page, self.stack.pages - 1)
        self.reveal = False
        self.sync(now)
        self.schedule_pointer()
        self.schedule_expiry()

    @property
    def live_progress(self) -> bool:
        return not self.history

    def project(self, now: float, *, reveal: bool = False) -> None:
        if not self.live_progress:
            self.stack = advance(self.stack, self.observation(), now, history=True, page=self.page, reveal=reveal, limit=self.capacity)
            return
        self.progress = advance_progress(retain_lifetimes(self.progress, self.stack), self.session, now)
        self.stack = visible(self.progress, self.capacity)
        latest = next((phase for toast in reversed(self.stack.toasts) if (phase := _phase(toast.key)) is not None), None)
        if latest != self.progress_head:
            self.progress_head = latest
            for key, card in self.cards.items():
                if _phase(key) is not None and card.expanded:
                    card.expanded = key == latest
                    card.prepared = card.layout = None

    def schedule_expiry(self) -> None:
        if self.expiry_timer is not None:
            cancel(self.expiry_timer)
            self.expiry_timer = None
        if (deadline := next_expiry(self.stack)) is not None:
            self.expiry_timer = later(self.root, max(1, round((deadline - self.clock()) * 1000)), self.expire)

    def expire(self) -> None:
        self.expiry_timer = None
        if not self.closed and self.cards:
            self.observe_pointer()  # include an arrival since the last glass hover sample
        self.refresh()

    def set_hover(self, key: Key, *, inside: bool) -> None:
        if not self.closed:
            card = self.cards.get(key)
            changed = card is not None and card.hovered != inside
            if card is not None:
                card.hovered = inside
                if changed and card.needs_reading():
                    card.reader = notification_reading.Paused(card.reader.offset)
            updated = hover(self.stack, key, inside=inside, now=self.clock())
            if updated != self.stack:
                self.stack = updated
                self.schedule_expiry()
            if changed:
                self.tick()

    def schedule_pointer(self) -> None:
        # One observer handles hover, wheel routing, and occasional background
        # observations. Desktop pixel reads run on the bounded worker.
        watching = not self.closed and (bool(self.wheel.regions) or any(not card.retiring for card in self.cards.values()))
        if watching and self.pointer_timer is None:
            self.pointer_timer = later(self.root, 16 if self.wheel.regions else 125, self.poll_pointer)
        elif not watching and self.pointer_timer is not None:
            cancel(self.pointer_timer)
            self.pointer_timer = None

    def observe_pointer(self) -> None:
        x, y = self.desktop.cursor_position()
        for card in self.cards.values():
            if not card.retiring:
                bounds = windows.outer_rect(card.handle)
                self.set_hover(card.key, inside=bounds.left <= x < bounds.right and bounds.top <= y < bounds.bottom)
        now = self.clock()
        if not any(card.motion is not None or card.reveals for card in self.cards.values()):
            samples = {sample.bounds: sample for sample in self.materials.read()}
            if samples:
                preference = self.environment.material()
                for card in self.cards.values():
                    if card.bounds is not None and (sample := samples.get(card.bounds)) is not None:
                        card.match_background(sample, preference)
            if now >= self.next_material:
                self.next_material = now + 0.75
                self.materials.submit(
                    tuple(card.bounds for card in self.cards.values() if card.glass and not card.retiring and card.bounds is not None)
                )

    def poll_pointer(self) -> None:
        self.pointer_timer = None
        if not self.closed:
            targets = {id(card.text): card.scroll_delta for card in self.cards.values() if not card.retiring}
            targets.update({id(card.details): card.scroll_details for card in self.cards.values() if not card.retiring})
            for event in self.wheel.drain():
                if (scroll := targets.get(event.target)) is not None:
                    scroll(event.delta)
            self.observe_pointer()
            self.schedule_pointer()

    def area(self) -> Rect:
        if self.work is not None:
            work = self.work
            return self.desktop.work_area(Rect(work.right - 1, work.bottom - 1, work.right, work.bottom))
        return self.desktop.work_area(self.monitor)

    def measured(self, toast: Toast, width: int) -> Measured:
        card = self.cards[toast.key]
        prepared = card.measure(self.content_for(toast), width)
        chrome = prepared.header_height + prepared.hint_height + prepared.padding
        return Measured(prepared.preferred, chrome, prepared.body_height, priority(toast.content))

    def sync_layers(self) -> None:
        # Qt rounds device-independent bounds during its layered paint. Align
        # the blur and shadow with those final physical pixels at fractional DPI.
        for card in self.cards.values():
            if not card.closed and card.window.isVisible():
                card.bounds = windows.outer_rect(card.handle)
                if card.glass and card.layer is not None:
                    card.layer.position(card.surface_bounds, self.scale, card.alpha)
                if card.tail_pending:
                    card.text.verticalScrollBar().setValue(card.text.verticalScrollBar().maximum())
                    card.tail_pending = False
        for message in self.session.messages:
            identity = _pending_approval(message)
            if identity is not None and self.approval_visible(identity):
                self.agent.input_presented(identity)

    def approval_visible(self, request_id: str) -> bool:
        """A painted, opaque card or visible history entry contains this review."""
        if self.closed:
            return False
        for card in self.cards.values():
            if card.closed or card.retiring or card.alpha < 0.99 or not card.window.isVisible() or not card.text.isVisible():
                continue
            match card.content:
                case Turn() as turn:
                    entries = results(turn)
                case Entry() as entry:
                    entries = (entry,)
                case _:
                    entries = ()
            if any(_entry_approval(entry) == request_id for entry in entries):
                return True
        return False

    def release(self, card: Card) -> None:
        del self.cards[card.key]
        card.park()
        self.spares = (*self.spares, card)

    def acquire(self, toast: Toast, width: int) -> Card:
        if not self.spares:
            card = self.create_card(self, toast, width)
        else:
            card = self.spares[-1]
            self.spares = self.spares[:-1]
            card.bind(toast, width)
        if self.live_progress and _phase(toast.key) is not None:
            card.expanded = toast.key == self.progress_head
        return card

    def retiring(self) -> tuple[Card, ...]:
        """Cards outside the projected stack, newest first."""
        desired = {toast.key for toast in self.stack.toasts}
        return tuple(sorted((card for key, card in self.cards.items() if key not in desired), key=card_order, reverse=True))

    def fit_viewport(self, viewport: Viewport, now: float) -> tuple[dict[Key, int], set[Key]]:
        created: set[Key] = set()
        # Create and measure before changing any visible card's contents/size.
        limits: dict[Key, int] = {}
        for _attempt in range(MAX_VISIBLE):
            # Reclaim surplus exits before acquiring arrivals. Active and spare
            # windows together stay bounded, even when a whole page is replaced.
            for card in self.retiring()[reservable(len(self.stack.toasts)) :]:
                self.release(card)
            for toast in self.stack.toasts:
                if toast.key not in self.cards:
                    self.cards[toast.key] = self.acquire(toast, viewport.width)
                    created.add(toast.key)
            retiring = self.retiring()
            measured = tuple(self.measured(toast, viewport.width) for toast in self.stack.toasts)
            fitted = fit(Column(measured, tuple(card.height for card in retiring), self.capacity), viewport)
            for card in retiring[fitted.reserved :]:
                self.release(card)
            limits = dict(zip((toast.key for toast in self.stack.toasts), fitted.heights, strict=True))
            if fitted.capacity == self.capacity:
                break
            self.capacity = fitted.capacity
            self.project(now, reveal=True)
            self.page = min(self.page, self.stack.pages - 1)
        return limits, created

    def sync(self, now: float, *, animate: bool | None = None) -> None:
        if not self.cards and not self.stack.toasts:
            self.work = None
            return
        animate = self.environment.animations() if animate is None else animate
        preference = self.environment.material()
        work = self.area()
        scale = self.loop.scale(work)
        immediate = self.work is not None and (self.work != work or self.scale != scale)
        self.work, self.scale = work, scale
        self.measure.scale = scale
        viewport = Viewport(work, scale, round(QFontMetricsF(font()).height() * scale * 1.38))
        if self.viewport != viewport:
            self.viewport = viewport
            self.capacity, self.page = MAX_VISIBLE, 0
            self.project(now, reveal=True)
        limits, created = self.fit_viewport(viewport, now)
        self.stack = replace(self.stack, toasts=tuple(toast for toast in self.stack.toasts if limits[toast.key]))
        desired = {toast.key for toast in self.stack.toasts}
        exits: tuple[Card, ...] = ()
        for key, card in tuple(self.cards.items()):
            if key in desired:
                # Reusing a fading recording restores its controls immediately;
                # fixed-width content may need no geometric change at all.
                immediate = immediate or (card.retiring and _recording(card.content))
                card.retiring = False
            elif not card.retiring:
                card.retiring = True
                if not animate or key in created:
                    self.release(card)
                else:
                    card.motion = None
                    exits = (*exits, card)
        retiring = sorted((card for card in self.cards.values() if card.retiring), key=card_order, reverse=True)
        for card in retiring[reservable(len(desired)) :]:
            self.release(card)
        for toast in self.stack.toasts:
            current = self.cards[toast.key]
            before = current.width, current.height
            current.render(self.content_for(toast), viewport.width, limits[toast.key], preference)
            # A resumed recording must restore usable controls immediately,
            # even when its fixed-width geometry matches the fading saved card.
            resized = before != (current.width, current.height)
            immediate = immediate or (toast.key not in created and _recording(toast.content) and (resized or current.alpha < 1))
            if toast.key in created:
                current.position(
                    work.right - viewport.margin,
                    Frame(
                        work.bottom - viewport.margin - current.height + viewport.rise,
                        current.width,
                        current.height,
                        0,
                        current.layout.details_height if current.layout is not None else 0,
                    ),
                )
                current.reveal()
            current.order = self.order_for(toast)
            current.check_pointer()
        # Native preparation consumes wall time. Start the shared transition
        # clock only once all arrivals are ready, so the first frame is not late.
        presented = self.clock()
        for card in exits:
            if card in self.cards.values():
                card.target(card.y - viewport.rise, 0, presented, animate=animate)
        self.layout(presented, animate=animate and not immediate, pushing=bool(created) and self.live_progress)
        self.tick()
        self.loop.watch(visible=bool(self.cards))
        self.loop.pump()

    def content_for(self, toast: Toast) -> Content:
        match toast.key, toast.content:
            case PhaseKey(), Turn() as turn if self.live_progress and toast.key != self.progress_head:
                return compact(turn)
            case _:
                return toast.content

    def order_for(self, toast: Toast) -> tuple[int, float, int, int]:
        # Live phases lead; history keeps chronology.
        group = (0 if _phase(toast.key) is not None else 1) if self.live_progress else 0
        return (group, *order_of(toast))

    def layout(self, now: float, *, animate: bool, pushing: bool = False) -> None:
        if self.work is None or self.viewport is None:
            return
        viewport = self.viewport
        right = viewport.area.right - viewport.margin
        cards = tuple(card for card in sorted(self.cards.values(), key=card_order, reverse=True) if not (self.live_progress and card.retiring))
        for card in cards:
            if card.right != right:
                card.position(right, card.frame)
        stacking = Stacking.FEED if not self.live_progress else Stacking.PUSH if pushing else Stacking.TRAIL
        slots = tuple(
            Retiring(card.height) if card.retiring else Active(card.height, card.motion.end.y if card.motion is not None else card.y)
            for card in cards
        )
        targets = tuple(
            (card, Frame(placement.y, card.width, card.height, placement.alpha, card.layout.details_height if card.layout is not None else 0))
            for card, placement in zip((card for card in cards if not card.retiring), frames(slots, viewport, stacking), strict=True)
        )
        changed = any(target != (card.motion.end if card.motion is not None else card.frame) for card, target in targets)
        # All active rectangles retarget on the same clock. Interpolating top
        # and bottom together preserves the gap between neighboring cards;
        # applying target heights before moving their tops would overlap them.
        for card, target in targets:
            card.target(target.y, target.alpha, now, animate=animate, retarget=changed)

    def older(self) -> None:
        self.page += 1
        self.reveal = True
        self.refresh()

    def newer(self) -> None:
        self.page = max(0, self.page - 1)
        self.reveal = True
        self.refresh()

    def action_link(self, link: str) -> None:
        if urlsplit(link).scheme in ("http", "https", "mailto"):
            webbrowser.open(link)
            return
        action = parse(link)
        match action:
            case OpenCanvas(target=target):
                self.canvas_open(target)
            case AnswerApproval(request=request, decision=decision):
                self.agent.respond(request, decision)
            case None:
                pass
            case _:
                assert_never(action)

    def toggle_card(self, selected: Card, *, animate: bool) -> None:
        """Qt owns disclosure state; collapse and expand on one layout clock."""
        expanded = not selected.expanded
        for card in self.cards.values():
            desired = expanded and card is selected
            if card.expanded == desired:
                continue
            if card.expanded:
                card.detail_offset = card.details.offset
            card.expanded = desired
            card.prepared = None
            card.layout = None
        self.sync(self.clock(), animate=animate and self.environment.animations())

    def dismiss_card(self, key: Key) -> None:
        card = self.cards.get(key)
        if card is None:
            return
        self.stack = hide(self.stack, key)
        self.refresh()

    def action(self, url: QtCore.QUrl) -> None:
        self.action_link(url.toString(QtCore.QUrl.ComponentFormattingOption.FullyEncoded))

    def sync_wheel(self) -> None:
        regions: list[Region] = []
        for card in self.cards.values():
            if card.retiring or card.bounds is None:
                continue
            if card.expanded and card.frame.details and card.prepared is not None:
                bounds = card.bounds
                top = bounds.top + card.prepared[2].header_height
                regions.append(Region(id(card.details), Rect(bounds.left, top, bounds.right, top + round(card.frame.details))))
            if card.overflow():
                regions.append(Region(id(card.text), card.bounds))
        self.wheel.update(tuple(regions))

    def tick(self) -> None:
        if self.animation_timer is not None:
            cancel(self.animation_timer)
            self.animation_timer = None
        if self.closed:
            return
        now = self.clock()
        removed = False
        spin = False
        revealing = False
        animate = self.environment.animations()
        reader = next(
            (card for card in sorted(self.cards.values(), key=card_order) if card.needs_reading() and (not self.live_progress or card.alpha >= 0.99)),
            None,
        )
        before = self.stack
        for key, card in tuple(self.cards.items()):
            if card.motion is not None:
                card.position(card.right, card.motion.sample(now) if animate else card.motion.end)
                if card.motion.finished(now) or not animate:
                    card.motion = None
                    if card.retiring:
                        self.release(card)
                        removed = True
                        continue
            if not card.closed:
                revealing = card.fade_text(now, animate=animate) or revealing
                reading_now = card.read(now, paused=card.hovered or card is not reader, smooth=animate)
                self.stack = reading_hold(
                    self.stack, key, reading=reading_now, now=now, busy=self.session.busy or self.session.waiting, hovered=card.hovered
                )
            if not card.closed and not card.retiring and card.content is not None and spinning(card.content):
                card.pulse(now if animate else 0)
                spin = spin or animate
        if removed:
            self.layout(now, animate=self.environment.animations())
        self.sync_wheel()
        self.schedule_pointer()
        moving = any(card.motion is not None for card in self.cards.values())
        scrolling = reader is not None and not reader.hovered
        sliding = scrolling and animate and _sliding(reader)
        self.environment.timer.update(active=moving or revealing or sliding)
        if self.stack is not before:
            self.schedule_expiry()
            self.schedule_pointer()
        if moving or revealing or spin or scrolling:
            interval = 1 / 60 if moving or revealing or sliding else 0.05
            delay = max(1, round((now + interval - self.clock()) * 1000))
            self.animation_timer = later(self.root, delay, self.tick)
        self.loop.watch(visible=bool(self.cards))
        self.loop.pump()
        if not self.cards:
            self.work = None

    def show(self, *, focus: bool = False) -> None:
        if self.closed:
            return
        self.refresh()
        if focus:
            cards = [card for card in self.cards.values() if not card.retiring and card.content is not None]
            if cards:
                cards[-1].text.setFocus(Qt.FocusReason.OtherFocusReason)

    def open_inbox(self) -> None:
        """Replace immutable feed selection; this owner updates the live Qt cards."""
        if self.closed:
            return
        self.stack = replace(self.stack, hidden=frozenset())
        self.history = False
        self.page = 0
        self.reveal = True
        self.show(focus=True)

    def show_history(self) -> None:
        if self.closed:
            return
        self.stack = replace(self.stack, hidden=frozenset())
        self.history = True
        self.page = 0
        self.reveal = True
        self.refresh()

    def resume(self) -> None:
        self.history = False
        self.page = 0
        self.refresh()

    def clear_cards(self) -> None:
        self.environment.timer.update(active=False)
        self.wheel.update(())
        if self.pointer_timer is not None:
            cancel(self.pointer_timer)
            self.pointer_timer = None
        if self.animation_timer is not None:
            cancel(self.animation_timer)
            self.animation_timer = None
        for card in tuple(self.cards.values()):
            self.release(card)
        self.loop.watch(visible=False)
        self.loop.pump()
        self.work = None
        self.next_material = 0.0

    def close(self) -> None:
        self.closed = True
        if self.expiry_timer is not None:
            cancel(self.expiry_timer)
            self.expiry_timer = None
        self.clear_cards()
        for card in self.spares:
            card.close()
        self.spares = ()
        self.wheel.close()
        self.materials.close()
        self.measure.close()
        self.loop.close()


def _phase(key: Key) -> PhaseKey | None:
    match key:
        case PhaseKey():
            return key
        case _:
            return None


def _pending_approval(message: Message) -> str | None:
    """The identity of an approval still waiting for the person's decision."""
    match message:
        case AgentRequest(request=Approval()) if pending(message):
            return message.id
        case _:
            return None


def _entry_approval(entry: Entry | Response) -> str | None:
    match entry:
        case Entry(message=message):
            return _pending_approval(message)
        case Response():
            return None


def _recording(content: Content | None) -> bool:
    match content:
        case Recording():
            return True
        case _:
            return False


def _sliding(reader: Card | None) -> bool:
    match reader:
        case Card(reader=notification_reading.Scrolling()):
            return True
        case _:
            return False


def card_order(card: Card) -> tuple[int, float, int, int]:
    return card.order
