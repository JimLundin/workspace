"""Recording the microphone, through the waveIn API."""

import ctypes
import math
import threading
import time
from array import array
from ctypes import wintypes
from dataclasses import dataclass, field, replace
from typing import Final, Protocol

from cell import Cell
from winapi._core import ULONG_PTR, fn, winmm
from winapi.system import EventHandle, wait_any


class WAVEFORMATEX(ctypes.Structure):
    wFormatTag: int
    nChannels: int
    nSamplesPerSec: int
    nAvgBytesPerSec: int
    nBlockAlign: int
    wBitsPerSample: int
    cbSize: int
    _pack_ = 1
    _fields_ = (
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    )


class WAVEHDR(ctypes.Structure):
    lpData: int | None
    dwBufferLength: int
    dwBytesRecorded: int
    dwUser: int
    dwFlags: int
    dwLoops: int
    lpNext: int | None
    reserved: int
    _fields_ = (
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser", ULONG_PTR),
        ("dwFlags", wintypes.DWORD),
        ("dwLoops", wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ULONG_PTR),
    )

    def __init__(self, data: int = 0, length: int = 0) -> None:
        super().__init__(data, length)


_64_BIT = ctypes.sizeof(ctypes.c_void_p) == 8
for _struct, _size in ((WAVEHDR, 48 if _64_BIT else 32), (WAVEFORMATEX, 18)):
    if ctypes.sizeof(_struct) != _size:
        raise ImportError(f"{_struct.__name__} is {ctypes.sizeof(_struct)} bytes; Windows expects {_size}")

_HWAVEIN = wintypes.HANDLE
_waveInOpen = fn(
    winmm, "waveInOpen", wintypes.UINT, ctypes.POINTER(_HWAVEIN), wintypes.UINT, ctypes.POINTER(WAVEFORMATEX), ULONG_PTR, ULONG_PTR, wintypes.DWORD
)
_waveInPrepareHeader = fn(winmm, "waveInPrepareHeader", wintypes.UINT, _HWAVEIN, ctypes.POINTER(WAVEHDR), wintypes.UINT)
_waveInUnprepareHeader = fn(winmm, "waveInUnprepareHeader", wintypes.UINT, _HWAVEIN, ctypes.POINTER(WAVEHDR), wintypes.UINT)
_waveInAddBuffer = fn(winmm, "waveInAddBuffer", wintypes.UINT, _HWAVEIN, ctypes.POINTER(WAVEHDR), wintypes.UINT)
_waveInStart = fn(winmm, "waveInStart", wintypes.UINT, _HWAVEIN)
_waveInReset = fn(winmm, "waveInReset", wintypes.UINT, _HWAVEIN)
_waveInClose = fn(winmm, "waveInClose", wintypes.UINT, _HWAVEIN)


class MMTIME(ctypes.Structure):
    kind: int
    value: int
    padding: int
    _fields_ = (("kind", wintypes.UINT), ("value", wintypes.DWORD), ("padding", wintypes.DWORD))

    def __init__(self, kind: int = 4, value: int = 0, padding: int = 0) -> None:
        super().__init__(kind, value, padding)


_waveInGetPosition = fn(winmm, "waveInGetPosition", wintypes.UINT, _HWAVEIN, ctypes.POINTER(MMTIME), wintypes.UINT)
_waveInMessage = fn(winmm, "waveInMessage", wintypes.UINT, _HWAVEIN, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p)

_WAVE_MAPPER: Final = 0xFFFF_FFFF
_WAVE_FORMAT_PCM: Final = 1
_CALLBACK_EVENT: Final = 0x0005_0000
_WHDR_DONE: Final = 0x01
_RETURN_TIMEOUT_MS: Final = 1000
_DRVM_MAPPER_PREFERRED_GET: Final = 0x2015
_DRV_QUERYFUNCTIONINSTANCEID: Final = 0x0811
_DRV_QUERYFUNCTIONINSTANCEIDSIZE: Final = 0x0812


class InputDriver(Protocol):
    """Owns the native handle and header operations consumed by capture.

    The header's memory stays owned by Microphone until reset returns it and
    unprepare releases it. Drivers update that same header, including its final
    byte count and completion flag; wait observes the supplied completion event.
    """

    def open(self, format: WAVEFORMATEX, event: EventHandle) -> tuple[int, wintypes.HANDLE]: ...
    def prepare(self, handle: wintypes.HANDLE, header: WAVEHDR) -> int: ...
    def add(self, handle: wintypes.HANDLE, header: WAVEHDR) -> int: ...
    def start(self, handle: wintypes.HANDLE) -> int: ...
    def reset(self, handle: wintypes.HANDLE) -> int: ...
    def unprepare(self, handle: wintypes.HANDLE, header: WAVEHDR) -> int: ...
    def close(self, handle: wintypes.HANDLE) -> int: ...
    def position(self, handle: wintypes.HANDLE, result: MMTIME) -> int: ...
    def wait(self, event: EventHandle, timeout_ms: int) -> bool: ...
    def device(self) -> str | None:
        """The capture endpoint the mapper would open now; None when it can't be observed."""
        ...


@dataclass(frozen=True, slots=True)
class WaveInput:
    """Adapts typed capture operations to Windows' positional waveIn contract."""

    def open(self, format: WAVEFORMATEX, event: EventHandle) -> tuple[int, wintypes.HANDLE]:
        handle = _HWAVEIN()
        error = int(_waveInOpen(ctypes.byref(handle), _WAVE_MAPPER, ctypes.byref(format), event, 0, _CALLBACK_EVENT))
        return error, handle

    def prepare(self, handle: wintypes.HANDLE, header: WAVEHDR) -> int:
        return int(_waveInPrepareHeader(handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR)))

    def add(self, handle: wintypes.HANDLE, header: WAVEHDR) -> int:
        return int(_waveInAddBuffer(handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR)))

    def start(self, handle: wintypes.HANDLE) -> int:
        return int(_waveInStart(handle))

    def reset(self, handle: wintypes.HANDLE) -> int:
        return int(_waveInReset(handle))

    def unprepare(self, handle: wintypes.HANDLE, header: WAVEHDR) -> int:
        return int(_waveInUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR)))

    def close(self, handle: wintypes.HANDLE) -> int:
        return int(_waveInClose(handle))

    def position(self, handle: wintypes.HANDLE, result: MMTIME) -> int:
        return int(_waveInGetPosition(handle, ctypes.byref(result), ctypes.sizeof(MMTIME)))

    def wait(self, event: EventHandle, timeout_ms: int) -> bool:
        return wait_any([event], timeout_ms=timeout_ms) is not None

    def device(self) -> str | None:
        index, flags = wintypes.DWORD(), wintypes.DWORD()
        if _waveInMessage(_HWAVEIN(_WAVE_MAPPER), _DRVM_MAPPER_PREFERRED_GET, ctypes.byref(index), ctypes.byref(flags)):
            return None
        # A device message addresses the device by its ID in the handle position.
        device = _HWAVEIN(index.value)
        size = wintypes.DWORD()
        if _waveInMessage(device, _DRV_QUERYFUNCTIONINSTANCEIDSIZE, ctypes.byref(size), None) or not 0 < size.value <= 4096:
            return None
        endpoint = ctypes.create_unicode_buffer(size.value // ctypes.sizeof(ctypes.c_wchar) + 1)
        if _waveInMessage(device, _DRV_QUERYFUNCTIONINSTANCEID, endpoint, size.value):
            return None
        return endpoint.value or None


def follows_default(opened: str | None, current: str | None) -> bool:
    """Reopen when the default capture endpoint is known to differ from the opened one.

    An unobservable default keeps the open handle rather than paying a reopen on every press.
    """
    return current is not None and current != opened


@dataclass(frozen=True, slots=True)
class _Capture:
    """One recording lifetime's native state, replaced whole under the microphone's lock."""

    handle: wintypes.HANDLE = field(default_factory=_HWAVEIN)
    device: str | None = None
    """The capture endpoint that was the default when the handle opened."""
    header: WAVEHDR = field(default_factory=WAVEHDR)
    """The queued buffer's header; the driver points at it until it is unprepared."""
    prepared: bool = False
    queued: bool = False
    stopping: bool = False
    last_position: int = 0
    """Where the level meter last read up to."""


@dataclass(frozen=True, slots=True)
class Microphone:
    """Records the default microphone as 16-bit mono PCM into one buffer, allocated
    once. Windows sets `event` whenever the recording changes state, including when
    the buffer is full. Opened at construction and kept ready until `close`, but
    only records between `start` and `stop`. After the default capture device
    changes, `follow_default` or the next press reopens on the new default, so
    dictation and the level meter observe the device Windows now selects."""

    event: EventHandle
    _driver: InputDriver
    _format: WAVEFORMATEX
    _buffer: ctypes.Array[ctypes.c_char]
    _capture: Cell[_Capture] = field(default_factory=lambda: Cell(_Capture()), init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    @classmethod
    def open(cls, rate: int, seconds: int, event: EventHandle, *, driver: InputDriver | None = None) -> Microphone:
        """A microphone on the default device, opened now: opening can take a second,
        so pay that before the talk key is pressed; start() retries and reports the
        error if it isn't available yet."""
        format = WAVEFORMATEX(_WAVE_FORMAT_PCM, 1, rate, rate * 2, 2, 16, 0)
        microphone = cls(event, WaveInput() if driver is None else driver, format, ctypes.create_string_buffer(rate * 2 * seconds))
        microphone._open()
        return microphone

    def _open(self) -> int:
        capture = self._capture.get()
        if capture.handle:
            return 0
        device = self._driver.device()
        error, handle = self._driver.open(self._format, self.event)
        if not error:
            self._capture.set(replace(capture, handle=handle, device=device))
        return error

    def start(self) -> int:
        """Starts recording on the ready microphone. 0, or Windows' error code."""
        with self._lock:
            return self._start()

    def _start(self) -> int:
        capture = self._capture.get()
        if capture.prepared:
            if not capture.stopping:
                return 0
            try:
                self.stop()  # finish cleanup after a failed stop before reusing its buffer
            except OSError as problem:
                return problem.errno or 1
        capture = self._capture.get()
        if capture.handle and follows_default(capture.device, self._driver.device()):
            self.close()
        if error := self._open():
            return error
        header = WAVEHDR(ctypes.addressof(self._buffer), len(self._buffer))
        capture = self._capture.update(lambda capture: replace(capture, header=header, last_position=0))
        if error := self._driver.prepare(capture.handle, header):
            self.close()
            return error
        capture = self._capture.update(lambda capture: replace(capture, prepared=True))
        if error := self._driver.add(capture.handle, header):
            self.close()
            return error
        capture = self._capture.update(lambda capture: replace(capture, queued=True))
        if error := self._driver.start(capture.handle):
            self.close()
        return error

    def follow_default(self) -> None:
        """Reopen an idle handle on a changed default capture device.

        Called periodically, so the first press after a change doesn't lose its
        opening words to the open. A press or release in progress keeps the lock;
        a recording or a closed handle is left to the next start.
        """
        if not self._lock.acquire(blocking=False):
            return
        try:
            capture = self._capture.get()
            if capture.prepared or not capture.handle or not follows_default(capture.device, self._driver.device()):
                return
            self.close()
            self._open()
        finally:
            self._lock.release()

    def full(self) -> bool:
        return bool(self._capture.get().header.dwFlags & _WHDR_DONE)

    def stop(self) -> bytes:
        """Returns the recording, keeping the microphone ready for the next press."""
        with self._lock:
            return self._stop()

    def _stop(self) -> bytes:
        capture = self._capture.get()
        if not capture.prepared:
            return b""
        capture = self._capture.update(lambda capture: replace(capture, stopping=True))
        recorded = b""
        if capture.queued:
            if error := self._driver.reset(capture.handle):
                raise OSError(error, "The microphone could not finish recording. Please try again.")
            self._wait_for_return()
            recorded = ctypes.string_at(self._buffer, int(capture.header.dwBytesRecorded))
        if error := self._driver.unprepare(capture.handle, capture.header):
            raise OSError(error, "The microphone could not release its recording buffer. Please try again.")
        self._capture.update(lambda capture: replace(capture, prepared=False, queued=False, stopping=False, header=WAVEHDR()))
        return recorded

    def level(self) -> float | None:
        """RMS of at most 40 ms of captured PCM; no wait and no full-buffer copy.

        The driver's byte position, rather than the unfinished header's byte
        count, marks data already recorded. Meter reads cannot overlap a reset
        or buffer release; a busy or unsupported device yields no observation.
        """
        if not self._lock.acquire(blocking=False):
            return None
        try:
            capture = self._capture.get()
            if not capture.queued or capture.stopping:
                return None
            position = MMTIME(4, 0, 0)  # TIME_BYTES; drivers may return TIME_SAMPLES.
            if self._driver.position(capture.handle, position):
                return None
            if position.kind not in (2, 4):
                return None
            end = min(len(self._buffer), int(position.value) * (2 if position.kind == 2 else 1)) & ~1
            # Windows reroutes an open mapper stream to a new default device and
            # restarts its byte position; the recorded count restarts with it.
            last = 0 if end < capture.last_position else capture.last_position
            if end == last:
                self._capture.set(replace(capture, last_position=last))
                return 0.0
            beginning = max(last, end - int(self._format.nSamplesPerSec) * 2 // 25) & ~1
            self._capture.set(replace(capture, last_position=end))
            samples = array("h", ctypes.string_at(ctypes.addressof(self._buffer) + beginning, end - beginning))
            return math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
        finally:
            self._lock.release()

    def _wait_for_return(self) -> None:
        """Keep the header and PCM alive until the driver returns the final data.

        Opening and starting the device signal the same event, so a signal alone
        is not proof that the last buffer is ready to read or unprepare.
        """
        deadline = time.monotonic() + _RETURN_TIMEOUT_MS / 1000
        while not self.full():
            remaining = round((deadline - time.monotonic()) * 1000)
            if remaining <= 0 or not self._driver.wait(self.event, remaining):
                raise OSError("Timed out waiting for the microphone's complete recording. Please try again.")

    def close(self) -> None:
        """Stops any recording and releases the microphone before its event closes."""
        with self._lock:
            if handle := self._capture.get().handle:
                self.stop()
                self._driver.close(handle)
                self._capture.update(lambda capture: replace(capture, handle=_HWAVEIN()))


def _follow_default(microphone: Microphone, interval: float, closing: threading.Event) -> None:
    while not closing.wait(interval):
        microphone.follow_default()


@dataclass(frozen=True, slots=True)
class DefaultFollower:
    """Owns the thread that keeps one microphone on the current default capture device."""

    _closing: threading.Event
    _thread: threading.Thread

    @classmethod
    def start(cls, microphone: Microphone, interval: float = 2.0) -> DefaultFollower:
        closing = threading.Event()
        arguments = (microphone, interval, closing)
        thread = threading.Thread(target=_follow_default, args=arguments, name="microphone default follower", daemon=True)
        thread.start()
        return cls(closing, thread)

    def close(self) -> None:
        """Returns once no reopen is in progress, so the microphone can close next."""
        self._closing.set()
        self._thread.join(timeout=2)
