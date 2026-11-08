"""Desktop material preferences and bounded background observations.

Composition and Qt retain opaque text on a translucent surface. This module
reads accessibility settings and samples nearby pixels off the UI thread.
"""

import ctypes
import math
import threading
import winreg
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from ctypes import wintypes
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Protocol

from cell import Cell
from winapi._core import GetDC, ReleaseDC, fn, gdi32, user32, winmm
from winapi.shapes import Rect


class Material(Enum):
    GLASS = auto()
    SOLID = auto()


class Frost(Enum):
    LIGHT = auto()
    SMOKED = auto()
    BRIGHT = auto()


@dataclass(frozen=True, slots=True)
class Backdrop:
    bounds: Rect
    frost: Frost


def sample_backgrounds(bounds: tuple[Rect, ...]) -> tuple[Backdrop, ...]:
    return tuple(Backdrop(rect, background_frost(rect)) for rect in bounds)


@dataclass(frozen=True, slots=True)
class _Sampling:
    worker: ThreadPoolExecutor | None = None
    pending: Future[tuple[Backdrop, ...]] | None = None


@dataclass(frozen=True, slots=True)
class FrostSampler:
    """One bounded background read; GetPixel can wait on the desktop compositor.

    The UI submits immutable bounds and polls the result on its existing pointer
    timer. This worker never touches widgets, and neither submitting nor polling waits
    for desktop pixels. The owner discards observations after a card moves.
    """

    sample: Callable[[tuple[Rect, ...]], tuple[Backdrop, ...]] = sample_backgrounds
    _sampling: Cell[_Sampling] = field(default_factory=lambda: Cell(_Sampling()), init=False, repr=False)

    def submit(self, bounds: tuple[Rect, ...]) -> None:
        sampling = self._sampling.get()
        if not bounds or sampling.pending is not None:
            return
        worker = sampling.worker or ThreadPoolExecutor(max_workers=1, thread_name_prefix="workspace-glass")
        self._sampling.set(_Sampling(worker, worker.submit(self.sample, bounds)))

    def read(self) -> tuple[Backdrop, ...]:
        sampling = self._sampling.get()
        if sampling.pending is None or not sampling.pending.done():
            return ()
        self._sampling.set(replace(sampling, pending=None))
        return sampling.pending.result()

    def close(self) -> None:
        if (worker := self._sampling.get().worker) is not None:
            worker.shutdown(wait=False, cancel_futures=True)
        self._sampling.set(_Sampling())


@dataclass(frozen=True, slots=True)
class Contrast:
    background: str
    foreground: str


type Preference = Material | Contrast


class _HighContrast(ctypes.Structure):
    size: int
    flags: int
    scheme: str | None
    _fields_ = [("size", wintypes.UINT), ("flags", wintypes.DWORD), ("scheme", wintypes.LPWSTR)]


_SystemParametersInfoW = fn(user32, "SystemParametersInfoW", wintypes.BOOL, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT)
_GetSysColor = fn(user32, "GetSysColor", wintypes.DWORD, ctypes.c_int)
_GetPixel = fn(gdi32, "GetPixel", wintypes.DWORD, wintypes.HDC, ctypes.c_int, ctypes.c_int)
_TimeBeginPeriod = fn(winmm, "timeBeginPeriod", wintypes.UINT, wintypes.UINT)
_TimeEndPeriod = fn(winmm, "timeEndPeriod", wintypes.UINT, wintypes.UINT)


class TimerPeriod(Protocol):
    def request(self) -> bool: ...

    def release(self) -> None: ...


@dataclass(frozen=True, slots=True)
class NativeTimerPeriod:
    def request(self) -> bool:
        return bool(_TimeBeginPeriod(1) == 0)

    def release(self) -> None:
        _TimeEndPeriod(1)


@dataclass(frozen=True, slots=True)
class TimerResolution:
    """Keep the UI's short frame timers accurate only while UI motion is running.

    Windows' default timer granularity can turn a 16 ms wait into 31 ms. Each
    successful request is balanced when movement ends, history opens or the
    view closes; idle notifications and the keyboard process never request it.
    """

    period: TimerPeriod = field(default_factory=NativeTimerPeriod)
    _active: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    """Set while a granted request is outstanding."""

    @property
    def active(self) -> bool:
        return self._active.is_set()

    def update(self, *, active: bool) -> None:
        if active and not self.active:
            if self.period.request():
                self._active.set()
        elif not active and self.active:
            self.period.release()
            self._active.clear()


def animations_enabled() -> bool:
    enabled = wintypes.BOOL()
    return bool(_SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0) and enabled.value)  # SPI_GETCLIENTAREAANIMATION


def preference() -> Preference:
    contrast = _HighContrast(ctypes.sizeof(_HighContrast), 0, None)
    if not _SystemParametersInfoW(0x0042, contrast.size, ctypes.byref(contrast), 0):  # SPI_GETHIGHCONTRAST
        return Material.SOLID
    if contrast.flags & 1:
        return Contrast(system_color(5), system_color(8))  # COLOR_WINDOW, COLOR_WINDOWTEXT
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            enabled, _kind = winreg.QueryValueEx(key, "EnableTransparency")
    except OSError:
        return Material.SOLID
    return Material.GLASS if enabled == 1 else Material.SOLID


def light_apps() -> bool:
    """Windows' app mode: large glass and content windows follow it."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            light, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
    except OSError:
        return False
    return light == 1


def system_color(index: int) -> str:
    value = int(_GetSysColor(index))
    return f"#{value & 255:02x}{value >> 8 & 255:02x}{value >> 16 & 255:02x}"


def background_frost(bounds: Rect) -> Frost:
    """Sample four surrounding pixels, off the animation path; retain no image.

    Uniform dark and bright surroundings can use a light tint with contrasting
    ink. Mixed or unavailable backgrounds need more shading. Only neighboring
    pixels are read, and no desktop image is retained.
    """
    dc = GetDC(None)
    if not dc:
        return Frost.SMOKED
    # Sample the sides: above/below can contain a neighboring conversation bubble.
    points = tuple((x, bounds.top + bounds.height * third // 3) for x in (bounds.left - 12, bounds.right + 12) for third in (1, 2))
    try:
        colors = tuple(color for px, py in points if (color := int(_GetPixel(dc, px, py))) != 0xFFFF_FFFF)
    finally:
        ReleaseDC(None, dc)
    return frost_for(colors)


def frost_for(colors: tuple[int, ...]) -> Frost:
    """Use light glass on uniform backgrounds; shade mixed or unknown surfaces."""
    values = tuple(luminance(color) for color in colors)
    if values and all(value < 0.18 for value in values):
        return Frost.LIGHT
    if values and all(value > 0.5 for value in values):
        return Frost.BRIGHT
    return Frost.SMOKED


def luminance(color: int) -> float:
    channels = tuple((color >> shift & 255) / 255 for shift in (0, 8, 16))
    linear = tuple(value / 12.92 if value <= 0.04045 else math.pow((value + 0.055) / 1.055, 2.4) for value in channels)
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))
