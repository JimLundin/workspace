"""The laptop's own panel brightness, read and set over WMI (root\\WMI's WmiMonitorBrightness).

DDC/CI doesn't reach a built-in panel and this machine has no legacy `\\\\.\\LCD`
device, so WMI is the way in. Only an active panel answers: with the lid
closed there is none, and every call reports `Unavailable`. Brightness 0 is the
darkest the panel goes; an LCD's backlight stays faintly on.
"""

import ctypes
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

lazy from win32more import FAILED
lazy from win32more.Windows.Win32.System.Com import (
    CLSCTX_INPROC_SERVER,
    COINIT_MULTITHREADED,
    EOAC_NONE,
    RPC_C_AUTHN_LEVEL_CALL,
    RPC_C_IMP_LEVEL_IMPERSONATE,
    CoCreateInstance,
    CoInitializeEx,
    CoSetProxyBlanket,
    CoUninitialize,
)
lazy from win32more.Windows.Win32.System.Rpc import RPC_C_AUTHN_WINNT, RPC_C_AUTHZ_NONE
lazy from win32more.Windows.Win32.System.Variant import VARIANT, VT_BSTR, VT_I4, VT_UI1, VariantClear
lazy from win32more.Windows.Win32.System.Wmi import (
    WBEM_FLAG_FORWARD_ONLY,
    WBEM_FLAG_RETURN_IMMEDIATELY,
    WBEM_INFINITE,
    IEnumWbemClassObject,
    IWbemClassObject,
    IWbemLocator,
    IWbemServices,
    WbemLocator,
)


@dataclass(frozen=True, slots=True)
class Level:
    """The panel's brightness, as a percentage from 0 to 100."""

    value: int


@dataclass(frozen=True, slots=True)
class Unavailable:
    """No active built-in panel answered, or WMI refused the request."""


@contextmanager
def _namespace() -> Generator[IWbemServices | None]:
    """root\\WMI on this machine, in the multithreaded apartment; None when WMI can't be reached."""
    if FAILED(CoInitializeEx(None, COINIT_MULTITHREADED)):
        yield None
        return
    locator = IWbemLocator(own=True)
    services = IWbemServices(own=True)
    try:
        if (
            FAILED(CoCreateInstance(WbemLocator, None, CLSCTX_INPROC_SERVER, IWbemLocator._iid_, locator))
            or FAILED(locator.ConnectServer("ROOT\\WMI", None, None, None, 0, None, None, services))
            or FAILED(
                CoSetProxyBlanket(
                    services, RPC_C_AUTHN_WINNT, RPC_C_AUTHZ_NONE, None, RPC_C_AUTHN_LEVEL_CALL, RPC_C_IMP_LEVEL_IMPERSONATE, None, EOAC_NONE
                )
            )
        ):
            yield None
        else:
            yield services
    finally:
        del services, locator
        CoUninitialize()


def _active(services: IWbemServices, wmi_class: str, column: str) -> IWbemClassObject | None:
    """The active panel's row of `wmi_class`, with `column`; None when no panel is active."""
    rows = IEnumWbemClassObject(own=True)
    query = f"SELECT {column} FROM {wmi_class} WHERE Active = TRUE"
    if FAILED(services.ExecQuery("WQL", query, WBEM_FLAG_FORWARD_ONLY | WBEM_FLAG_RETURN_IMMEDIATELY, None, rows)):
        return None
    row = IWbemClassObject(own=True)
    returned = ctypes.c_uint32()
    if FAILED(rows.Next(WBEM_INFINITE, 1, row, returned)) or returned.value != 1:
        return None
    return row


def brightness() -> Level | Unavailable:
    try:
        with _namespace() as services:
            row = None if services is None else _active(services, "WmiMonitorBrightness", "CurrentBrightness")
            if row is None:
                return Unavailable()
            value = VARIANT()
            try:
                if FAILED(row.Get("CurrentBrightness", 0, value, None, None)) or value.Anonymous.Anonymous.vt != VT_UI1:
                    return Unavailable()
                level = int(value.Anonymous.Anonymous.Anonymous.bVal)
            finally:
                VariantClear(value)
                del row  # Released before the apartment closes.
            return Level(level) if 0 <= level <= 100 else Unavailable()
    except OSError:
        return Unavailable()


def set_brightness(level: int) -> Level | Unavailable:
    """Sets the panel to `level` percent at once; the level set, or Unavailable when refused."""
    if level not in range(101):
        raise ValueError(f"brightness is a percentage from 0 to 100, not {level!r}")
    try:
        with _namespace() as services:
            if services is None:
                return Unavailable()
            row = _active(services, "WmiMonitorBrightnessMethods", "__PATH")
            if row is None:
                return Unavailable()
            path = VARIANT()
            methods, signature, arguments = IWbemClassObject(own=True), IWbemClassObject(own=True), IWbemClassObject(own=True)
            timeout, wanted = VARIANT(), VARIANT()
            try:
                if FAILED(row.Get("__PATH", 0, path, None, None)) or path.Anonymous.Anonymous.vt != VT_BSTR:
                    return Unavailable()
                instance = path.Anonymous.Anonymous.Anonymous.bstrVal
                if instance is None:
                    return Unavailable()
                # WMI carries a uint32 argument as VT_I4 and a uint8 as VT_UI1.
                timeout.Anonymous.Anonymous.vt, timeout.Anonymous.Anonymous.Anonymous.lVal = VT_I4, 0
                wanted.Anonymous.Anonymous.vt, wanted.Anonymous.Anonymous.Anonymous.bVal = VT_UI1, level
                if (
                    FAILED(services.GetObject("WmiMonitorBrightnessMethods", 0, None, methods, None))
                    or FAILED(methods.GetMethod("WmiSetBrightness", 0, signature, None))
                    or FAILED(signature.SpawnInstance(0, arguments))
                    or FAILED(arguments.Put("Timeout", 0, timeout, 0))
                    or FAILED(arguments.Put("Brightness", 0, wanted, 0))
                    or FAILED(services.ExecMethod(instance, "WmiSetBrightness", 0, None, arguments, None, None))
                ):
                    return Unavailable()
                return Level(level)
            finally:
                VariantClear(path)
                del arguments, signature, methods, row  # Released before the apartment closes.
    except OSError:
        return Unavailable()
