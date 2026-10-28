import ctypes

class D2D_POINT_2F(ctypes.Structure):
    def __init__(self, x: float, y: float) -> None: ...

class D2D1_BEZIER_SEGMENT(ctypes.Structure):
    def __init__(self, first: D2D_POINT_2F, second: D2D_POINT_2F, end: D2D_POINT_2F) -> None: ...
