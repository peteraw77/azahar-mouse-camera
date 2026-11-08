import time
from pathlib import Path

import pytest

from mousecam.app import QUIT, TOGGLE, _loop, make_button_mapper, make_mapper
from mousecam.config import AxisCalibration, BudgetConfig, Calibration, Config, ConfigError, load_config
from mousecam.mapper import BudgetMapper, VelocityMapper

MEASURED = Calibration(
    yaw=AxisCalibration(max_rate=170.0),
    pitch=AxisCalibration(max_rate=39.0, range_deg=90.0),
)


def test_velocity_mode_needs_no_calibration():
    assert isinstance(make_mapper(Config(mode="velocity")), VelocityMapper)


def test_budget_mode_uses_the_calibration():
    assert isinstance(make_mapper(Config(mode="budget", calibration=MEASURED)), BudgetMapper)


@pytest.mark.parametrize(
    ("calibration", "stage"),
    [
        (Calibration(), "--only yaw"),
        (Calibration(yaw=AxisCalibration(max_rate=170.0)), "--only pitch"),
    ],
)
def test_budget_mode_without_calibration_says_what_to_run(calibration, stage):
    with pytest.raises(ConfigError, match=stage):
        make_mapper(Config(mode="budget", calibration=calibration))


def test_queue_is_limited_by_time_on_both_axes():
    budget = BudgetConfig(max_carry_ms=200.0)
    mapper = make_mapper(Config(mode="budget", budget=budget, calibration=MEASURED))
    mapper.update(10_000_000, -10_000_000, 0.0)
    assert mapper.pending == pytest.approx((170.0 * 0.2, 39.0 * 0.2))


def test_pitch_queue_is_never_more_than_the_range():
    budget = BudgetConfig(max_carry_ms=60_000.0)
    mapper = make_mapper(Config(mode="budget", budget=budget, calibration=MEASURED))
    mapper.update(0, -10_000_000, 0.0)
    assert mapper.pending[1] == 90.0


class FakeHotkeys:
    def __init__(self, script):
        self.start = time.perf_counter()
        self.script = script

    def poll(self):
        now = time.perf_counter() - self.start
        due = [action for when, action in self.script if when <= now]
        self.script = [(when, action) for when, action in self.script if when > now]
        return due


class FakeMouse:
    def __init__(self):
        self.moved = False

    def take(self):
        return 0, 0


class FlickOnce(FakeMouse):
    def __init__(self, hotkeys):
        super().__init__()
        self.hotkeys = hotkeys

    def take(self):
        if not self.moved and time.perf_counter() - self.hotkeys.start > 0.05:
            self.moved = True
            return 1000, -100
        return 0, 0


class Recorder:
    """Stands in for the pad and the cursor lock."""

    def __init__(self, clicks=(), physically_down=()):
        self.sticks = []
        self.button_changes = []
        self.clicks = list(clicks)  # (seconds from start, mouse button, pressed)
        self.physically_down = set(physically_down)
        self.start = time.perf_counter()

    def set_right_stick(self, x, y):
        self.sticks.append((x, y))

    def centre(self):
        self.sticks.append((0.0, 0.0))

    def set_button(self, name, pressed):
        self.button_changes.append((name, pressed))

    def take_button_events(self):
        now = time.perf_counter() - self.start
        due = [(button, pressed) for when, button, pressed in self.clicks if when <= now]
        self.clicks = [click for click in self.clicks if click[0] > now]
        return due

    def is_down(self, button):
        return button in self.physically_down

    def lock(self):
        pass

    def release(self):
        pass

    def refresh(self):
        pass


def run_loop(script, clicks=(), physically_down=()):
    config = Config()
    hotkeys = FakeHotkeys(script)
    recorder = Recorder(clicks, physically_down)
    _loop(config, make_mapper(config), recorder, FakeMouse(), hotkeys, recorder, make_button_mapper(config))
    return recorder


def test_clicks_press_pad_buttons_while_on():
    recorder = run_loop(
        [(0.0, TOGGLE), (0.4, QUIT)],
        clicks=[(0.05, "left", True), (0.15, "left", False)],
        physically_down={"left"},
    )
    assert recorder.button_changes == [("a", True), ("a", False)]


def test_clicks_while_off_do_nothing():
    recorder = run_loop(
        [(0.2, QUIT)],
        clicks=[(0.05, "left", True), (0.1, "left", False)],
    )
    assert recorder.button_changes == []


def test_turning_off_releases_a_held_button():
    recorder = run_loop(
        [(0.0, TOGGLE), (0.15, TOGGLE), (0.25, QUIT)],
        clicks=[(0.05, "right", True)],
        physically_down={"right"},
    )
    assert recorder.button_changes == [("b", True), ("b", False)]


def test_a_button_is_released_if_its_release_message_never_arrives():
    """Focus changing mid-click can send the release to another window."""
    recorder = run_loop(
        [(0.0, TOGGLE), (0.4, QUIT)],
        clicks=[(0.02, "left", True)],
        physically_down=(),  # the physical button is already up
    )
    assert recorder.button_changes == [("a", True), ("a", False)]


def test_debug_reports_the_peak_queue(capsys):
    budget = BudgetConfig(sensitivity_x=0.05, sensitivity_y=0.05)
    config = Config(mode="budget", debug=True, budget=budget, calibration=MEASURED)
    hotkeys = FakeHotkeys([(0.0, TOGGLE), (0.2, TOGGLE), (0.25, QUIT)])
    recorder = Recorder()
    _loop(config, make_mapper(config), recorder, FlickOnce(hotkeys), hotkeys, recorder, make_button_mapper(config))
    output = capsys.readouterr().out
    assert "peak pending while on: yaw=25.5 pitch=5.0" in output
    assert (1.0, 1.0) in recorder.sticks
    assert recorder.sticks[-1] == (0.0, 0.0)


def test_project_config_can_run_budget_mode():
    config = load_config(Path(__file__).parent.parent / "config.toml")
    mapper = make_mapper(Config(mode="budget", budget=config.budget, calibration=config.calibration))
    assert isinstance(mapper, BudgetMapper)
