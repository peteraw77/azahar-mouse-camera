import tomllib
from pathlib import Path

import pytest

from mousecam.config import (
    AxisCalibration,
    Calibration,
    Config,
    ConfigError,
    PulseCalibration,
    load_config,
    parse_config,
    save_calibration,
)

SHIPPED_CONFIG = Path(__file__).parent.parent / "config.toml"


def test_empty_config_gives_defaults():
    assert parse_config({}) == Config()


def test_missing_file_gives_defaults(tmp_path):
    assert load_config(tmp_path / "nope.toml") == Config()


def test_partial_section_keeps_other_defaults():
    config = parse_config({"invert_y": True, "velocity": {"full_speed_x": 1500}})
    assert config.invert_y is True
    assert config.velocity.full_speed_x == 1500
    assert config.velocity.full_speed_y == Config().velocity.full_speed_y


def test_project_config_is_valid():
    parse_config(tomllib.loads(SHIPPED_CONFIG.read_text("utf-8")))


FULL_CALIBRATION = Calibration(
    yaw=AxisCalibration(deadzone=0.12, max_rate=120.5, curve=((0.25, 30.0), (1.0, 120.5))),
    pitch=AxisCalibration(deadzone=0.2, max_rate=45.0, curve=((1.0, 45.0),), range_deg=90.0),
    pulse=PulseCalibration(
        registered_ms=(50, 100),
        missed_ms=(16, 33),
        trains=((100.0, 100.0, 0.97),),
        angles=((33.3, 3.1), (100.0, 9.8)),
        coasts=False,
    ),
)

USER_CONFIG = """\
# my comment stays
mode = "velocity"

[hotkeys]
toggle = "F7"   # so does this one

[velocity]
full_speed_x = 1234.0
"""


def test_calibration_round_trips(tmp_path):
    path = tmp_path / "config.toml"
    save_calibration(path, FULL_CALIBRATION)
    assert load_config(path).calibration == FULL_CALIBRATION


def test_partial_calibration_round_trips(tmp_path):
    path = tmp_path / "config.toml"
    calibration = Calibration(yaw=AxisCalibration(deadzone=0.1))
    save_calibration(path, calibration)
    assert load_config(path).calibration == calibration


def test_saving_keeps_user_settings_and_comments(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(USER_CONFIG, "utf-8")
    save_calibration(path, FULL_CALIBRATION)
    text = path.read_text("utf-8")
    assert text.startswith(USER_CONFIG.rstrip())
    config = load_config(path)
    assert config.hotkeys.toggle == "F7"
    assert config.velocity.full_speed_x == 1234.0


def test_saving_twice_replaces_the_old_results(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(USER_CONFIG, "utf-8")
    save_calibration(path, FULL_CALIBRATION)
    newer = Calibration(yaw=AxisCalibration(deadzone=0.3))
    save_calibration(path, newer)
    text = path.read_text("utf-8")
    assert load_config(path).calibration == newer
    assert text.count("[calibration.yaw]") == 1
    assert text.count("Written by") == 1
    assert "120.5" not in text
    assert text.startswith(USER_CONFIG.rstrip())


def test_settings_after_the_calibration_block_survive(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[calibration.yaw]\ndeadzone = 0.5\n\n[hotkeys]\ntoggle = \"F7\"\n", "utf-8")
    save_calibration(path, Calibration(yaw=AxisCalibration(deadzone=0.1)))
    config = load_config(path)
    assert config.calibration.yaw.deadzone == 0.1
    assert config.hotkeys.toggle == "F7"


def test_save_refuses_to_damage_a_hand_edited_file(tmp_path):
    """A hand-wrapped curve looks like table headers. The file must survive untouched."""
    original = '[calibration.yaw]\ncurve = [\n  [0.25, 30.0],\n]\n\n[hotkeys]\ntoggle = "F7"\n'
    path = tmp_path / "config.toml"
    path.write_text(original, "utf-8")
    with pytest.raises(ConfigError):
        save_calibration(path, Calibration(yaw=AxisCalibration(deadzone=0.1)))
    assert path.read_text("utf-8") == original


@pytest.mark.parametrize(
    "calibration",
    [
        {"typo": {}},
        {"yaw": {"typo": 1}},
        {"yaw": {"deadzone": 1.5}},
        {"yaw": {"deadzone": "low"}},
        {"yaw": {"curve": [[0.5]]}},
        {"yaw": {"curve": [[0.5, "fast"]]}},
        {"pulse": {"coasts": 1}},
        {"pulse": {"trains": [[1, 2]]}},
        {"pulse": {"angles": [[1, 2, 3]]}},
        {"pulse": {"registered_ms": ["a"]}},
    ],
)
def test_bad_calibration_is_rejected(calibration):
    with pytest.raises(ConfigError):
        parse_config({"calibration": calibration})


@pytest.mark.parametrize(
    "data",
    [
        {"mode": "warp"},
        {"tick_hz": 5},
        {"tick_hz": True},
        {"invert_y": "yes"},
        {"velocity": {"full_speed_x": 0}},
        {"velocity": {"full_speed_y": "fast"}},
        {"velocity": {"smoothing_ms": -1}},
        {"velocity": {"min_deflection": 1.0}},
        {"velocity": 3},
        {"hotkeys": {"toggle": 8}},
        {"typo_setting": 1},
        {"velocity": {"typo_setting": 1}},
    ],
)
def test_bad_values_are_rejected(data):
    with pytest.raises(ConfigError):
        parse_config(data)


@pytest.mark.parametrize(
    "budget",
    [
        {"sensitivity_x": 0},
        {"sensitivity_y": -1},
        {"ramp_ms": "slow"},
        {"fade_ms": True},
        {"frame_ms": 0},
        {"typo_setting": 1},
    ],
)
def test_bad_budget_settings_are_rejected(budget):
    with pytest.raises(ConfigError):
        parse_config({"budget": budget})


def test_budget_settings_are_read():
    assert parse_config({"budget": {"sensitivity_x": 0.2}}).budget.sensitivity_x == 0.2


def test_bad_toml_is_reported(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("mode = ", "utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
