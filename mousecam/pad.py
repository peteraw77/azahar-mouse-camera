"""Virtual Xbox 360 pad: the right stick for the camera, plus buttons for mouse clicks."""

from __future__ import annotations

import time

AXIS_MAX = 32767
TRIGGER_MAX = 255

# Names usable in config.toml, and the vgamepad constant behind each one.
BUTTONS = {
    "a": "XUSB_GAMEPAD_A",
    "b": "XUSB_GAMEPAD_B",
    "x": "XUSB_GAMEPAD_X",
    "y": "XUSB_GAMEPAD_Y",
    "lb": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "rb": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "back": "XUSB_GAMEPAD_BACK",
    "start": "XUSB_GAMEPAD_START",
    "ls": "XUSB_GAMEPAD_LEFT_THUMB",
    "rs": "XUSB_GAMEPAD_RIGHT_THUMB",
}
TRIGGERS = ("lt", "rt")
BUTTON_NAMES = (*BUTTONS, *TRIGGERS)

# Settling a new pad. A report only gets through if the device has finished
# starting up and the report differs from the last one, so a plain centre() at
# startup is lost. Until one gets through, readers see a junk stick value (measured
# at about -10% X), which would slowly turn the camera. So alternate between centre
# and a nudge too small for the game to see, then finish on centre.
SETTLE_REPORTS = 30
SETTLE_STEP_S = 0.05
SETTLE_NUDGE = 1


class PadError(RuntimeError):
    """The virtual pad could not be created."""


def to_axis(value: float) -> int:
    """Convert a -1..1 deflection to an int16 axis value.

    Clamping matters: the XInput report stores axes as C shorts, and an
    out-of-range value wraps silently, turning full right into full left.
    """
    return round(max(-1.0, min(1.0, value)) * AXIS_MAX)


class Pad:
    """A virtual pad that exists until close() or process exit."""

    def __init__(self) -> None:
        try:
            # vgamepad connects to the ViGEmBus driver at import time.
            import vgamepad

            self._pad = vgamepad.VX360Gamepad()
            self._button_flags = {name: getattr(vgamepad.XUSB_BUTTON, flag) for name, flag in BUTTONS.items()}
        except (ImportError, OSError, RuntimeError) as exc:
            raise PadError(
                f"Could not create the virtual pad ({exc}). "
                "Check that the ViGEmBus driver is installed; see README.md."
            ) from exc
        self._settle()

    def _settle(self) -> None:
        for report in range(SETTLE_REPORTS):
            self._pad.right_joystick(SETTLE_NUDGE * (report % 2), 0)
            self._pad.update()
            time.sleep(SETTLE_STEP_S)
        self.centre()

    def set_right_stick(self, x: float, y: float) -> None:
        """Set the right stick. x: +1 is right. y: +1 is up (XInput convention)."""
        self._pad.right_joystick(to_axis(x), to_axis(y))
        self._pad.update()

    def centre(self) -> None:
        self.set_right_stick(0.0, 0.0)

    def set_button(self, name: str, pressed: bool) -> None:
        """Press or release a button or trigger, by a name from BUTTON_NAMES."""
        value = TRIGGER_MAX if pressed else 0
        if name == "lt":
            self._pad.left_trigger(value)
        elif name == "rt":
            self._pad.right_trigger(value)
        elif pressed:
            self._pad.press_button(self._button_flags[name])
        else:
            self._pad.release_button(self._button_flags[name])
        self._pad.update()

    def close(self) -> None:
        """Release everything, so nothing can stay stuck on as the pad goes away."""
        self._pad.reset()
        self._pad.update()
        del self._pad
