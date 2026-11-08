"""Shared Windows API declarations, and a window that runs on its own thread."""

from __future__ import annotations

import ctypes
import threading
from ctypes import POINTER, byref, wintypes
from itertools import count

# Private DLL instances, so these argtypes can't clash with other ctypes users.
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
HWND_MESSAGE = wintypes.HWND(-3)
ERROR_ALREADY_EXISTS = 183
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = wintypes.HANDLE(-4)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
user32.RegisterClassW.argtypes = [POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.UnregisterClassW.restype = wintypes.BOOL
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None
user32.GetMessageW.argtypes = [POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.DispatchMessageW.argtypes = [POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT


class Win32Error(RuntimeError):
    """A Windows API call failed."""


def last_error(what: str) -> Win32Error:
    return Win32Error(f"{what} failed: {ctypes.WinError(ctypes.get_last_error()).strerror}")


def started_by_double_click() -> bool:
    """True if this program has its console to itself, so the window closes when it
    exits. Started from a terminal, the shell shares the console too."""
    kernel32.GetConsoleProcessList.argtypes = [POINTER(wintypes.DWORD), wintypes.DWORD]
    kernel32.GetConsoleProcessList.restype = wintypes.DWORD
    processes = (wintypes.DWORD * 4)()
    return kernel32.GetConsoleProcessList(processes, len(processes)) == 1


def make_dpi_aware() -> None:
    """Use real pixels. Otherwise, with display scaling on, Windows scales the
    coordinates we pass, and a 1x1 cursor lock can cover more than one pixel."""
    user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    # Failure only means the awareness was already set, which is fine.
    user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)


def claim_single_instance(name: str) -> bool:
    """Return False if another process holds this name. Held until this process exits."""
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise last_error("CreateMutex")
    return ctypes.get_last_error() != ERROR_ALREADY_EXISTS


class WindowThread(threading.Thread):
    """A window and its message loop on a dedicated thread.

    Subclasses override on_create, on_destroy and on_message. on_create runs on
    the new thread, and anything it raises comes back out of start(). Use with
    `with`, which starts the thread and stops it again on the way out.
    """

    _serial = count()

    def __init__(self, ex_style: int = 0, style: int = 0, parent: wintypes.HWND | None = None) -> None:
        super().__init__(name=type(self).__name__, daemon=True)
        self.hwnd: wintypes.HWND | None = None
        self._ex_style = ex_style
        self._style = style
        self._parent = parent
        self._ready = threading.Event()
        self._startup_error: Exception | None = None
        # Must outlive the window: Windows calls back into it.
        self._wndproc_ref = WNDPROC(self._wndproc)

    def on_create(self) -> None:
        pass

    def on_destroy(self) -> None:
        pass

    def on_message(self, msg: int, wparam: int, lparam: int) -> int | None:
        """Handle a message and return its result, or None for default handling."""
        return None

    def start(self) -> None:
        super().start()
        self._ready.wait()
        if self._startup_error is not None:
            self.join()
            raise self._startup_error

    def stop(self) -> None:
        if self.is_alive() and self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self.join(timeout=2.0)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()

    def run(self) -> None:
        instance = kernel32.GetModuleHandleW(None)
        class_name = f"MouseCam{self.name}{next(self._serial)}"
        window_class = WNDCLASSW(
            lpfnWndProc=self._wndproc_ref, hInstance=instance, lpszClassName=class_name
        )
        try:
            if not user32.RegisterClassW(byref(window_class)):
                raise last_error("RegisterClass")
            self.hwnd = user32.CreateWindowExW(
                self._ex_style, class_name, self.name, self._style,
                0, 0, 0, 0, self._parent, None, instance, None,
            )
            if not self.hwnd:
                raise last_error("CreateWindowEx")
            try:
                self.on_create()
            except Exception:
                user32.DestroyWindow(self.hwnd)
                raise
        except Exception as exc:
            self._startup_error = exc
            self._ready.set()
            user32.UnregisterClassW(class_name, instance)
            return

        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(byref(msg), None, 0, 0) > 0:
            user32.DispatchMessageW(byref(msg))
        user32.UnregisterClassW(class_name, instance)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DESTROY:
            self.on_destroy()
            user32.PostQuitMessage(0)
            return 0
        result = self.on_message(msg, wparam, lparam)
        if result is not None:
            return result
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
