# Consumed VARIANT reading and writing: the type tag and the byte, signed 32-bit
# and BSTR members of its value union. VariantClear frees an owned BSTR.
import ctypes
from typing import type_check_only

VT_BSTR: int
VT_I4: int
VT_LPWSTR: int
VT_UI1: int

@type_check_only
class _Value(ctypes.Union):
    bVal: int
    lVal: int
    bstrVal: str | None

@type_check_only
class _Tagged(ctypes.Structure):
    vt: int
    Anonymous: _Value

@type_check_only
class _Variant(ctypes.Union):
    Anonymous: _Tagged

class VARIANT(ctypes.Structure):
    Anonymous: _Variant

def VariantClear(value: VARIANT) -> int: ...
