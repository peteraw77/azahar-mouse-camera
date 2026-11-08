"""BudgetMapper against a simulated camera that reads the stick at 30 fps."""

import math
import random

import pytest

from mousecam.mapper import AxisSettings, BudgetMapper, BudgetSettings

YAW_RATE = 170.0
PITCH_RATE = 39.0
PITCH_RANGE = 90.0
RAMP_S = 0.164
FADE_S = 0.080
FRAME_S = 2 / 59.83  # the game's frame time: two 3DS screen refreshes
SENSITIVITY_X = 0.05
SENSITIVITY_Y = 0.015
THRESHOLD = 0.56  # the measured deadzone
TICK_S = 1 / 500

# The stick is only read once a frame, so a pulse can end up to a frame out. At full
# speed that's one frame's turn, which limits how accurate any single movement can be.
ONE_FRAME_AT_FULL_SPEED = YAW_RATE * FRAME_S


def settings(**overrides):
    values = dict(
        yaw=AxisSettings(SENSITIVITY_X, YAW_RATE, 720.0),
        pitch=AxisSettings(SENSITIVITY_Y, PITCH_RATE, PITCH_RANGE),
        ramp_s=RAMP_S,
        fade_s=FADE_S,
        frame_s=0.0334,
        invert_y=False,
    )
    values.update(overrides)
    return BudgetSettings(**values)


class SimAxis:
    """The fitted camera: the speed climbs while held, stops dead on release, and the
    level fades. It sees the stick only once a frame, like the game."""

    def __init__(self, rate, ramp_s=RAMP_S, fade_s=FADE_S, frame_s=FRAME_S):
        self.rate = rate
        self.ramp_s = ramp_s
        self.fade_s = fade_s
        self.frame_s = frame_s
        self.angle = 0.0
        self.level = 0.0
        self.direction = 0
        self.reversals = 0
        self.turn_signs = set()

    def frame(self, stick):
        if abs(stick) <= THRESHOLD:
            self.level *= math.exp(-self.frame_s / self.fade_s)
            return
        direction = 1 if stick > 0 else -1
        if direction != self.direction:
            if self.direction != 0:
                self.reversals += 1
            self.direction = direction
            self.level = 0.0
        new_level = min(1.0, self.level + self.frame_s / self.ramp_s)
        self.angle += direction * self.rate * (self.level + new_level) / 2 * self.frame_s
        self.level = new_level
        self.turn_signs.add(direction)


class Rig:
    def __init__(
        self, phase=0.0, tick_s=TICK_S, camera_ramp_s=RAMP_S, camera_frame_s=FRAME_S, jitter_s=0.0, seed=7, **overrides
    ):
        self.jitter_s = jitter_s
        self.random = random.Random(seed)
        self.seen_changes = []  # (time the game can see it, stick), for jitter
        self.seen = (0.0, 0.0)
        self.mapper = BudgetMapper(settings(**overrides))
        self.yaw = SimAxis(YAW_RATE, ramp_s=camera_ramp_s, frame_s=camera_frame_s)
        self.pitch = SimAxis(PITCH_RATE, ramp_s=camera_ramp_s, frame_s=camera_frame_s)
        self.tick_s = tick_s
        self.t = 0.0
        self.camera_frame_s = camera_frame_s
        self.next_frame = phase * camera_frame_s
        self.stick = (0.0, 0.0)
        self.stick_history = []

    def tick(self, dx=0.0, dy=0.0):
        self.t += self.tick_s
        while self.next_frame <= self.t:
            while self.seen_changes and self.seen_changes[0][0] <= self.next_frame:
                self.seen = self.seen_changes.pop(0)[1]
            self.yaw.frame(self.seen[0])
            self.pitch.frame(self.seen[1])
            self.next_frame += self.camera_frame_s
        stick = self.mapper.update(dx, dy, self.tick_s)
        if stick != self.stick:
            # Reaches the game a little late, by a varying amount.
            self.seen_changes.append((self.t + self.random.uniform(0.0, self.jitter_s), stick))
        self.stick = stick
        self.stick_history.append(self.stick)

    def move(self, counts_x=0, counts_y=0, seconds=0.2):
        """Move the mouse steadily, delivered in 125 reports/s like real raw input."""
        ticks_per_report = max(1, round((1 / 125) / self.tick_s))
        ticks = max(ticks_per_report, round(seconds / self.tick_s))
        reports = ticks // ticks_per_report
        for i in range(reports * ticks_per_report):
            if i % ticks_per_report == 0:
                self.tick(counts_x / reports, counts_y / reports)
            else:
                self.tick()

    def wait(self, seconds):
        for _ in range(round(seconds / self.tick_s)):
            self.tick()

    def settle(self):
        """Run until the stick has stayed centred for a while."""
        quiet = 0
        for _ in range(round(60 / self.tick_s)):
            self.tick()
            quiet = quiet + 1 if self.stick == (0.0, 0.0) else 0
            if quiet * self.tick_s > 0.5:
                return
        raise AssertionError("the stick never settled")


def counts_for(degrees):
    return degrees / SENSITIVITY_X


def error_stats(degrees, seconds, phases=48, **rig_options):
    """Degrees of error over all the ways the game's frames can line up with a movement:
    the mean (is it biased?), the median and the 90th percentile (how far off is it?).

    Not the single worst case: nothing can stop the odd stick change landing right on a
    frame boundary, which is why the rare worst case can be several frames out.
    """
    errors = []
    for i in range(phases):
        rig = Rig(phase=i / phases, seed=i, **rig_options)
        rig.move(counts_for(degrees), seconds=seconds)
        rig.settle()
        errors.append(rig.yaw.angle - degrees)
    sizes = sorted(abs(e) for e in errors)
    return sum(errors) / len(errors), sizes[len(sizes) // 2], sizes[int(len(sizes) * 0.9)]


# --- The main promise: a given mouse distance gives a given angle ---


@pytest.mark.parametrize(
    ("degrees", "seconds"),
    [(5, 0.1), (20, 0.1), (90, 0.2), (180, 0.3), (360, 0.3), (700, 0.2), (30, 1.0), (90, 2.0), (360, 3.0)],
)
def test_mouse_distance_gives_the_right_angle(degrees, seconds):
    mean, median, p90 = error_stats(degrees, seconds)
    assert abs(mean) < 0.6 * ONE_FRAME_AT_FULL_SPEED
    assert median < 0.5 * ONE_FRAME_AT_FULL_SPEED
    assert p90 < 1.5 * ONE_FRAME_AT_FULL_SPEED


def test_same_distance_gives_a_consistent_angle_however_fast():
    results = []
    for seconds in (0.1, 0.3, 1.0, 3.0):
        rig = Rig(phase=0.37)
        rig.move(counts_for(180), seconds=seconds)
        rig.settle()
        results.append(rig.yaw.angle)
    assert max(results) - min(results) < 2 * ONE_FRAME_AT_FULL_SPEED


def test_errors_do_not_build_up_over_many_movements():
    random.seed(1)
    rig = Rig()
    wanted = 0.0
    for _ in range(150):
        degrees = random.uniform(-90, 90)
        rig.move(counts_for(degrees), seconds=random.uniform(0.05, 0.6))
        wanted += degrees
        rig.wait(random.uniform(0.0, 0.4))
    rig.settle()
    # 150 movements. This allows less than a third of a degree of error each.
    assert abs(rig.yaw.angle - wanted) < 45.0


def test_slow_creeping_movement_is_not_lost():
    rig = Rig()
    rig.move(counts_for(30), seconds=10.0)  # 3 degrees/s: far below the smallest pulse rate
    rig.settle()
    assert rig.yaw.angle == pytest.approx(30, abs=ONE_FRAME_AT_FULL_SPEED)


def test_movements_too_small_for_a_pulse_are_kept_for_later():
    rig = Rig()
    tiny = counts_for(0.2)
    for _ in range(2):
        rig.move(tiny, seconds=0.05)
    rig.wait(0.5)
    assert rig.stick_history[-1] == (0.0, 0.0)
    assert rig.yaw.angle == 0.0
    assert rig.mapper.pending[0] == pytest.approx(0.4)
    for _ in range(50):
        rig.move(tiny, seconds=0.05)
        rig.wait(0.2)
    rig.settle()
    assert rig.yaw.angle == pytest.approx(52 * 0.2, abs=3.0)


# --- No drift ---


@pytest.mark.parametrize("degrees", [0.5, 3, 15, 90, 360])
def test_camera_stops_once_the_budget_is_spent(degrees):
    rig = Rig()
    rig.move(counts_for(degrees), seconds=0.2)
    rig.settle()
    angle = rig.yaw.angle
    pending = rig.mapper.pending
    rig.wait(5.0)
    assert rig.yaw.angle == angle
    assert rig.mapper.pending == pending
    assert rig.stick == (0.0, 0.0)


@pytest.mark.parametrize("degrees", [0.7, 1.5, 3, 7, 15, 45, 90, 360])
def test_camera_never_twitches_backwards_after_a_movement(degrees):
    for i in range(6):
        rig = Rig(phase=i / 6)
        rig.move(counts_for(degrees), seconds=0.2)
        rig.settle()
        assert rig.yaw.reversals == 0
        assert rig.yaw.turn_signs <= {1}


def test_nothing_happens_with_no_input():
    rig = Rig()
    rig.wait(2.0)
    assert set(rig.stick_history) == {(0.0, 0.0)}


def test_what_stays_pending_is_less_than_the_smallest_pulse():
    for degrees in (0.3, 1.0, 13.7, 91.3):
        rig = Rig()
        rig.move(counts_for(degrees), seconds=0.2)
        rig.settle()
        assert abs(rig.mapper.pending[0]) < 1.1


# --- Queueing and limits ---


def test_a_fast_flick_is_queued_not_dropped():
    rig = Rig()
    rig.move(counts_for(340), seconds=0.05)
    assert rig.mapper.pending[0] > 300
    rig.settle()
    assert rig.yaw.angle == pytest.approx(340, abs=1.5 * ONE_FRAME_AT_FULL_SPEED)


def test_a_flick_plays_out_at_the_cameras_top_speed():
    rig = Rig()
    rig.move(counts_for(340), seconds=0.02)
    held = 0
    while rig.stick[0] != 0.0 or held == 0:
        rig.tick()
        held += 1
    # 2 seconds at full speed, plus half the ramp.
    assert held * TICK_S == pytest.approx(340 / YAW_RATE + RAMP_S / 2, abs=0.05)


def test_stick_only_ever_goes_to_full_or_centre():
    rig = Rig()
    rig.move(counts_for(40), counts_for(40), seconds=0.1)
    rig.move(-counts_for(10), seconds=0.1)
    rig.settle()
    values = {value for stick in rig.stick_history for value in stick}
    assert values <= {-1.0, 0.0, 1.0}
    assert all(abs(value) > THRESHOLD or value == 0 for value in values)


def test_yaw_queue_has_a_limit():
    rig = Rig()
    rig.move(counts_for(5000), seconds=0.1)
    assert rig.mapper.pending[0] <= 720.0
    rig.settle()
    assert rig.yaw.angle < 720.0 + 1.5 * ONE_FRAME_AT_FULL_SPEED


def test_pitch_budget_cannot_build_up_against_a_limit():
    rig = Rig()
    rig.move(counts_y=-100_000, seconds=0.1)
    assert rig.mapper.pending[1] == pytest.approx(PITCH_RANGE, abs=1)
    # At worst it holds the stick for one full sweep's time, plus the ramp.
    start = len(rig.stick_history)
    rig.settle()
    held = sum(1 for stick in rig.stick_history[start:] if stick[1] != 0.0)
    assert held * TICK_S < PITCH_RANGE / PITCH_RATE + RAMP_S


def test_negative_pitch_budget_is_limited_too():
    rig = Rig()
    rig.move(counts_y=100_000, seconds=0.1)
    assert rig.mapper.pending[1] == pytest.approx(-PITCH_RANGE, abs=1)


CARRY_S = 0.15
SHORT_QUEUE = dict(
    yaw=AxisSettings(SENSITIVITY_X, YAW_RATE, YAW_RATE * CARRY_S),
    pitch=AxisSettings(SENSITIVITY_Y, PITCH_RATE, PITCH_RATE * CARRY_S),
)


def seconds_until_centred(rig):
    ticks = 0
    while rig.stick != (0.0, 0.0):
        rig.tick()
        ticks += 1
    return ticks * rig.tick_s


def test_camera_stops_soon_after_sustained_fast_movement():
    """Regression: a long queue kept the camera turning for seconds, which felt floaty."""
    rig = Rig(**SHORT_QUEUE)
    rig.move(counts_for(600), seconds=1.0)  # 600 degrees/s against a 170 degrees/s camera
    assert rig.stick[0] == 1.0
    assert seconds_until_centred(rig) < CARRY_S + 2 * FRAME_S


def test_camera_stops_soon_after_a_hard_flick_from_rest():
    rig = Rig(**SHORT_QUEUE)
    rig.move(counts_for(2000), seconds=0.05)
    # From a standstill it also has to ramp up, which delays spending the queue.
    assert seconds_until_centred(rig) < CARRY_S + RAMP_S / 2 + 2 * FRAME_S


def test_short_queue_leaves_movement_below_top_speed_untouched():
    rig = Rig(**SHORT_QUEUE)
    rig.move(counts_for(120), seconds=1.0)  # 120 degrees/s: the camera can keep up
    rig.settle()
    assert rig.yaw.angle == pytest.approx(120, abs=1.5 * ONE_FRAME_AT_FULL_SPEED)


def test_short_queue_drops_only_what_the_camera_cannot_turn():
    rig = Rig(**SHORT_QUEUE)
    rig.move(counts_for(600), seconds=1.0)
    rig.settle()
    assert YAW_RATE * 0.8 < rig.yaw.angle < YAW_RATE * 1.3


# --- Directions and axes ---


def test_mouse_right_is_stick_right():
    rig = Rig()
    rig.move(counts_for(40))
    assert (1.0, 0.0) in rig.stick_history
    assert all(stick[0] >= 0 for stick in rig.stick_history)


def test_mouse_up_is_stick_up_unless_inverted():
    rig = Rig()
    rig.move(counts_y=-2000)
    assert (0.0, 1.0) in rig.stick_history
    rig = Rig(invert_y=True)
    rig.move(counts_y=-2000)
    assert (0.0, -1.0) in rig.stick_history


def test_axes_have_separate_sensitivities():
    rig = Rig()
    rig.mapper.update(100, -100, 0.0)
    assert rig.mapper.pending == pytest.approx((100 * SENSITIVITY_X, 100 * SENSITIVITY_Y))


def test_diagonal_movement_gets_each_axis_right():
    rig = Rig()
    rig.move(counts_for(120), -2000, seconds=0.5)
    rig.settle()
    assert rig.yaw.angle == pytest.approx(120, abs=1.5 * ONE_FRAME_AT_FULL_SPEED)
    assert rig.pitch.angle == pytest.approx(2000 * SENSITIVITY_Y, abs=2.0)


def test_there_and_back_ends_up_near_the_start():
    for i in range(6):
        rig = Rig(phase=i / 6)
        rig.move(counts_for(90), seconds=0.3)
        rig.move(-counts_for(90), seconds=0.3)
        rig.settle()
        assert abs(rig.yaw.angle) < 2 * ONE_FRAME_AT_FULL_SPEED


def test_reversing_midway_cancels_what_was_queued():
    rig = Rig()
    rig.move(counts_for(200), seconds=0.05)
    rig.move(-counts_for(200), seconds=0.05)
    rig.settle()
    assert abs(rig.yaw.angle) < 2 * ONE_FRAME_AT_FULL_SPEED


# --- Robustness ---


@pytest.mark.parametrize(("degrees", "seconds"), [(15, 1.0), (30, 1.0), (60, 1.0), (90, 1.0), (90, 2.0), (360, 3.0)])
def test_steady_movement_does_not_beat_against_the_frame_rate(degrees, seconds):
    """Regression: pulses and gaps that weren't whole frames piled up errors in one direction."""
    mean, median, p90 = error_stats(degrees, seconds)
    assert abs(mean) < 0.5 * ONE_FRAME_AT_FULL_SPEED
    assert median < 0.25 * ONE_FRAME_AT_FULL_SPEED
    assert p90 < ONE_FRAME_AT_FULL_SPEED


@pytest.mark.parametrize("jitter_ms", [2, 5])
def test_timing_jitter_adds_no_bias(jitter_ms):
    mean, median, p90 = error_stats(90, 2.0, jitter_s=jitter_ms / 1000)
    assert abs(mean) < ONE_FRAME_AT_FULL_SPEED
    assert median < ONE_FRAME_AT_FULL_SPEED
    assert p90 < 4 * ONE_FRAME_AT_FULL_SPEED


def test_gaps_between_pulses_are_never_shorter_than_a_frame():
    rig = Rig()
    rig.move(counts_for(90), seconds=2.0)
    rig.settle()
    runs = []
    length = 0
    state = None
    for stick in rig.stick_history:
        now = stick[0] != 0.0
        if now != state and state is not None:
            runs.append((state, length))
            length = 0
        state = now
        length += 1
    frame_ticks = 0.0334 / TICK_S
    for is_on, ticks in runs[1:]:  # the first run is the wait before the movement
        assert ticks >= frame_ticks - 1, "a pulse or gap shorter than a game frame"


@pytest.mark.parametrize("game_fps", [29.0, 30.0, 31.0])
def test_a_slightly_wrong_frame_time_adds_no_bias(game_fps):
    mean, median, p90 = error_stats(90, 1.0, camera_frame_s=1 / game_fps)
    assert abs(mean) < ONE_FRAME_AT_FULL_SPEED
    assert median < 2 * ONE_FRAME_AT_FULL_SPEED
    assert p90 < 4 * ONE_FRAME_AT_FULL_SPEED


@pytest.mark.parametrize("wrong_by", [0.8, 1.2])
def test_a_camera_that_differs_from_the_model_still_lands_close(wrong_by):
    rig = Rig(camera_ramp_s=RAMP_S * wrong_by)
    rig.move(counts_for(180), seconds=0.3)
    rig.settle()
    # Long turns barely depend on the ramp.
    assert rig.yaw.angle == pytest.approx(180, abs=2.5 * ONE_FRAME_AT_FULL_SPEED)


@pytest.mark.parametrize("tick_hz", [250, 1000])
def test_result_does_not_depend_on_the_tick_rate(tick_hz):
    rig = Rig(tick_s=1 / tick_hz, phase=0.37)
    rig.move(counts_for(180), seconds=0.3)
    rig.settle()
    assert rig.yaw.angle == pytest.approx(180, abs=1.5 * ONE_FRAME_AT_FULL_SPEED)


def test_reset_clears_everything():
    rig = Rig()
    rig.move(counts_for(300), seconds=0.05)
    assert rig.stick[0] == 1.0
    rig.mapper.reset()
    assert rig.mapper.pending == (0.0, 0.0)
    assert rig.mapper.update(0, 0, TICK_S) == (0.0, 0.0)


def test_zero_dt_is_safe():
    mapper = BudgetMapper(settings())
    assert mapper.update(0, 0, 0.0) == (0.0, 0.0)
    assert mapper.pending == (0.0, 0.0)


def test_a_long_stall_does_not_break_anything():
    rig = Rig()
    rig.move(counts_for(90), seconds=0.1)
    rig.mapper.update(0, 0, 5.0)  # the process froze for 5 seconds
    rig.settle()
    assert abs(rig.mapper.pending[0]) < 1.1
