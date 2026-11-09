import ctypes

HCF_HIGHCONTRASTON: int

class HIGHCONTRASTW(ctypes.Structure):
    cbSize: int
    dwFlags: int
    def __init__(self, *, cbSize: int) -> None: ...
