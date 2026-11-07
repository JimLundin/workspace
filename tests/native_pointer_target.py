"""One native fixture window answers hit queries from its own message thread."""

import socket
import sys
import threading
from contextlib import suppress
from ctypes import wintypes
from dataclasses import dataclass

lazy from winapi import screen, shell, system, windows
lazy from winapi._core import fn, user32
lazy from winapi.shapes import Rect

point_window = fn(user32, "WindowFromPhysicalPoint", wintypes.HWND, wintypes.POINT)
ancestor = fn(user32, "GetAncestor", wintypes.HWND, wintypes.HWND, wintypes.UINT)


@dataclass(frozen=True, slots=True)
class TargetRequest:
    port: int
    title: str
    bounds: Rect


def arguments() -> TargetRequest:
    match sys.argv[1:]:
        case [port, title, left, top, right, bottom]:
            bounds = Rect(int(left), int(top), int(right), int(bottom))
            if bounds.width <= 0 or bounds.height <= 0:
                raise ValueError("The native pointer target requires a visible rectangle.")
            return TargetRequest(int(port), title, bounds)
        case _:
            raise ValueError("The native pointer target requires its endpoint and rectangle.")


def point(line: str) -> tuple[int, int]:
    match line.strip().split(":"):
        case ["hit", x, y]:
            return int(x), int(y)
        case _:
            raise ValueError("The native pointer target received an invalid query.")


def serve(request: TargetRequest) -> None:
    """Own the target HWND, request socket and reader until native shutdown."""
    screen.use_physical_pixels()
    with socket.create_connection(("127.0.0.1", request.port), timeout=10) as peer:
        # Windows requires the HWND/message/two-payload callback signature.
        def message(hwnd: int, event: int, wparam: int, lparam: int) -> int | None:
            if event == system.WM_APP + 1:
                hit = ancestor(point_window(wintypes.POINT(wparam, lparam)), 2) or 0
                peer.sendall(f"hit:{hit}\n".encode("ascii"))
                return 0
            if event == system.WM_CLOSE:
                system.post_quit()
                return 0
            return None

        window = shell.AppWindow(request.title, message)

        def requests() -> None:
            try:
                with peer.makefile("r", encoding="ascii") as source:
                    for line in source:
                        x, y = point(line)
                        if not system.post_message(window.handle, system.WM_APP + 1, x, y):
                            raise OSError("The native pointer target refused its query.")
            finally:
                system.post_message(window.handle, system.WM_CLOSE, 0, 0)

        reader = threading.Thread(target=requests, name="native pointer requests", daemon=True)
        try:
            windows.move(window.handle, request.bounds)
            windows.show_quietly(window.handle, visible=True, topmost=False)
            peer.sendall(f"ready:{window.handle}:{windows.process_id(window.handle)}\n".encode("ascii"))
            reader.start()
            system.run_message_loop()
        finally:
            window.destroy()
            with suppress(OSError):
                peer.shutdown(socket.SHUT_RDWR)
            if reader.ident is not None:
                reader.join(timeout=2)
                if reader.is_alive():
                    raise RuntimeError("The native pointer reader survived its target.")


if __name__ == "__main__":
    serve(arguments())
