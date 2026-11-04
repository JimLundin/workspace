# Consumed PROPVARIANT reading: the type tag and the string member of its value union.
import ctypes
from typing import type_check_only

@type_check_only
class _Value(ctypes.Union):
    pwszVal: str | None

@type_check_only
class _Tagged(ctypes.Structure):
    vt: int
    Anonymous: _Value

@type_check_only
class _Variant(ctypes.Union):
    Anonymous: _Tagged

class PROPVARIANT(ctypes.Structure):
    Anonymous: _Variant

def PropVariantClear(value: PROPVARIANT) -> int: ...
