"""Hide and lock the cursor while the mouse camera is on.

A program can only hide the cursor while it's over one of its own windows, and
ClipCursor alone would let clicks through to whatever is under the pointer. So
the cursor is locked on top of a tiny, nearly invisible window of ours. That window
hides the cursor and catches clicks, so they never reach Azahar's touchscreen, and
it never takes focus, so the keyboard keeps going to Azahar.
"""

from __future__ import annotations

from ctypes import POINTER, byref, wintypes

from mousecam.win32 import WindowThread, last_error, user32

WM_SETCURSOR = 0x0020
WM_MOUSEACTIVATE = 0x0021
MA_NOACTIVATE = 3

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080  # stays out of the taskbar and Alt+Tab
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

LWA_ALPHA = 0x00000002
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SW_HIDE = 0

# Alpha 0 would let clicks fall through to the window below.
WINDOW_ALPHA = 1
WINDOW_SIZE = 32

user32.ClipCursor.argtypes = [POINTER(wintypes.RECT)]
user32.ClipCursor.restype = wintypes.BOOL
user32.GetCursorPos.argtypes = [POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.SetCursorPos.argtypes = [wintypes.INT, wintypes.INT]
user32.SetCursorPos.restype = wintypes.BOOL
user32.SetCursor.argtypes = [wintypes.HANDLE]
user32.SetCursor.restype = wintypes.HANDLE
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, wintypes.INT, wintypes.INT, wintypes.INT, wintypes.INT, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.ShowWindowAsync.argtypes = [wintypes.HWND, wintypes.INT]
user32.ShowWindowAsync.restype = wintypes.BOOL
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL


class CursorLock(WindowThread):
    def __init__(self) -> None:
        super().__init__(
            ex_style=WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE,
            style=WS_POPUP,
        )
        self._clip: wintypes.RECT | None = None

    def lock(self) -> None:
        """Hide the cursor and pin it where it is now."""
        point = wintypes.POINT()
        if not user32.GetCursorPos(byref(point)):
            raise last_error("GetCursorPos")
        half = WINDOW_SIZE // 2
        user32.SetWindowPos(
            self.hwnd, HWND_TOPMOST, point.x - half, point.y - half, WINDOW_SIZE, WINDOW_SIZE,
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        # Windows only asks for a new cursor on a mouse event, so trigger one.
        user32.SetCursorPos(point.x, point.y)
        self._clip = wintypes.RECT(point.x, point.y, point.x + 1, point.y + 1)
        self.refresh()

    def refresh(self) -> None:
        """Reapply the lock, because Windows drops it when focus changes."""
        if self._clip is not None:
            user32.ClipCursor(byref(self._clip))

    def release(self) -> None:
        """Free the cursor. Safe to call at any time, any number of times."""
        self._clip = None
        user32.ClipCursor(None)
        if self.hwnd:
            # Async: this also runs at exit, and must never wait on another thread.
            user32.ShowWindowAsync(self.hwnd, SW_HIDE)

    def stop(self) -> None:
        self.release()
        super().stop()

    def on_create(self) -> None:
        if not user32.SetLayeredWindowAttributes(self.hwnd, 0, WINDOW_ALPHA, LWA_ALPHA):
            raise last_error("SetLayeredWindowAttributes")

    def on_message(self, msg: int, wparam: int, lparam: int) -> int | None:
        if msg == WM_SETCURSOR:
            user32.SetCursor(None)
            return 1
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        return None
