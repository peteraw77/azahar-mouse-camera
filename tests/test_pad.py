import pytest

from mousecam.pad import AXIS_MAX, to_axis


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, 0),
        (1.0, AXIS_MAX),
        (-1.0, -AXIS_MAX),
        (0.5, 16384),
        (1.5, AXIS_MAX),
        (-1.5, -AXIS_MAX),
    ],
)
def test_to_axis_scales_and_clamps(value, expected):
    assert to_axis(value) == expected
