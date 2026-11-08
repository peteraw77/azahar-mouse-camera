"""Pure mapping logic: mouse deltas + dt in, stick values out. No I/O.

BudgetMapper is the main mode. VelocityMapper is the baseline to compare it with.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

# Below this smoothed speed (as a fraction of full speed) the stick snaps to
# centre. Without it, exponential smoothing would never quite reach zero.
STOP_THRESHOLD = 0.01

# Below this ramp level the camera is treated as back at a standstill.
IDLE_LEVEL = 0.02


@dataclass(frozen=True)
class VelocitySettings:
    full_speed_x: float  # mouse counts/s that give full deflection
    full_speed_y: float
    smoothing_s: float  # time constant of the speed smoothing
    min_deflection: float  # smallest non-zero deflection (to clear a deadzone)
    invert_y: bool


class VelocityMapper:
    """Baseline mode: mouse speed sets stick deflection, like reWASD.

    Smoothing is needed because most ticks contain no counts at all. Windows 11
    combines raw input for background programs into about 125 reports/s (measured:
    totals are kept), so at a 500 Hz tick the speed is a spike every fourth tick.
    """

    def __init__(self, settings: VelocitySettings) -> None:
        self._settings = settings
        self.reset()

    def reset(self) -> None:
        self._x = 0.0
        self._y = 0.0

    @property
    def pending(self) -> tuple[float, float]:
        """This mode has no budget, so nothing is ever waiting to be spent."""
        return 0.0, 0.0

    def update(self, dx: float, dy: float, dt: float) -> tuple[float, float]:
        """Return stick (x, y) for mouse counts (dx, dy) gathered over dt seconds.

        Mouse dy is positive downward; stick y is positive upward.
        """
        s = self._settings
        if dt > 0.0:
            target_x = dx / dt / s.full_speed_x
            target_y = -dy / dt / s.full_speed_y
            if s.invert_y:
                target_y = -target_y
            alpha = 1.0 - math.exp(-dt / s.smoothing_s) if s.smoothing_s > 0.0 else 1.0
            # Limit after smoothing, not before: limiting each spike would cap the
            # average at the share of ticks that have counts. Limiting here still
            # stops a flick from holding the stick at full long after the mouse stops.
            self._x, self._y = _limit(
                self._x + alpha * (target_x - self._x),
                self._y + alpha * (target_y - self._y),
            )
        return self._output()

    def _output(self) -> tuple[float, float]:
        magnitude = math.hypot(self._x, self._y)
        if magnitude < STOP_THRESHOLD:
            return 0.0, 0.0
        floor = self._settings.min_deflection
        scale = (floor + (1.0 - floor) * magnitude) / magnitude
        return self._x * scale, self._y * scale


class ButtonMapper:
    """Turns mouse button events into pad button presses the game can see.

    The game reads input once a frame, so a very quick click could press and release
    between two reads and go unnoticed. So each press and each release lasts at least
    min_state_s. Changes that arrive sooner wait their turn, so a quick double-click
    stays two presses instead of merging into one.
    """

    def __init__(self, mapping: dict[str, str], min_state_s: float) -> None:
        """mapping goes from mouse button name to pad button name."""
        self._mapping = mapping
        self._min_state_s = min_state_s
        self._held: set[str] = set()  # mouse buttons
        self._down: set[str] = set()  # pad buttons, as last reported
        self._queues: dict[str, deque[bool]] = {pad: deque() for pad in mapping.values()}
        self._next_change_s: dict[str, float] = {pad: 0.0 for pad in mapping.values()}

    @property
    def held(self) -> set[str]:
        """The mapped mouse buttons currently held."""
        return set(self._held)

    def mouse_event(self, button: str, pressed: bool) -> None:
        pad = self._mapping.get(button)
        if pad is None:
            return
        if pressed:
            self._held.add(button)
        else:
            self._held.discard(button)
        # Several mouse buttons can share a pad button: it's down while any of them is.
        wanted = any(self._mapping[held] == pad for held in self._held)
        queue = self._queues[pad]
        latest = queue[-1] if queue else pad in self._down
        if wanted != latest:
            queue.append(wanted)

    def tick(self, now: float) -> list[tuple[str, bool]]:
        """Return the (pad button, pressed) changes due at this time."""
        changes = []
        for pad, queue in self._queues.items():
            if queue and now >= self._next_change_s[pad]:
                pressed = queue.popleft()
                self._next_change_s[pad] = now + self._min_state_s
                (self._down.add if pressed else self._down.discard)(pad)
                changes.append((pad, pressed))
        return changes

    def release_all(self) -> list[tuple[str, bool]]:
        """Forget everything at once, and return the releases to send."""
        changes = [(pad, False) for pad in sorted(self._down)]
        self._held.clear()
        self._down.clear()
        for pad, queue in self._queues.items():
            queue.clear()
            self._next_change_s[pad] = 0.0
        return changes


@dataclass(frozen=True)
class AxisSettings:
    degrees_per_count: float
    max_rate: float  # degrees/s at full speed
    max_pending: float  # budget beyond this is dropped, in degrees


@dataclass(frozen=True)
class BudgetSettings:
    yaw: AxisSettings
    pitch: AxisSettings
    ramp_s: float  # time for the camera to reach full speed from a standstill
    fade_s: float  # how quickly the ramp level fades once the stick is released
    frame_s: float  # how often the game reads the stick
    invert_y: bool


class BudgetMapper:
    """Main mode: moving the mouse a given distance turns the camera a set angle.

    Mouse movement adds to a pending angle on each axis, and the stick spends it. The
    camera has one fixed top speed, so stick position can't set the turn rate. Each
    axis instead sends timed full-stick pulses, using a model of the camera:

    - Stick held: the speed climbs steadily from the current level to full speed.
    - Stick released: the camera stops dead, but the level fades away gradually, so
      pressing again soon afterwards starts partway up the ramp.

    The model was fitted to measured pulses. It's open loop: nothing reads the real
    camera, so differences between the model and the game add up as small errors.
    """

    def __init__(self, settings: BudgetSettings) -> None:
        self._settings = settings
        self._yaw = _PulseAxis(settings.yaw, settings)
        self._pitch = _PulseAxis(settings.pitch, settings)

    def reset(self) -> None:
        self._yaw.reset()
        self._pitch.reset()

    @property
    def pending(self) -> tuple[float, float]:
        """Degrees still to turn on each axis."""
        return self._yaw.pending, self._pitch.pending

    def update(self, dx: float, dy: float, dt: float) -> tuple[float, float]:
        """Return stick (x, y) for mouse counts (dx, dy) gathered over dt seconds.

        Mouse dy is positive downward; stick y is positive upward.
        """
        counts_y = dy if self._settings.invert_y else -dy
        return (
            float(self._yaw.update(dx, dt)),
            float(self._pitch.update(counts_y, dt)),
        )


class _PulseAxis:
    """Works in whole game frames, both stick on and stick off.

    The game reads the stick once a frame, so holding it for exactly n frames is read
    n times, wherever that falls. Other lengths catch a varying number of frames, and
    a gap under a frame can go unseen. Either way, the error builds up at a steady pulse
    rhythm. An idle axis can still start at once: its ramp has faded, so the exact
    length of the gap no longer matters.
    """

    def __init__(self, axis: AxisSettings, settings: BudgetSettings) -> None:
        self._axis = axis
        self._ramp_s = settings.ramp_s
        self._fade_s = settings.fade_s
        self._frame_s = settings.frame_s
        self.reset()

    def reset(self) -> None:
        self.pending = 0.0
        self._level = 0.0  # camera speed as a fraction of full, or what remains of it
        self._direction = 0  # the stick for the current frame: -1, 0 or +1
        self._ramp_direction = 0  # the direction the level was built up in
        self._frame_left_s = 0.0
        self._idle = True

    def update(self, counts: float, dt: float) -> int:
        if dt > 0.0:
            self._advance(dt)
        limit = self._axis.max_pending
        self.pending = max(-limit, min(limit, self.pending + counts * self._axis.degrees_per_count))
        if self._idle:
            self._choose_frame()
        return self._direction

    def _advance(self, dt: float) -> None:
        """Account for the time just passed, one finished frame at a time."""
        if self._idle:
            return
        self._frame_left_s -= dt
        while not self._idle and self._frame_left_s <= 0.0:
            self._finish_frame()
            self._choose_frame()

    def _finish_frame(self) -> None:
        if self._direction == 0:
            self._level *= math.exp(-self._frame_s / self._fade_s)
        else:
            self.pending -= self._direction * self._frame_turn(self._level)
            self._level = self._next_level(self._level)

    def _choose_frame(self) -> None:
        """Hold the stick for the next frame only if the budget can pay for all of it.

        So it can't overshoot, and never needs a correction backwards. Whatever can't
        be paid for stays pending.
        """
        direction = 1 if self.pending > 0.0 else -1
        level = self._level if direction == self._ramp_direction else 0.0
        if self.pending != 0.0 and abs(self.pending) >= self._frame_turn(level):
            self._level = level
            self._ramp_direction = direction
            self._direction = direction
        else:
            self._direction = 0
            if self._level < IDLE_LEVEL:
                self._idle = True
                self._level = 0.0
                self._frame_left_s = 0.0
                return
        self._idle = False
        # Added, not set: keeping the remainder stops the frame clock drifting.
        self._frame_left_s += self._frame_s

    def _next_level(self, level: float) -> float:
        return min(1.0, level + self._frame_s / self._ramp_s)

    def _frame_turn(self, level: float) -> float:
        """Degrees turned by one frame of stick, starting from a ramp level."""
        return self._axis.max_rate * (level + self._next_level(level)) / 2 * self._frame_s


def _limit(x: float, y: float) -> tuple[float, float]:
    """Limit the vector's length to 1, keeping its direction."""
    magnitude = math.hypot(x, y)
    if magnitude <= 1.0:
        return x, y
    return x / magnitude, y / magnitude
