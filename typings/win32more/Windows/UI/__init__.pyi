import ctypes

class Color(ctypes.Structure):
    def __init__(self, alpha: int, red: int, green: int, blue: int) -> None: ...
    A: int
    R: int
    G: int
    B: int
