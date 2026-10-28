import ctypes

class Vector2(ctypes.Structure):
    def __init__(self, x: float, y: float) -> None: ...
    X: float
    Y: float

class Vector3(ctypes.Structure):
    def __init__(self, x: float, y: float, z: float) -> None: ...
    X: float
    Y: float
    Z: float
