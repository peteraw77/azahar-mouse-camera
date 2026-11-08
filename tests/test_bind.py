import pytest

from mousecam.bind import (
    BEEPS,
    BIND_AXIS_GAP_S,
    BIND_HOLD_S,
    BIND_RAMP_DOWN_S,
    BIND_RAMP_UP_S,
    sweep_value,
)


@pytest.mark.parametrize(
    ("t", "expected"),
    [(-1.0, 0.0), (0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (1.5, 1.0), (2.5, 0.5), (3.0, 0.0), (9.0, 0.0)],
)
def test_sweep_value_profile(t, expected):
    assert sweep_value(t, ramp_up=1.0, hold=1.0, ramp_down=1.0) == pytest.approx(expected)


def test_bind_sequence_fits_azahar_listen_window():
    """Y has to pass 50% within 5 s of OK being clicked on the first beep."""
    x_sweep = BIND_RAMP_UP_S + BIND_HOLD_S + BIND_RAMP_DOWN_S
    y_passes_half = BEEPS * 1.0 + x_sweep + BIND_AXIS_GAP_S + BIND_RAMP_UP_S / 2
    assert y_passes_half < 5.0
