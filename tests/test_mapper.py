import math

import pytest

from mousecam.mapper import VelocityMapper, VelocitySettings

DT = 1 / 500


def settings(**overrides):
    values = dict(
        full_speed_x=1000.0,
        full_speed_y=1000.0,
        smoothing_s=0.04,
        min_deflection=0.0,
        invert_y=False,
    )
    values.update(overrides)
    return VelocitySettings(**values)


def hold_speed(mapper, vx, vy, seconds=1.0, dt=DT):
    """Move the mouse at a constant speed (counts/s) and return the last output."""
    output = (0.0, 0.0)
    for _ in range(round(seconds / dt)):
        output = mapper.update(vx * dt, vy * dt, dt)
    return output


def hold_bursts(mapper, speed, seconds=1.0, reports_per_s=125, tick_hz=500):
    """Move at a steady speed, delivered the way Windows 11 delivers raw input to a
    background program: combined into 125 reports/s, so most ticks have no counts.

    Returns the stick x of every tick in the last half of the run.
    """
    ticks_per_report = tick_hz // reports_per_s
    counts_per_report = speed / reports_per_s
    dt = 1 / tick_hz
    ticks = round(seconds * tick_hz)
    outputs = []
    for tick in range(ticks):
        dx = counts_per_report if tick % ticks_per_report == 0 else 0
        x, _ = mapper.update(dx, 0, dt)
        if tick >= ticks // 2:
            outputs.append(x)
    return outputs


@pytest.mark.parametrize(
    ("speed", "expected"),
    [(300, 0.1), (1500, 0.5), (2400, 0.8)],
)
def test_bursty_reports_give_the_same_average_deflection(speed, expected):
    outputs = hold_bursts(VelocityMapper(settings(full_speed_x=3000)), speed)
    assert sum(outputs) / len(outputs) == pytest.approx(expected, abs=0.02)


def test_bursty_reports_can_reach_full_deflection():
    outputs = hold_bursts(VelocityMapper(settings(full_speed_x=300)), 3000)
    assert min(outputs) > 0.8
    assert max(outputs) <= 1.0


def test_stick_centres_soon_after_bursty_reports_stop():
    mapper = VelocityMapper(settings(full_speed_x=300))
    hold_bursts(mapper, 100_000)
    assert hold_speed(mapper, 0, 0, seconds=4.7 * 0.04) == (0.0, 0.0)


def test_no_input_gives_centred_stick():
    assert VelocityMapper(settings()).update(0, 0, DT) == (0.0, 0.0)


def test_steady_speed_gives_proportional_deflection():
    x, y = hold_speed(VelocityMapper(settings()), 500, 0)
    assert x == pytest.approx(0.5, abs=1e-3)
    assert y == 0.0


def test_axes_have_separate_full_speeds():
    x, y = hold_speed(VelocityMapper(settings(full_speed_x=1000, full_speed_y=2000)), 500, -500)
    assert x == pytest.approx(0.5, abs=1e-3)
    assert y == pytest.approx(0.25, abs=1e-3)


def test_mouse_up_is_stick_up_unless_inverted():
    assert hold_speed(VelocityMapper(settings()), 0, -500)[1] > 0
    assert hold_speed(VelocityMapper(settings(invert_y=True)), 0, -500)[1] < 0


def test_deflection_is_limited_and_keeps_direction():
    x, y = hold_speed(VelocityMapper(settings()), 30000, -40000)
    assert math.hypot(x, y) == pytest.approx(1.0, abs=1e-6)
    assert y / x == pytest.approx(4 / 3, abs=1e-6)


@pytest.mark.parametrize("min_deflection", [0.0, 0.3])
def test_stick_centres_soon_after_a_flick(min_deflection):
    mapper = VelocityMapper(settings(min_deflection=min_deflection))
    assert hold_speed(mapper, 1_000_000, 0, seconds=0.5)[0] == pytest.approx(1.0, abs=1e-3)
    # 0.01 of full speed is reached after ln(100) = 4.6 time constants.
    assert hold_speed(mapper, 0, 0, seconds=4.7 * 0.04) == (0.0, 0.0)


def test_result_does_not_depend_on_tick_rate():
    slow = hold_speed(VelocityMapper(settings()), 500, 0, dt=1 / 250)
    fast = hold_speed(VelocityMapper(settings()), 500, 0, dt=1 / 1000)
    assert slow[0] == pytest.approx(fast[0], abs=1e-6)


def test_min_deflection_lifts_small_movements():
    x, _ = hold_speed(VelocityMapper(settings(min_deflection=0.3)), 100, 0)
    assert x == pytest.approx(0.3 + 0.7 * 0.1, abs=1e-3)


def test_min_deflection_still_reaches_full():
    x, _ = hold_speed(VelocityMapper(settings(min_deflection=0.3)), 5000, 0)
    assert x == pytest.approx(1.0, abs=1e-6)


def test_no_smoothing_follows_input_immediately():
    assert VelocityMapper(settings(smoothing_s=0.0)).update(1, 0, DT)[0] == pytest.approx(0.5)


def test_reset_clears_speed():
    mapper = VelocityMapper(settings())
    hold_speed(mapper, 500, 0)
    mapper.reset()
    assert mapper.update(0, 0, DT) == (0.0, 0.0)


def test_zero_dt_is_safe():
    mapper = VelocityMapper(settings())
    assert mapper.update(5, 5, 0.0) == (0.0, 0.0)
