"""Bounded conversation bubbles and history on the assistant UI thread."""

import time
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Final, TypedDict
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, StrictInt, TypeAdapter
lazy from PySide6 import QtCore
lazy from PySide6.QtCore import Qt
lazy from PySide6.QtGui import QFontMetricsF
lazy from PySide6.QtWidgets import QApplication

from assistant.agent_progress import Progress, advance_progress, compact, retain_lifetimes, visible
from assistant.canvas_activity import history_session, redirect_session
from assistant.qt_runtime import prepare
from assistant.toast_stack import Active, Column, Measured, Preview, Retiring, Stacking, Viewport, fit, frames, reservable
from usage import DIRECTORY
from winapi import appearance, windows
from winapi.shapes import Rect
lazy from assistant import console_requests, notification_reading
lazy from assistant.agent_session import Approval, Session, Snapshot, pending
lazy from assistant.agent_window import AgentWindow
lazy from assistant.feed_desktop import Desktop, NativeDesktop
lazy from assistant.feed_items import SourceKey, Verb, WorkItem, act, help_request
lazy from assistant.feed_triage import Assessment
lazy from assistant.inbox import Query, review_prompt
lazy from assistant.notifications import (
    MAX_VISIBLE,
    Content,
    Entry,
    Frame,
    Key,
    PhaseKey,
    Recording,
    Stack,
    Toast,
    Turn,
    advance,
    display_order,
    hide,
    hover,
    next_expiry,
    origin_item,
    priority,
    reading_hold,
    results,
    spinning,
)
lazy from assistant.qt_ui import EventLoop, cancel, later
lazy from assistant.toast_card import Card, Measure
lazy from assistant.ui_components.text import font
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
        "expiry_timer",
        "loop",
        "material_preference",
        "materials",
        "measure",
        "monitor",
        "motion_enabled",
        "next_material",
        "page",
        "pointer_timer",
        "progress",
        "progress_head",
        "query",
        "reveal",
        "root",
        "scale",
        "session",
        "spares",
        "stack",
        "timing",
        "viewport",
        "wheel",
        "work",
    )

    def __init__(
        self,
        root: QApplication,
        agent: AgentWindow,
        *,
        monitor: Rect | None = None,
        clock: Callable[[], float] = time.monotonic,
        motion_enabled: Callable[[], bool] = appearance.animations_enabled,
        material_preference: Callable[[], appearance.Preference] = appearance.preference,
        desktop: Desktop | None = None,
        create_card: Callable[[AgentToasts, Toast, int], Card] | None = None,
        timing: appearance.TimerResolution | None = None,
    ) -> None:
        # One view owns cards, desktop observation and motion timer lifetimes.
        # Independent monitor hint, clock and native adapters enter at construction
        # so every card shares that ownership; tests consume the same contracts.
        self.root, self.agent, self.clock, self.motion_enabled = root, agent, clock, motion_enabled
        self.desktop: Desktop = NativeDesktop() if desktop is None else desktop
        self.create_card = Card if create_card is None else create_card
        self.material_preference = material_preference
        self.materials = appearance.FrostSampler()
        self.monitor = monitor if monitor is not None else saved_monitor()
        self.session = Session()
        self.stack = Stack()
        self.progress = Progress()
        self.progress_head: PhaseKey | None = None
        self.loop = EventLoop(root, self.sync_layers)
        self.measure = Measure()
        self.timing = appearance.TimerResolution() if timing is None else timing
        self.wheel = WheelRouter()
        self.cards: dict[Key, Card] = {}
        # Qt owns these native resources. Keep at most MAX_VISIBLE surfaces for
        # this view's lifetime; replacing logical content must not rebuild them.
        self.spares: tuple[Card, ...] = ()
        self.closed = False
        self.query = Query()
        self.canvas_open: Callable[[str], None] | None = None
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

    def use_canvas(self, open_at: Callable[[str], None]) -> None:
        self.canvas_open = open_at

    def observation(self) -> Snapshot:
        if self.canvas_open is None:
            return self.session
        return history_session(self.session) if self.query.history else redirect_session(self.session)

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
        return self.canvas_open is not None and not self.query.history

    def project(self, now: float, *, reveal: bool = False) -> None:
        if not self.live_progress:
            self.stack = advance(self.stack, self.observation(), now, query=self.query, page=self.page, reveal=reveal, limit=self.capacity)
            return
        self.progress = advance_progress(retain_lifetimes(self.progress, self.stack), self.session, now)
        self.stack = visible(self.progress, self.capacity)
        latest = next((toast.key for toast in reversed(self.stack.toasts) if isinstance(toast.key, PhaseKey)), None)
        if latest != self.progress_head:
            self.progress_head = latest
            for key, card in self.cards.items():
                if isinstance(key, PhaseKey) and card.expanded:
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
                preference = self.material_preference()
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
        match toast.content:
            case WorkItem(item=Assessment()) if not card.expanded:
                preview = Preview.COMPLETE
            case _:
                preview = Preview.LINES
        chrome = prepared.header_height + prepared.hint_height + prepared.padding
        return Measured(prepared.preferred, chrome, prepared.body_height, priority(toast.content), preview)

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
            if isinstance(message, Approval) and pending(message) and self.approval_visible(message.request_id):
                self.agent.input_presented(message.request_id)

    def approval_visible(self, request_id: str) -> bool:
        """A painted, opaque card or visible history entry contains this review."""
        if self.closed:
            return False
        for card in self.cards.values():
            if card.closed or card.retiring or card.alpha < 0.99 or not card.window.isVisible() or not card.text.isVisible():
                continue
            content = card.content
            entries = results(content) if isinstance(content, Turn) else (content,) if isinstance(content, Entry) else ()
            if any(
                isinstance(entry, Entry) and isinstance(entry.message, Approval) and entry.message.request_id == request_id and pending(entry.message)
                for entry in entries
            ):
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
        if self.live_progress and isinstance(toast.key, PhaseKey):
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
        animate = self.motion_enabled() if animate is None else animate
        preference = self.material_preference()
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
                immediate = immediate or (card.retiring and isinstance(card.content, Recording))
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
            immediate = immediate or (
                toast.key not in created
                and (
                    (isinstance(toast.content, Recording) and (resized or current.alpha < 1))
                    or (resized and isinstance(toast.content, WorkItem) and isinstance(toast.content.item, Assessment))
                )
            )
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
        order = display_order(toast, curated=self.session.triage.enabled and not self.query.history)
        if self.live_progress:
            return (0 if isinstance(toast.key, PhaseKey) else 1, *order[1:])
        return order

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

    def review_feed(self) -> None:
        if self.agent.on_submit is not None:
            prompt = review_prompt(self.session.communications, self.query, self.session.console_requests)
            self.agent.on_submit(prompt)

    def action_link(self, url: str) -> None:
        self.action(QtCore.QUrl(url))

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
            if isinstance(card.content, WorkItem):
                card.text.verticalScrollBar().setValue(0)
            card.prepared = None
            card.layout = None
        self.sync(self.clock(), animate=animate and self.motion_enabled())

    def dismiss_card(self, key: Key) -> None:
        card = self.cards.get(key)
        if card is None:
            return
        if isinstance(card.content, WorkItem) and isinstance(card.content.item, Assessment):
            action = self.agent.on_dismiss_work
            if action is None or not action(card.content.item.identity):
                if self.agent.on_problem is not None:
                    self.agent.on_problem("That item could not be dismissed. It remains in your feed.")
                return
        self.stack = hide(self.stack, key)
        self.refresh()

    def action(self, url: QtCore.QUrl) -> None:
        parsed = urlsplit(url.toString())
        if parsed.scheme in ("http", "https", "mailto"):
            webbrowser.open(url.toString())
            return
        if parsed.scheme != "workspace":
            return
        if parsed.netloc == "canvas" and self.canvas_open is not None:
            target = parse_qs(parsed.query).get("target", [""])[0]
            if target:
                self.canvas_open(target)
            return
        if parsed.netloc == "agent-option":
            self.answer_option(parsed.query)
            return
        values = parse_qs(parsed.query)
        if parsed.netloc == "console-option":
            self.answer_console(values.get("message", [""])[0], values)
            return
        if parsed.netloc == "console-dismiss" and self.agent.on_console is not None:
            self.agent.on_console(console_requests.Dismiss(values.get("message", [""])[0]))
            return
        verb = next((verb for verb in Verb if verb.value == parsed.netloc), None)
        key = SourceKey(values.get("source", [""])[0], values.get("item", [""])[0])
        row = next((card.content for card in self.cards.values() if isinstance(card.content, WorkItem) and card.content.key == key), None)
        if verb is None or row is None:
            return
        if verb is Verb.HELP:
            prompt = help_request(row)
            if prompt and self.agent.on_submit is not None:
                self.query = Query()
                self.agent.on_submit(prompt)
            return
        command = act(row, verb)
        if command is not None and self.agent.on_communication is not None:
            self.agent.on_communication(command)

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
        animate = self.motion_enabled()
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
                revealing = (
                    card.fade_text(now, animate=animate and card.look is not None and not isinstance(card.look[2], appearance.Contrast)) or revealing
                )
                reading_now = card.read(now, paused=card.hovered or card is not reader, smooth=animate)
                self.stack = reading_hold(
                    self.stack, key, reading=reading_now, now=now, busy=self.session.busy or self.session.waiting, hovered=card.hovered
                )
            if not card.closed and not card.retiring and card.content is not None and spinning(card.content):
                card.pulse(now if animate else 0)
                spin = spin or animate
        if removed:
            self.layout(now, animate=self.motion_enabled())
        self.sync_wheel()
        self.schedule_pointer()
        moving = any(card.motion is not None for card in self.cards.values())
        scrolling = reader is not None and not reader.hovered
        sliding = reader is not None and scrolling and animate and isinstance(reader.reader, notification_reading.Scrolling)
        self.timing.update(active=moving or revealing or sliding)
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
        self.query = Query()
        self.page = 0
        self.reveal = True
        self.show(focus=True)

    def show_history(self) -> None:
        if self.closed:
            return
        self.stack = replace(self.stack, hidden=frozenset())
        self.query = replace(self.query, history=True)
        self.page = 0
        self.reveal = True
        self.refresh()

    def resume(self) -> None:
        self.query = replace(self.query, history=False)
        self.page = 0
        self.refresh()

    def clear_cards(self) -> None:
        self.timing.update(active=False)
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

    def answer_console(self, identity: str, values: dict[str, list[str]]) -> None:
        index = values.get("question", ["0"])[0]
        if not index.isdecimal():
            return
        question = int(index)
        answer = values.get("answer", [""])[0]
        for card in self.cards.values():
            origin = origin_item(card.content)
            match origin:
                case WorkItem(item=console_requests.Request(identity=request_id, questions=questions, state=console_requests.State.WAITING)):
                    if (
                        not card.retiring
                        and request_id == identity
                        and 0 <= question < len(questions)
                        and not questions[question].multiple
                        and answer in (option.label for option in questions[question].options)
                        and self.agent.on_console is not None
                    ):
                        self.agent.on_console(console_requests.Answer(identity, question, answer))
                        break
                case _:
                    pass

    def answer_option(self, query: str) -> None:
        values = parse_qs(query)
        self.agent.respond(values.get("request", [""])[0], values.get("answer", [""])[0])


def card_order(card: Card) -> tuple[int, float, int, int]:
    return card.order
