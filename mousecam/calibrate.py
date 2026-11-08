"""Interactive calibration: moves the stick while Peter watches the game and marks
what he sees with global hotkeys. The results go into config.toml.

The measuring code only talks to a "rig" (stick, keys, clock, messages), so the
tests can run all of it against a simulated camera and a simulated Peter.
"""

from __future__ import annotations

import time
import winsound
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterable

from mousecam.config import AxisCalibration, Calibration, Config, save_calibration
from mousecam.hotkeys import Hotkeys
from mousecam.pad import Pad
from mousecam.win32 import winmm

MARK = "mark"
DONE = "done"
QUIT = "quit"
MARK_KEY = "F9"
DONE_KEY = "F7"  # not F10: that's the Windows menu key, and its release reaches Azahar

WAIT_POLL_S = 0.005
LAP_POLL_S = 0.001  # also how precisely pulse trains switch
REACTION_S = 0.3  # time from seeing something to pressing the key

COARSE_STEP = 0.04
COARSE_HOLD_S = 0.4
FINE_STEP = 0.01
FINE_HOLD_S = 0.8
FINE_MARGIN = 0.1

FULL_RATE_LAPS = 3
CURVE_LEVELS = (0.25, 0.4, 0.6, 0.8)
LAP_TIMEOUT_S = 180.0
ASYMMETRY_WARNING = 0.05

COAST_TEST_HOLD_S = 2.0
PULSE_LENGTHS_MS = (16, 33, 50, 100)
PULSES_PER_LENGTH = 5
PULSE_GAP_S = 1.0
# Whole numbers of 30 fps frames. Anything else beats against the frame rate: a 50 ms
# pulse catches one frame or two depending on phase, which looks like acceleration.
PULSE_TRAINS_MS = ((100.0, 100.0), (66.7, 66.7), (33.3, 33.3))

# Degrees per pulse: the camera turns at one fixed speed, so budget mode has to spend
# its budget in pulses. The gap isn't a whole number of frames, so successive pulses
# land at different points in a frame and a lap averages over all of them.
ANGLE_PULSES_MS = (200.0, 133.3, 100.0, 66.7, 33.3)
ANGLE_GAP_MS = 257.0

# Pitch has limits, so no 360 degree landmark: time the sweep between the limits.
# The true angle can't be seen, so the sweep counts as this many "degrees". Pitch
# sensitivity is tuned by feel, and clamping only needs the same units throughout.
NOMINAL_PITCH_RANGE_DEG = 90.0
PITCH_LEVELS = (1.0, 0.6, 0.4)

FIXED_SPEED_TOLERANCE = 0.1
LINEAR_TOLERANCE = 0.15
SPIN_UP_RATIO = 0.85
OVERSHOOT_RATIO = 1.15


class Aborted(Exception):
    """Peter pressed the quit hotkey."""


class ConsoleRig:
    """The real thing: virtual pad, global hotkeys, console and beeps."""

    def __init__(self, pad: Pad, hotkeys: Hotkeys) -> None:
        self._pad = pad
        self._hotkeys = hotkeys
        self.now = time.perf_counter
        self.sleep = time.sleep

    def stick(self, x: float, y: float) -> None:
        self._pad.set_right_stick(x, y)

    def poll(self) -> list[str]:
        return self._hotkeys.poll()

    def say(self, text: str, beeps: int = 0) -> None:
        print(text, flush=True)
        for _ in range(beeps):
            winsound.Beep(880, 120)
            time.sleep(0.08)


# --- Pure calculations ---


def rate_from_marks(marks: list[float], degrees_per_lap: float = 360.0) -> float | None:
    """Turn rate from the times a landmark came round. Needs at least one full lap.

    Peter's reaction time is about the same for each mark, so it cancels out.
    """
    if len(marks) < 2 or marks[-1] <= marks[0]:
        return None
    return degrees_per_lap * (len(marks) - 1) / (marks[-1] - marks[0])


def level_before(history: list[tuple[float, float]], when: float) -> float:
    """The stick level at a moment, from (start time, level) pairs in time order."""
    current = history[0][1]
    for start, level in history:
        if start > when:
            break
        current = level
    return current


def steps(start: float, stop: float, step: float) -> list[float]:
    """Evenly spaced levels from start up to and including stop, without float drift."""
    count = int(round((stop - start) / step))
    return [round(start + i * step, 3) for i in range(count + 1)]


def curve_levels(deadzone: float | None) -> list[float]:
    """Levels to measure: the standard ones above the deadzone, plus one just above it."""
    if deadzone is None:
        return list(CURVE_LEVELS)
    levels = [level for level in CURVE_LEVELS if level > deadzone]
    just_above = round(deadzone + 0.05, 3)
    if just_above < 1.0 and all(abs(just_above - level) > 0.02 for level in levels):
        levels.append(just_above)
    return sorted(levels)


def with_curve_point(
    curve: tuple[tuple[float, float], ...], level: float, rate: float
) -> tuple[tuple[float, float], ...]:
    """Add or replace one (deflection, rate) point, keeping the curve sorted."""
    points = {deflection: value for deflection, value in curve}
    points[level] = round(rate, 3)
    return tuple(sorted(points.items()))


def summarize(calibration: Calibration) -> list[str]:
    """Plain-language results, including what they mean for budget mode."""
    lines = ["", "=== Calibration results ==="]
    lines += _summarize_axis("Yaw", calibration.yaw, "degrees/s")
    lines += _summarize_axis("Pitch", calibration.pitch, f"of a nominal {NOMINAL_PITCH_RANGE_DEG:g} degree range/s")
    pulse = calibration.pulse
    if pulse.registered_ms or pulse.missed_ms:
        lines.append(f"Single pulses: moved {list(pulse.registered_ms)} ms, no movement {list(pulse.missed_ms)} ms")
    for on_ms, off_ms, ratio in pulse.trains:
        lines.append(
            f"Pulse train {on_ms:g} ms on / {off_ms:g} ms off: {ratio:.0%} of predicted rate ({_describe_ratio(ratio)})"
        )
    for on_ms, degrees in pulse.angles:
        lines.append(f"Pulse of {on_ms:g} ms: turns {degrees:.2f} degrees")
    if pulse.coasts is not None:
        lines.append("After release: " + ("keeps turning for a moment" if pulse.coasts else "stops straight away"))
    return lines


def _describe_ratio(ratio: float) -> str:
    if ratio == 0:
        return "no turning at this pulse length"
    if ratio < SPIN_UP_RATIO:
        return "turns less than the stick time predicts, so pulses this short lose rotation"
    if ratio > OVERSHOOT_RATIO:
        return "turns more than predicted, probably beating against the frame rate"
    return "turns as predicted"


def _summarize_axis(name: str, axis: AxisCalibration, unit: str) -> list[str]:
    lines = []
    if axis.deadzone is not None:
        lines.append(f"{name} deadzone: {axis.deadzone:.2f}")
    if axis.max_rate is not None:
        lines.append(f"{name} full-stick rate: {axis.max_rate:.1f} {unit}")
    moving = [(level, rate) for level, rate in axis.curve if rate > 0]
    if len(axis.curve) > 1:
        rows = ", ".join(f"{level:g} -> {rate:.1f}" for level, rate in axis.curve)
        lines.append(f"{name} curve: {rows}")
    if len(moving) > 1:
        lines.append(f"{name} response: {_describe_shape(moving, axis.deadzone)}")
    return lines


def _describe_shape(points: list[tuple[float, float]], deadzone: float | None) -> str:
    rates = [rate for _, rate in points]
    if (max(rates) - min(rates)) / max(rates) <= FIXED_SPEED_TOLERANCE:
        return "fixed speed: deflection doesn't change the turn rate, so budget mode must pulse the stick"
    top_level, top_rate = points[-1]
    floor = deadzone or 0.0
    for level, rate in points[:-1]:
        straight_line = top_rate * (level - floor) / (top_level - floor)
        if abs(rate - straight_line) > LINEAR_TOLERANCE * top_rate:
            return "curved: budget mode will interpolate between the measured points"
    return "roughly linear"


# --- Measuring steps ---


def _keys(rig) -> list[str]:
    events = rig.poll()
    if QUIT in events:
        raise Aborted
    return events


def wait_key(rig, timeout: float | None = None) -> str | None:
    """Wait for F9 or F10. Returns None if the timeout runs out first."""
    start = rig.now()
    while timeout is None or rig.now() - start < timeout:
        for event in _keys(rig):
            return event
        rig.sleep(WAIT_POLL_S)
    return None


def instruct(rig, text: str) -> None:
    """Give a new instruction and drop any earlier key presses, so that a stray
    double-tap can't answer it or start a lap timer early."""
    rig.say(text, beeps=1)
    _keys(rig)


def ask(rig, question: str) -> bool:
    instruct(rig, f"{question}  {MARK_KEY} = yes, {DONE_KEY} = no")
    return wait_key(rig) == MARK


def _pause(rig, seconds: float) -> None:
    """Sleep, while still responding to the quit hotkey."""
    end = rig.now() + seconds
    while rig.now() < end:
        _keys(rig)
        rig.sleep(min(WAIT_POLL_S, max(0.0, end - rig.now())))


def find_threshold(rig, direction: tuple[int, int], levels: Iterable[float], hold_s: float) -> float | None:
    """Step through stick levels until Peter marks that the camera has started moving."""
    dx, dy = direction
    history: list[tuple[float, float]] = []
    try:
        for level in levels:
            rig.stick(level * dx, level * dy)
            start = rig.now()
            history.append((start, level))
            while rig.now() - start < hold_s:
                events = _keys(rig)
                if MARK in events:
                    return level_before(history, rig.now() - REACTION_S)
                if DONE in events:
                    return None
                rig.sleep(WAIT_POLL_S)
        return None
    finally:
        rig.stick(0.0, 0.0)


def measure_deadzone(rig, direction: tuple[int, int], name: str) -> float | None:
    """A quick pass to find the area, then a slow pass for precision."""
    rig.say(f"Deadzone, {name}: the stick creeps up from zero. Press {MARK_KEY} the moment the camera starts moving.", beeps=1)
    _pause(rig, 1.0)
    coarse = find_threshold(rig, direction, steps(COARSE_STEP, 1.0, COARSE_STEP), COARSE_HOLD_S)
    if coarse is None:
        rig.say("  No movement marked.")
        return None
    rig.say(f"  Near {coarse:.2f}. Slower pass now: press {MARK_KEY} again the moment it starts moving.", beeps=1)
    _pause(rig, 1.5)
    low = max(FINE_STEP, round(coarse - FINE_MARGIN, 3))
    high = min(1.0, round(coarse + FINE_MARGIN, 3))
    fine = find_threshold(rig, direction, steps(low, high, FINE_STEP), FINE_HOLD_S)
    result = coarse if fine is None else fine
    rig.say(f"  Deadzone {name}: {result:.2f}")
    return result


def measure_laps(
    rig, stick_at: Callable[[float], tuple[float, float]], laps: int, what: str
) -> float | None:
    """Drive the stick while Peter marks each lap. Returns degrees/s, or None."""
    instruct(
        rig,
        f"{what}: press {MARK_KEY} each time your landmark lines up. "
        f"Press {DONE_KEY} after {laps} full lap{'s' if laps > 1 else ''}, "
        "or right away if the camera isn't turning.",
    )
    marks: list[float] = []
    current = None
    start = rig.now()
    try:
        while (elapsed := rig.now() - start) < LAP_TIMEOUT_S:
            wanted = stick_at(elapsed)
            if wanted != current:
                rig.stick(*wanted)
                current = wanted
            events = _keys(rig)
            if DONE in events:
                break
            if MARK in events:
                marks.append(rig.now())
                if len(marks) > 1:
                    rig.say(f"  lap {len(marks) - 1}: {marks[-1] - marks[-2]:.2f} s")
                else:
                    rig.say("  timing started")
            rig.sleep(LAP_POLL_S)
        else:
            rig.say("  Timed out, using the laps marked so far.")
    finally:
        rig.stick(0.0, 0.0)
    rate = rate_from_marks(marks)
    rig.say(f"  {rate:.1f} degrees/s" if rate is not None else "  No full lap marked.")
    _pause(rig, 1.0)
    return rate


def _constant(x: float, y: float = 0.0) -> Callable[[float], tuple[float, float]]:
    return lambda elapsed: (x, y)


def _pulse_train(on_ms: float, off_ms: float) -> Callable[[float], tuple[float, float]]:
    period = (on_ms + off_ms) / 1000
    on = on_ms / 1000
    return lambda elapsed: (1.0, 0.0) if elapsed % period < on else (0.0, 0.0)


def measure_sweep(rig, level: float) -> float | None:
    """Average seconds to tilt between the limits at a stick level, over two passes.

    The prompts name the stick direction, and never say which way the camera should
    go: that depends on the game's camera setting, and the first half of each pass
    deliberately moves away from the direction being timed.

    Returns None if no pass finished. A pass that did finish still counts if a later
    one is skipped.
    """
    durations: list[float] = []
    for number, direction, name, opposite in ((1, -1.0, "down", "up"), (2, 1.0, "up", "down")):
        instruct(
            rig,
            f"Pitch at stick {level:g}, pass {number} of 2. Setting up, stick {opposite}: "
            f"press {MARK_KEY} once the camera stops at the limit, or {DONE_KEY} to skip this pass.",
        )
        rig.stick(0.0, -direction)
        try:
            if wait_key(rig) != MARK:
                break
        finally:
            rig.stick(0.0, 0.0)
        _pause(rig, 0.7)
        instruct(
            rig,
            f"  Timing now, stick {name} at {level:g}: press {MARK_KEY} the moment the camera "
            f"stops at the limit, or {DONE_KEY} if it doesn't move.",
        )
        start = rig.now()
        rig.stick(0.0, level * direction)
        try:
            answer = wait_key(rig, timeout=LAP_TIMEOUT_S)
        finally:
            rig.stick(0.0, 0.0)
        if answer != MARK:
            break
        durations.append(max(0.05, rig.now() - start - REACTION_S))
        rig.say(f"  {durations[-1]:.2f} s")
        _pause(rig, 0.7)
    return sum(durations) / len(durations) if durations else None


# --- Stages. Each takes the calibration so far and returns an updated copy. ---


def stage_deadzone(rig, calibration: Calibration) -> Calibration:
    rig.say("\n--- Yaw deadzone ---")
    found = [
        value
        for value in (
            measure_deadzone(rig, (1, 0), "right"),
            measure_deadzone(rig, (-1, 0), "left"),
        )
        if value is not None
    ]
    if not found:
        return calibration
    # The larger one: budget mode needs a deflection that works in both directions.
    return replace(calibration, yaw=replace(calibration.yaw, deadzone=max(found)))


def stage_yaw(rig, calibration: Calibration) -> Calibration:
    rig.say("\n--- Full-stick yaw rate ---")
    right = measure_laps(rig, _constant(1.0), FULL_RATE_LAPS, "Full stick right")
    left = measure_laps(rig, _constant(-1.0), FULL_RATE_LAPS, "Full stick left")
    rates = [rate for rate in (right, left) if rate is not None]
    if right and left and abs(right - left) / max(right, left) > ASYMMETRY_WARNING:
        rig.say(f"  Note: right ({right:.1f}) and left ({left:.1f}) differ by more than {ASYMMETRY_WARNING:.0%}.")
    yaw = calibration.yaw
    if rates:
        rate = round(sum(rates) / len(rates), 3)
        yaw = replace(yaw, max_rate=rate, curve=with_curve_point(yaw.curve, 1.0, rate))

    rig.say("Watch the camera when the stick lets go, in a moment.", beeps=1)
    _pause(rig, 1.0)
    rig.stick(1.0, 0.0)
    _pause(rig, COAST_TEST_HOLD_S)
    rig.stick(0.0, 0.0)
    _pause(rig, 0.5)
    stops = ask(rig, "Did the camera stop straight away when the stick let go?")
    pulse = replace(calibration.pulse, coasts=not stops)
    return replace(calibration, yaw=yaw, pulse=pulse)


def stage_curve(rig, calibration: Calibration) -> Calibration:
    rig.say("\n--- Response curve ---")
    yaw = calibration.yaw
    for level in curve_levels(yaw.deadzone):
        rate = measure_laps(rig, _constant(level), 1, f"Stick at {level:g}")
        yaw = replace(yaw, curve=with_curve_point(yaw.curve, level, rate or 0.0))
    return replace(calibration, yaw=yaw)


def stage_pulse(rig, calibration: Calibration) -> Calibration:
    rig.say("\n--- Pulses ---")
    registered, missed = [], []
    for length_ms in PULSE_LENGTHS_MS:
        rig.say(f"Watch: {PULSES_PER_LENGTH} pulses of {length_ms} ms, about a second apart.", beeps=1)
        _pause(rig, 1.5)
        direction = 1.0
        for _ in range(PULSES_PER_LENGTH):
            rig.stick(direction, 0.0)
            rig.sleep(length_ms / 1000)
            rig.stick(0.0, 0.0)
            _pause(rig, PULSE_GAP_S)
            direction = -direction
        if ask(rig, f"Did most of the {length_ms} ms pulses move the camera?"):
            registered.append(length_ms)
        else:
            missed.append(length_ms)

    trains = []
    max_rate = calibration.yaw.max_rate
    if max_rate is None:
        rig.say("Skipping pulse trains: they need the full-stick rate from the yaw stage.")
    else:
        for on_ms, off_ms in PULSE_TRAINS_MS:
            rate = measure_laps(rig, _pulse_train(on_ms, off_ms), 1, f"Pulse train {on_ms} ms on, {off_ms} ms off")
            predicted = max_rate * on_ms / (on_ms + off_ms)
            trains.append((on_ms, off_ms, round((rate or 0.0) / predicted, 3)))
    pulse = replace(
        calibration.pulse,
        registered_ms=tuple(registered),
        missed_ms=tuple(missed),
        trains=tuple(trains) or calibration.pulse.trains,
    )
    return replace(calibration, pulse=pulse)


def stage_pitch(rig, calibration: Calibration) -> Calibration:
    rig.say("\n--- Pitch ---")
    if not ask(rig, "Can the camera tilt up and down in this game?"):
        return calibration
    found = [
        value
        for value in (
            measure_deadzone(rig, (0, 1), "stick up"),
            measure_deadzone(rig, (0, -1), "stick down"),
        )
        if value is not None
    ]
    pitch = replace(calibration.pitch, range_deg=NOMINAL_PITCH_RANGE_DEG, curve=())
    if found:
        pitch = replace(pitch, deadzone=max(found))
    for level in PITCH_LEVELS:
        if pitch.deadzone is not None and level <= pitch.deadzone:
            continue
        seconds = measure_sweep(rig, level)
        if seconds is None:
            # Not measured isn't the same as not moving, so no point on the curve.
            rig.say(f"  Nothing measured at {level:g}. Rerun with --only pitch to fill it in.")
            continue
        rate = NOMINAL_PITCH_RANGE_DEG / seconds
        pitch = replace(pitch, curve=with_curve_point(pitch.curve, level, rate))
        if level == 1.0:
            pitch = replace(pitch, max_rate=round(rate, 3))
    return replace(calibration, pitch=pitch)


def stage_angle(rig, calibration: Calibration) -> Calibration:
    rig.say("\n--- Degrees per pulse ---")
    angles = []
    for on_ms in ANGLE_PULSES_MS:
        rate = measure_laps(rig, _pulse_train(on_ms, ANGLE_GAP_MS), 1, f"Repeating {on_ms:g} ms pulses")
        if rate is None:
            # No lap in time means a very small turn, not none, so don't record a zero.
            rig.say(f"  No result for {on_ms:g} ms: no full lap was marked.")
            continue
        degrees = rate * (on_ms + ANGLE_GAP_MS) / 1000
        rig.say(f"  {degrees:.2f} degrees per pulse")
        angles.append((on_ms, round(degrees, 3)))
    return replace(calibration, pulse=replace(calibration.pulse, angles=tuple(angles)))


STAGES = {
    "deadzone": stage_deadzone,
    "yaw": stage_yaw,
    "curve": stage_curve,
    "pulse": stage_pulse,
    "angle": stage_angle,
    "pitch": stage_pitch,
}


def run_stages(
    rig, calibration: Calibration, names: Iterable[str], save: Callable[[Calibration], None]
) -> tuple[Calibration, bool]:
    """Run stages, saving after each one so an abort keeps finished stages.

    Returns the calibration and whether every stage finished.
    """
    try:
        for name in names:
            calibration = STAGES[name](rig, calibration)
            save(calibration)
        return calibration, True
    except Aborted:
        rig.stick(0.0, 0.0)
        rig.say("\nStopped early. Stages that finished are saved; the one in progress isn't.")
        return calibration, False


INTRO = """\
MH4U camera calibration. Takes about 10 minutes.

Before starting:
- Load a game with Azahar in New 3DS mode, somewhere you can stand still and look around.
- Pick a landmark: something distinctive that passes your character as the camera turns.
- Keep this window visible on your other monitor, and keep Azahar focused.
  The keys work from inside the game, and a beep means a new instruction.

Keys:  {mark} = mark / yes    {done} = done / no    {quit} = stop early
"""


def run_calibration(config: Config, config_path: Path, names: list[str]) -> None:
    winmm.timeBeginPeriod(1)
    try:
        print("Starting...")
        pad = Pad()
        try:
            bindings = {MARK: MARK_KEY, DONE: DONE_KEY, QUIT: config.hotkeys.quit}
            with Hotkeys(bindings) as hotkeys:
                rig = ConsoleRig(pad, hotkeys)
                print(INTRO.format(mark=MARK_KEY, done=DONE_KEY, quit=config.hotkeys.quit))
                print(f"Stages: {', '.join(names)}")
                rig.say(f"Press {MARK_KEY} to begin.", beeps=1)
                try:
                    if wait_key(rig) != MARK:
                        print("Cancelled.")
                        return
                except Aborted:
                    print("Cancelled.")
                    return
                calibration, _ = run_stages(
                    rig,
                    config.calibration,
                    names,
                    lambda latest: save_calibration(config_path, latest),
                )
                for line in summarize(calibration):
                    print(line)
                print(f"\nSaved to {config_path}")
        finally:
            pad.close()
    finally:
        winmm.timeEndPeriod(1)
