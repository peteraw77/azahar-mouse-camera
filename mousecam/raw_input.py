"""Raw mouse movement via the Windows Raw Input API.

Raw counts come straight from the mouse. Unlike cursor positions, they ignore
pointer acceleration and don't stop at screen edges or when the cursor is locked.
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import POINTER, byref, sizeof, wintypes

from mousecam.win32 import HWND_MESSAGE, WindowThread, last_error, user32

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000100  # keep receiving input while another program has focus
RIDEV_REMOVE = 0x00000001
MOUSE_MOVE_ABSOLUTE = 0x0001
USAGE_PAGE_GENERIC = 0x01
USAGE_MOUSE = 0x02


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("ulButtons", wintypes.ULONG),  # a union in the C header; unused here
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


user32.RegisterRawInputDevices.argtypes = [POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.GetRawInputData.argtypes = [
    wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID, POINTER(wintypes.UINT), wintypes.UINT,
]
user32.GetRawInputData.restype = wintypes.UINT


class RawMouse(WindowThread):
    """Adds up mouse movement in the background until take() collects it."""

    def __init__(self) -> None:
        super().__init__(parent=HWND_MESSAGE)
        self._lock = threading.Lock()
        self._dx = 0
        self._dy = 0
        self._raw = RAWINPUT()

    def take(self) -> tuple[int, int]:
        """Return the counts moved since the last call. +x is right, +y is down."""
        with self._lock:
            result = self._dx, self._dy
            self._dx = self._dy = 0
        return result

    def on_create(self) -> None:
        if not self._register(RIDEV_INPUTSINK, self.hwnd):
            raise last_error("RegisterRawInputDevices")

    def on_destroy(self) -> None:
        self._register(RIDEV_REMOVE, None)

    def on_message(self, msg: int, wparam: int, lparam: int) -> int | None:
        if msg == WM_INPUT:
            self._read(lparam)
        return None  # WM_INPUT must still reach DefWindowProc, which cleans up

    def _register(self, flags: int, hwnd: wintypes.HWND | None) -> bool:
        device = RAWINPUTDEVICE(USAGE_PAGE_GENERIC, USAGE_MOUSE, flags, hwnd)
        return bool(user32.RegisterRawInputDevices(byref(device), 1, sizeof(device)))

    def _read(self, handle: int) -> None:
        size = wintypes.UINT(sizeof(self._raw))
        copied = user32.GetRawInputData(
            handle, RID_INPUT, byref(self._raw), byref(size), sizeof(RAWINPUTHEADER)
        )
        if copied == wintypes.UINT(-1).value or self._raw.header.dwType != RIM_TYPEMOUSE:
            return
        mouse = self._raw.mouse
        # Absolute reports (remote desktop, some tablets) are positions, not deltas.
        if mouse.usFlags & MOUSE_MOVE_ABSOLUTE:
            return
        with self._lock:
            self._dx += mouse.lLastX
            self._dy += mouse.lLastY
