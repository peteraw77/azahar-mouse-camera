"""Global hotkeys, which work whichever program has focus."""

from __future__ import annotations

import queue
from ctypes import wintypes

from mousecam.win32 import HWND_MESSAGE, WindowThread, user32

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000  # holding the key down doesn't toggle over and over
MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
VK_F1 = 0x70

user32.RegisterHotKey.argtypes = [wintypes.HWND, wintypes.INT, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, wintypes.INT]
user32.UnregisterHotKey.restype = wintypes.BOOL


class HotkeyError(ValueError):
    """A hotkey is badly written or can't be registered."""


def parse_hotkey(text: str) -> tuple[int, int]:
    """Turn text like "Ctrl+F8" into (modifier flags, virtual key code)."""
    *modifier_names, key = [part.strip().lower() for part in text.split("+")]
    modifiers = 0
    for name in modifier_names:
        if name not in MODIFIERS:
            raise HotkeyError(f"Unknown modifier {name!r} in hotkey {text!r}")
        modifiers |= MODIFIERS[name]
    return modifiers, _key_code(key, text)


def _key_code(key: str, text: str) -> int:
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())  # virtual key codes for A-Z and 0-9 match ASCII
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        return VK_F1 + int(key[1:]) - 1
    raise HotkeyError(f"Unknown key {key!r} in hotkey {text!r}")


class Hotkeys(WindowThread):
    """Registers hotkeys. poll() returns the actions triggered since the last call."""

    def __init__(self, bindings: dict[str, str]) -> None:
        """bindings maps an action name to its hotkey text."""
        super().__init__(parent=HWND_MESSAGE)
        self._bindings = list(bindings.items())
        parsed = [parse_hotkey(text) for _, text in self._bindings]
        if len(set(parsed)) != len(parsed):
            raise HotkeyError("Two actions use the same hotkey")
        self._parsed = parsed
        self._registered: list[int] = []
        self._events: queue.SimpleQueue[str] = queue.SimpleQueue()

    def poll(self) -> list[str]:
        events = []
        while not self._events.empty():
            events.append(self._events.get())
        return events

    def on_create(self) -> None:
        for hotkey_id, (modifiers, key) in enumerate(self._parsed):
            if not user32.RegisterHotKey(self.hwnd, hotkey_id, modifiers | MOD_NOREPEAT, key):
                text = self._bindings[hotkey_id][1]
                raise HotkeyError(f"Can't register {text}. Another program may be using it.")
            self._registered.append(hotkey_id)

    def on_destroy(self) -> None:
        for hotkey_id in self._registered:
            user32.UnregisterHotKey(self.hwnd, hotkey_id)

    def on_message(self, msg: int, wparam: int, lparam: int) -> int | None:
        if msg == WM_HOTKEY:
            self._events.put(self._bindings[wparam][0])
            return 0
        return None
