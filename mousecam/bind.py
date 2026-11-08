"""Bind helper: moves the virtual right stick on cue so Azahar can bind it.

Azahar's "Set Analog Stick" button listens for 5 seconds after you click OK. It
takes the first axis to pass 50% deflection as X and the next one as Y, so the
sequence has to be X then Y, and has to start after OK is clicked. Otherwise the
axes get bound the wrong way round.
"""

from __future__ import annotations

import msvcrt
import time
import winsound

from mousecam.pad import Pad

STEP_S = 1 / 120
BEEPS = 2
BEEP_MS = 150

# Short enough that both axes pass 50% within Azahar's 5 s window, counting from
# a click on the first beep.
BIND_RAMP_UP_S = 0.6
BIND_HOLD_S = 0.2
BIND_RAMP_DOWN_S = 0.4
BIND_AXIS_GAP_S = 0.2

# Longer hold for the single directions, so the camera visibly turns in-game.
TEST_HOLD_S = 1.5

DIRECTIONS = {
    "r": ("right", 1.0, 0.0),
    "l": ("left", -1.0, 0.0),
    "u": ("up", 0.0, 1.0),
    "d": ("down", 0.0, -1.0),
}

HELP = """
Keep this window open: the virtual pad only exists while it runs.

  a        Bind sequence for Azahar's "Set Analog Stick" (X, then Y)
  r l u d  Move the stick right / left / up / down once (to test in-game)
  q        Quit
"""


def sweep_value(t: float, ramp_up: float, hold: float, ramp_down: float) -> float:
    """Deflection (0..1) at time t of a ramp up, hold, ramp down profile."""
    if t <= 0.0:
        return 0.0
    if t < ramp_up:
        return t / ramp_up
    if t < ramp_up + hold:
        return 1.0
    return max(0.0, 1.0 - (t - ramp_up - hold) / ramp_down)


def sweep(pad: Pad, x: float, y: float, ramp_up: float, hold: float, ramp_down: float) -> None:
    """Move the stick towards (x, y) and back to centre."""
    total = ramp_up + hold + ramp_down
    start = time.perf_counter()
    while (t := time.perf_counter() - start) < total:
        value = sweep_value(t, ramp_up, hold, ramp_down)
        pad.set_right_stick(x * value, y * value)
        time.sleep(STEP_S)
    pad.centre()


def countdown(prep_s: float) -> None:
    """Give time to switch to Azahar, then beep. The sweep follows the last beep."""
    time.sleep(prep_s)
    for _ in range(BEEPS):
        winsound.Beep(880, BEEP_MS)
        time.sleep(1.0 - BEEP_MS / 1000)


def bind_sequence(pad: Pad, prep_s: float) -> None:
    print(f'  Switch to Azahar and click "Set Analog Stick". You have {prep_s:g} s.')
    print("  Click OK on the first beep. Do not click it after the second beep.")
    countdown(prep_s)
    print("  Moving X...")
    sweep(pad, 1.0, 0.0, BIND_RAMP_UP_S, BIND_HOLD_S, BIND_RAMP_DOWN_S)
    time.sleep(BIND_AXIS_GAP_S)
    print("  Moving Y...")
    sweep(pad, 0.0, 1.0, BIND_RAMP_UP_S, BIND_HOLD_S, BIND_RAMP_DOWN_S)
    print("  Done.")


def direction_test(pad: Pad, key: str, prep_s: float) -> None:
    name, x, y = DIRECTIONS[key]
    print(f"  Moving {name} after {prep_s:g} s and two beeps...")
    countdown(prep_s)
    sweep(pad, x, y, BIND_RAMP_UP_S, TEST_HOLD_S, BIND_RAMP_DOWN_S)
    print("  Done.")


def drain_keys() -> None:
    """Drop keys pressed during a sweep, so they don't queue up another one."""
    while msvcrt.kbhit():
        msvcrt.getwch()


def run_bind(prep_s: float) -> None:
    pad = Pad()
    try:
        print("Virtual Xbox 360 pad created.")
        print(HELP)
        while True:
            key = msvcrt.getwch().lower()
            if key in ("q", "\x03"):  # getwch returns Ctrl+C as a character
                return
            if key == "a":
                bind_sequence(pad, prep_s)
            elif key in DIRECTIONS:
                direction_test(pad, key, prep_s)
            else:
                continue
            drain_keys()
            print("Ready. Press a, r, l, u, d or q.")
    except KeyboardInterrupt:
        pass
    finally:
        pad.close()
