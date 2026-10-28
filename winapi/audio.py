"""Recording the microphone, through the waveIn API."""

import ctypes
import math
import threading
import time
from array import array
from ctypes import wintypes
from typing import Final, Protocol

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

_WAVE_MAPPER: Final = 0xFFFF_FFFF
_WAVE_FORMAT_PCM: Final = 1
_CALLBACK_EVENT: Final = 0x0005_0000
_WHDR_DONE: Final = 0x01
_RETURN_TIMEOUT_MS: Final = 1000


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


class WaveInput:
    """Adapts typed capture operations to Windows' positional waveIn contract."""

    __slots__ = ()

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


class Microphone:
    """Records the default microphone as 16-bit mono PCM into one buffer, allocated
    once. Windows sets `event` whenever the recording changes state, including when
    the buffer is full. Opened at construction and kept ready until `close`, but
    only records between `start` and `stop`."""

    __slots__ = ("_buffer", "_driver", "_format", "_handle", "_header", "_last_position", "_lock", "_prepared", "_queued", "_stopping", "event")

    # The buffer format/capacity, completion event and native driver jointly
    # define one recording lifetime; the driver remains a keyword-only port.
    def __init__(self, rate: int, seconds: int, event: EventHandle, *, driver: InputDriver | None = None) -> None:
        self._driver: InputDriver = WaveInput() if driver is None else driver
        self._format = WAVEFORMATEX(_WAVE_FORMAT_PCM, 1, rate, rate * 2, 2, 16, 0)
        self._buffer = ctypes.create_string_buffer(rate * 2 * seconds)
        self._handle = _HWAVEIN()
        self._header = WAVEHDR()
        self._prepared = False
        self._queued = False
        self._stopping = False
        self._lock = threading.RLock()
        self._last_position = 0
        self.event = event
        # Opening a device can take a second. Pay that cost before the talk key is
        # pressed; start() retries and reports the error if it isn't available yet.
        self._open()

    def _open(self) -> int:
        if self._handle:
            return 0
        error, handle = self._driver.open(self._format, self.event)
        if not error:
            self._handle = handle
        return error

    def start(self) -> int:
        """Starts recording on the ready microphone. 0, or Windows' error code."""
        with self._lock:
            return self._start()

    def _start(self) -> int:
        if self._prepared:
            if not self._stopping:
                return 0
            try:
                self.stop()  # finish cleanup after a failed stop before reusing its buffer
            except OSError as problem:
                return problem.errno or 1
        if error := self._open():
            return error
        self._header = WAVEHDR(ctypes.addressof(self._buffer), len(self._buffer))
        self._last_position = 0
        if error := self._driver.prepare(self._handle, self._header):
            self.close()
            return error
        self._prepared = True
        if error := self._driver.add(self._handle, self._header):
            self.close()
            return error
        self._queued = True
        if error := self._driver.start(self._handle):
            self.close()
        return error

    def full(self) -> bool:
        return bool(self._header.dwFlags & _WHDR_DONE)

    def stop(self) -> bytes:
        """Returns the recording, keeping the microphone ready for the next press."""
        with self._lock:
            return self._stop()

    def _stop(self) -> bytes:
        if not self._prepared:
            return b""
        self._stopping = True
        recorded = b""
        if self._queued:
            if error := self._driver.reset(self._handle):
                raise OSError(error, "The microphone could not finish recording. Please try again.")
            self._wait_for_return()
            recorded = ctypes.string_at(self._buffer, int(self._header.dwBytesRecorded))
        if error := self._driver.unprepare(self._handle, self._header):
            raise OSError(error, "The microphone could not release its recording buffer. Please try again.")
        self._prepared = False
        self._queued = False
        self._stopping = False
        self._header = WAVEHDR()
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
            if not self._queued or self._stopping:
                return None
            position = MMTIME(4, 0, 0)  # TIME_BYTES; drivers may return TIME_SAMPLES.
            if self._driver.position(self._handle, position):
                return None
            if position.kind not in (2, 4):
                return None
            end = min(len(self._buffer), int(position.value) * (2 if position.kind == 2 else 1)) & ~1
            if end <= self._last_position:
                return 0.0
            beginning = max(self._last_position, end - int(self._format.nSamplesPerSec) * 2 // 25) & ~1
            self._last_position = end
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
            if self._handle:
                self.stop()
                self._driver.close(self._handle)
                self._handle = _HWAVEIN()
