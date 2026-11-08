"""Virtual Xbox 360 pad. Only the right stick is ever used."""

from __future__ import annotations

import time

AXIS_MAX = 32767

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

    def close(self) -> None:
        self.centre()
        del self._pad
