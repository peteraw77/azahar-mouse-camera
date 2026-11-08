import pytest

from mousecam.hotkeys import HotkeyError, Hotkeys, parse_hotkey

CTRL = 0x0002
SHIFT = 0x0004
VK_F8 = 0x77


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("F8", (0, VK_F8)),
        ("f8", (0, VK_F8)),
        ("Ctrl+F8", (CTRL, VK_F8)),
        (" ctrl + shift + F8 ", (CTRL | SHIFT, VK_F8)),
        ("F1", (0, 0x70)),
        ("F24", (0, 0x87)),
        ("Ctrl+m", (CTRL, ord("M"))),
        ("7", (0, ord("7"))),
    ],
)
def test_parse_hotkey(text, expected):
    assert parse_hotkey(text) == expected


@pytest.mark.parametrize("text", ["", "Ctrl+", "Hyper+F8", "F25", "F0", "Banana", "Ctrl"])
def test_bad_hotkeys_are_rejected(text):
    with pytest.raises(HotkeyError):
        parse_hotkey(text)


def test_duplicate_hotkeys_are_rejected():
    with pytest.raises(HotkeyError):
        Hotkeys({"toggle": "F8", "quit": "f8"})
