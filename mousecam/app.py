"""The run command: mouse in, right stick out, until the quit hotkey."""

from __future__ import annotations

import atexit
import signal
import time

from mousecam.config import Config, ConfigError
from mousecam.cursor import CursorLock
from mousecam.hotkeys import Hotkeys
from mousecam.mapper import AxisSettings, BudgetMapper, BudgetSettings, VelocityMapper, VelocitySettings
from mousecam.pad import Pad
from mousecam.raw_input import RawMouse
from mousecam.win32 import make_dpi_aware, winmm

TOGGLE = "toggle"
QUIT = "quit"
TIMER_RESOLUTION_MS = 1
SLOW_WORK_PERIOD_S = 0.1  # how often to reapply the cursor lock and print debug


def run_app(config: Config) -> None:
    mapper = make_mapper(config)
    make_dpi_aware()
    signal.signal(signal.SIGBREAK, _interrupt)  # closing the console window
    winmm.timeBeginPeriod(TIMER_RESOLUTION_MS)
    try:
        print("Starting...")
        pad = Pad()
        try:
            bindings = {TOGGLE: config.hotkeys.toggle, QUIT: config.hotkeys.quit}
            with RawMouse() as mouse, Hotkeys(bindings) as hotkeys, CursorLock() as cursor:
                # Leaving the `with` frees the cursor; this is a second line of defence.
                atexit.register(cursor.release)
                print(f"Mode: {config.mode}")
                print(f"{config.hotkeys.toggle} turns the mouse camera on and off.")
                print(f"{config.hotkeys.quit} quits.")
                print("Mouse camera: OFF")
                try:
                    _loop(config, mapper, pad, mouse, hotkeys, cursor)
                except KeyboardInterrupt:
                    pass
        finally:
            pad.close()
    finally:
        winmm.timeEndPeriod(TIMER_RESOLUTION_MS)
    print("Stopped. Cursor released and stick centred.")


def make_mapper(config: Config) -> BudgetMapper | VelocityMapper:
    if config.mode == "budget":
        return _make_budget_mapper(config)
    velocity = config.velocity
    return VelocityMapper(
        VelocitySettings(
            full_speed_x=velocity.full_speed_x,
            full_speed_y=velocity.full_speed_y,
            smoothing_s=velocity.smoothing_ms / 1000,
            min_deflection=velocity.min_deflection,
            invert_y=config.invert_y,
        )
    )


def _make_budget_mapper(config: Config) -> BudgetMapper:
    yaw = config.calibration.yaw
    pitch = config.calibration.pitch
    if yaw.max_rate is None:
        raise ConfigError("Budget mode needs the yaw rate. Run: python -m mousecam calibrate --only yaw")
    if pitch.max_rate is None or pitch.range_deg is None:
        raise ConfigError("Budget mode needs the pitch rate. Run: python -m mousecam calibrate --only pitch")
    budget = config.budget
    # Limit the queue by time, which is what you feel as floatiness. Mouse movement
    # easily outruns the camera's top speed, and the excess can't be turned off later.
    carry_s = budget.max_carry_ms / 1000
    return BudgetMapper(
        BudgetSettings(
            yaw=AxisSettings(budget.sensitivity_x, yaw.max_rate, yaw.max_rate * carry_s),
            # Also never more than the distance between the limits, which would only
            # hold the stick against a limit after the camera had got there.
            pitch=AxisSettings(budget.sensitivity_y, pitch.max_rate, min(pitch.max_rate * carry_s, pitch.range_deg)),
            ramp_s=budget.ramp_ms / 1000,
            fade_s=budget.fade_ms / 1000,
            frame_s=budget.frame_ms / 1000,
            invert_y=config.invert_y,
        )
    )


def _interrupt(signum, frame) -> None:
    raise KeyboardInterrupt


def _loop(config, mapper, pad, mouse, hotkeys, cursor) -> None:
    period = 1 / config.tick_hz
    active = False
    stick = (0.0, 0.0)
    peak_x = peak_y = peak_yaw = peak_pitch = 0.0
    last = time.perf_counter()
    next_tick = last + period
    next_slow_work = last

    while True:
        for action in hotkeys.poll():
            if action == QUIT:
                return
            active = not active
            mapper.reset()
            mouse.take()  # drop movement from while the camera was off
            stick = (0.0, 0.0)
            pad.centre()
            if active:
                cursor.lock()
            else:
                cursor.release()
            if config.debug and not active:
                print(f"\npeak stick while on: x={peak_x:.3f} y={peak_y:.3f}")
                print(f"peak pending while on: yaw={peak_yaw:.1f} pitch={peak_pitch:.1f}")
            peak_x = peak_y = peak_yaw = peak_pitch = 0.0
            print(f"Mouse camera: {'ON' if active else 'OFF'}")

        now = time.perf_counter()
        dt = now - last
        last = now
        dx, dy = mouse.take()

        if active:
            new_stick = mapper.update(dx, dy, dt)
            if new_stick != stick:
                stick = new_stick
                pad.set_right_stick(*stick)
                peak_x = max(peak_x, abs(stick[0]))
                peak_y = max(peak_y, abs(stick[1]))
            peak_yaw = max(peak_yaw, abs(mapper.pending[0]))
            peak_pitch = max(peak_pitch, abs(mapper.pending[1]))
            if now >= next_slow_work:
                next_slow_work = now + SLOW_WORK_PERIOD_S
                cursor.refresh()
                if config.debug:
                    yaw, pitch = mapper.pending
                    print(
                        f"\rstick x={stick[0]:+.3f} y={stick[1]:+.3f}  pending yaw={yaw:+8.2f} pitch={pitch:+7.2f}",
                        end="",
                        flush=True,
                    )

        next_tick += period
        remaining = next_tick - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)
        else:
            next_tick = time.perf_counter()  # fell behind: don't try to catch up
