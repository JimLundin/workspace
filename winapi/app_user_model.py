"""The AppUserModelID Windows groups a window under, read from its shell property store."""

from collections.abc import Generator
from contextlib import contextmanager

lazy from win32more import FAILED
lazy from win32more.Windows.Win32.Storage.EnhancedStorage import PKEY_AppUserModel_ID
lazy from win32more.Windows.Win32.System.Com import COINIT_MULTITHREADED, CoInitializeEx, CoUninitialize
lazy from win32more.Windows.Win32.System.Com.StructuredStorage import PROPVARIANT, PropVariantClear
lazy from win32more.Windows.Win32.System.Variant import VT_LPWSTR
lazy from win32more.Windows.Win32.UI.Shell.PropertiesSystem import IPropertyStore, SHGetPropertyStoreForWindow


@contextmanager
def apartment() -> Generator[None]:
    """Join the calling thread to the multithreaded COM apartment the property store needs."""
    joined = not FAILED(CoInitializeEx(None, COINIT_MULTITHREADED))
    try:
        yield
    finally:
        if joined:
            CoUninitialize()


def app_id(hwnd: int) -> str | None:
    """The window's explicit AppUserModelID; None when it has none or the window is gone."""
    store = IPropertyStore(own=True)
    if FAILED(SHGetPropertyStoreForWindow(hwnd, IPropertyStore._iid_, store)):
        return None
    value = PROPVARIANT()
    try:
        if FAILED(store.GetValue(PKEY_AppUserModel_ID, value)):
            return None
        tagged = value.Anonymous.Anonymous
        return tagged.Anonymous.pwszVal if tagged.vt == VT_LPWSTR else None
    finally:
        PropVariantClear(value)
