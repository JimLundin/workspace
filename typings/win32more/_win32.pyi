import ctypes
from typing import ClassVar, Protocol, type_check_only

@type_check_only
class ByReference[T](Protocol):
    @property
    def _obj(self) -> T: ...

@type_check_only
class OutputPointer[T](Protocol):
    contents: T
    def __setitem__(self, index: int, value: T, /) -> None: ...

class Guid(ctypes.Structure):
    def __init__(self, value: str) -> None: ...

class ComPtr(ctypes.c_void_p):
    _iid_: ClassVar[Guid]
    def __init__(self, *, own: bool = False) -> None: ...
    def as_[T: ComPtr](self, interface: type[T]) -> T: ...
    def AddRef(self) -> int: ...
