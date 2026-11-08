"""Runs the calibration flow against a simulated camera and a simulated Peter."""

import math

import pytest

from mousecam import __main__ as cli
from mousecam.calibrate import (
    DONE,
    MARK,
    QUIT,
    STAGES,
    Aborted,
    ask,
    curve_levels,
    level_before,
    rate_from_marks,
    run_stages,
    stage_angle,
    stage_curve,
    stage_deadzone,
    stage_pitch,
    stage_pulse,
    stage_yaw,
    steps,
    summarize,
    with_curve_point,
)
from mousecam.config import AxisCalibration, Calibration, PulseCalibration, load_config, save_calibration

FRAME_S = 1 / 30
REACTION_S = 0.25


class SimCamera:
    """Reads the stick once per game frame, like the 30 fps game."""

    def __init__(self, deadzone=0.2, max_rate=120.0, fixed_speed=False, spin_up_s=0.0, pitch_rate=60.0, has_pitch=True):
        self.deadzone = deadzone
        self.max_rate = max_rate
        self.fixed_speed = fixed_speed
        self.spin_up_s = spin_up_s
        self.pitch_rate = pitch_rate
        self.has_pitch = has_pitch
        self.yaw = 0.0
        self.pitch = 0.0
        self.pitch_limit = 45.0
        self.speed = 0.0
        self.travelled = 0.0

    def rate(self, deflection):
        magnitude = abs(deflection)
        if magnitude <= self.deadzone:
            return 0.0
        fraction = 1.0 if self.fixed_speed else (magnitude - self.deadzone) / (1.0 - self.deadzone)
        return math.copysign(fraction, deflection)

    def frame(self, x, y):
        target = self.rate(x) * self.max_rate
        if self.spin_up_s > 0 and target != 0:
            # Accelerates gradually, but stops dead on release, so short pulses lose out.
            self.speed += (target - self.speed) * (1 - math.exp(-FRAME_S / self.spin_up_s))
        else:
            self.speed = target
        self.yaw += self.speed * FRAME_S
        self.travelled += abs(self.speed) * FRAME_S
        if self.has_pitch:
            moved = self.rate(y) * self.pitch_rate * FRAME_S
            new = max(-self.pitch_limit, min(self.pitch_limit, self.pitch + moved))
            self.travelled += abs(new - self.pitch)
            self.pitch = new


class SimPeter:
    """Reads the prompts and marks what he sees, reacting a moment late."""

    def __init__(self, laps=None, answers=None, quit_on=None, skip_on=()):
        self.laps = laps
        self.answers = answers or {}
        self.quit_on = quit_on
        self.skip_on = skip_on
        self.pending = []
        self.prompt = ""
        self.base = 0.0
        self.base_travelled = 0.0
        self.base_time = 0.0
        self.next_landmark = None
        self.laps_marked = 0
        self.done_sent = False
        self.notified = False

    def new_prompt(self, text, rig):
        self.prompt = text
        self.pending = []
        self.base = rig.camera.yaw
        self.base_travelled = rig.camera.travelled
        self.base_time = rig.t
        self.next_landmark = None
        self.laps_marked = 0
        self.done_sent = False
        self.notified = False
        self.limit_seen_at = None

    def later(self, rig, key):
        self.pending.append((rig.t + REACTION_S, key))

    def watch(self, rig):
        camera = rig.camera
        prompt = self.prompt
        if self.quit_on and self.quit_on in prompt and not self.notified:
            self.notified = True
            self.later(rig, QUIT)
        elif any(text in prompt for text in self.skip_on):
            if not self.notified:
                self.notified = True
                self.later(rig, DONE)
        elif "starts moving" in prompt:
            if not self.notified and camera.travelled - self.base_travelled > 0.2:
                self.notified = True
                self.later(rig, MARK)
        elif "landmark" in prompt:
            self.watch_laps(rig)
        elif "stops at the limit" in prompt:
            self.watch_limit(rig)
        elif "F9 = yes" in prompt and not self.notified:
            self.notified = True
            self.later(rig, MARK if self.answer(rig) else DONE)
        elif "Press F9 to begin" in prompt and not self.notified:
            self.notified = True
            self.later(rig, MARK)

    def answer(self, rig):
        for key, value in self.answers.items():
            if key in self.prompt:
                return value
        if "pulses move" in self.prompt:
            return rig.pulse_travelled > 0.05
        return True

    def watch_laps(self, rig):
        wanted = 3 if "after 3 full laps" in self.prompt else 1
        turned = abs(rig.camera.yaw - self.base)
        if self.done_sent:
            return
        if rig.t - self.base_time > 12 and turned < 0.5:
            self.done_sent = True
            self.later(rig, DONE)
            return
        if self.next_landmark is None:
            if turned > 10:  # the first time the landmark comes round
                self.next_landmark = turned + 360
                self.later(rig, MARK)
        elif turned >= self.next_landmark:
            self.next_landmark += 360
            self.laps_marked += 1
            self.later(rig, MARK)
            if self.laps_marked == wanted:
                self.pending.append((rig.t + REACTION_S + 0.3, DONE))
                self.done_sent = True

    def watch_limit(self, rig):
        camera = rig.camera
        if not self.notified and abs(camera.pitch) >= camera.pitch_limit:
            # Only a limit in the direction the stick is pushing counts.
            if rig.y and math.copysign(1, rig.y) == math.copysign(1, camera.pitch):
                self.notified = True
                self.later(rig, MARK)
        if not self.notified and rig.t - self.base_time > 15:
            self.notified = True
            self.later(rig, DONE)

    def keys(self, rig):
        self.watch(rig)
        due = [key for when, key in self.pending if when <= rig.t]
        self.pending = [(when, key) for when, key in self.pending if when > rig.t]
        return due


class SimRig:
    def __init__(self, camera, peter):
        self.camera = camera
        self.peter = peter
        self.t = 0.0
        self.x = 0.0
        self.y = 0.0
        self.next_frame = 0.0
        self.said = []
        self.pulse_travelled = 0.0
        self.pulse_base = 0.0

    def now(self):
        return self.t

    def stick(self, x, y):
        self.x, self.y = x, y

    def poll(self):
        return self.peter.keys(self)

    def sleep(self, seconds):
        self.t += seconds
        while self.next_frame <= self.t:
            self.camera.frame(self.x, self.y)
            self.next_frame += FRAME_S

    def say(self, text, beeps=0):
        self.said.append(text)
        if "pulses of" in text:
            self.pulse_base = self.camera.travelled
        if "pulses move" in text:
            self.pulse_travelled = self.camera.travelled - self.pulse_base
        if beeps:  # a beep is a new instruction, which is what Peter reacts to
            self.peter.new_prompt(text, self)


def make_rig(camera=None, **peter):
    return SimRig(camera or SimCamera(), SimPeter(**peter))


def run_stage(stage, calibration=None, rig=None):
    rig = rig or make_rig()
    return stage(rig, calibration or Calibration()), rig


# --- Pure calculations ---


def test_rate_from_marks():
    assert rate_from_marks([10.0, 13.0, 16.0]) == pytest.approx(120.0)


@pytest.mark.parametrize("marks", [[], [1.0], [5.0, 5.0]])
def test_rate_needs_a_full_lap(marks):
    assert rate_from_marks(marks) is None


def test_level_before():
    history = [(0.0, 0.1), (1.0, 0.2), (2.0, 0.3)]
    assert level_before(history, -1.0) == 0.1
    assert level_before(history, 1.5) == 0.2
    assert level_before(history, 9.0) == 0.3


def test_steps_have_no_float_drift_and_include_the_end():
    assert steps(0.04, 1.0, 0.04)[-1] == 1.0
    assert steps(0.1, 0.3, 0.1) == [0.1, 0.2, 0.3]


def test_curve_levels_skip_the_deadzone_and_add_a_point_just_above():
    assert curve_levels(None) == [0.25, 0.4, 0.6, 0.8]
    assert curve_levels(0.3) == [0.35, 0.4, 0.6, 0.8]
    assert curve_levels(0.1) == [0.15, 0.25, 0.4, 0.6, 0.8]


def test_with_curve_point_replaces_and_sorts():
    curve = with_curve_point(((1.0, 100.0), (0.4, 20.0)), 0.6, 50.0)
    assert curve == ((0.4, 20.0), (0.6, 50.0), (1.0, 100.0))
    assert with_curve_point(curve, 0.6, 55.0)[1] == (0.6, 55.0)


# --- Stages against the simulated camera ---


def test_deadzone_is_measured():
    calibration, rig = run_stage(stage_deadzone)
    assert calibration.yaw.deadzone == pytest.approx(0.2, abs=0.03)
    assert (rig.x, rig.y) == (0.0, 0.0)


def test_deadzone_can_report_nothing():
    rig = make_rig(SimCamera(deadzone=2.0))
    calibration, rig = run_stage(stage_deadzone, rig=rig)
    assert calibration.yaw.deadzone is None


def test_full_rate_is_measured():
    calibration, rig = run_stage(stage_yaw)
    assert calibration.yaw.max_rate == pytest.approx(120.0, rel=0.01)
    assert calibration.yaw.curve == ((1.0, calibration.yaw.max_rate),)
    assert (rig.x, rig.y) == (0.0, 0.0)


@pytest.mark.parametrize(("answer", "coasts"), [(True, False), (False, True)])
def test_coasting_answer_is_recorded(answer, coasts):
    rig = make_rig(answers={"stop straight away": answer})
    calibration, _ = run_stage(stage_yaw, rig=rig)
    assert calibration.pulse.coasts is coasts


def test_curve_matches_the_camera():
    start = Calibration(yaw=AxisCalibration(deadzone=0.2, max_rate=120.0, curve=((1.0, 120.0),)))
    calibration, _ = run_stage(stage_curve, start)
    camera = SimCamera()
    levels = [level for level, _ in calibration.yaw.curve]
    assert levels == [0.25, 0.4, 0.6, 0.8, 1.0]
    for level, rate in calibration.yaw.curve:
        assert rate == pytest.approx(camera.rate(level) * camera.max_rate, rel=0.03)


def test_level_below_the_real_deadzone_records_zero():
    start = Calibration(yaw=AxisCalibration(deadzone=None))
    rig = make_rig(SimCamera(deadzone=0.5))
    calibration, _ = run_stage(stage_curve, start, rig)
    rates = dict(calibration.yaw.curve)
    assert rates[0.25] == 0.0
    assert rates[0.4] == 0.0
    assert rates[0.8] > 0.0


def test_pulse_trains_match_a_camera_without_spin_up():
    start = Calibration(yaw=AxisCalibration(max_rate=120.0))
    calibration, rig = run_stage(stage_pulse, start)
    assert 100 in calibration.pulse.registered_ms
    assert 50 in calibration.pulse.registered_ms
    assert [train[:2] for train in calibration.pulse.trains] == [(100.0, 100.0), (66.7, 66.7), (33.3, 33.3)]
    for _, _, ratio in calibration.pulse.trains:
        assert ratio == pytest.approx(1.0, abs=0.12)
    assert (rig.x, rig.y) == (0.0, 0.0)


def test_pulse_trains_detect_spin_up():
    # A deadzone of 0 and a full-stick rate that the spin-up has time to reach.
    start = Calibration(yaw=AxisCalibration(max_rate=120.0))
    rig = make_rig(SimCamera(deadzone=0.0, spin_up_s=0.3))
    calibration, _ = run_stage(stage_pulse, start, rig)
    ratios = [ratio for _, _, ratio in calibration.pulse.trains]
    assert ratios and all(ratio < 0.85 for ratio in ratios)
    assert ratios[0] > ratios[-1]  # the shorter the pulses, the more rotation is lost
    assert "lose rotation" in "\n".join(summarize(calibration))


def test_pulse_trains_are_skipped_without_a_full_rate():
    calibration, rig = run_stage(stage_pulse)
    assert calibration.pulse.trains == ()
    assert any("Skipping pulse trains" in text for text in rig.said)


def test_pitch_is_measured():
    calibration, rig = run_stage(stage_pitch)
    pitch = calibration.pitch
    assert pitch.deadzone == pytest.approx(0.2, abs=0.03)
    assert pitch.range_deg == 90.0
    # The true sweep takes 90 degrees / 60 degrees/s = 1.5 s at full stick.
    assert pitch.max_rate == pytest.approx(60.0, rel=0.2)
    assert [level for level, _ in pitch.curve] == [0.4, 0.6, 1.0]
    rates = [rate for _, rate in pitch.curve]
    assert rates == sorted(rates)
    assert (rig.x, rig.y) == (0.0, 0.0)


def test_pitch_prompts_never_say_which_way_the_camera_should_go():
    """The game's camera setting decides that, so naming it looked like a bug in-game."""
    _, rig = run_stage(stage_pitch)
    prompts = [text for text in rig.said if "Pitch at stick" in text or "Timing now" in text]
    assert prompts
    for text in prompts:
        assert "stick up" in text or "stick down" in text
        assert "tilts" not in text


def test_skipping_a_later_pass_keeps_the_pass_that_finished():
    rig = make_rig(skip_on=("Pitch at stick 1, pass 2",))
    calibration, _ = run_stage(stage_pitch, rig=rig)
    # One pass of 90 degrees at 60 degrees/s still gives the full-stick rate.
    assert calibration.pitch.max_rate == pytest.approx(60.0, rel=0.2)
    assert dict(calibration.pitch.curve)[1.0] == calibration.pitch.max_rate


def test_a_skipped_level_is_left_out_rather_than_saved_as_no_movement():
    rig = make_rig(skip_on=("Pitch at stick 0.6", "Pitch at stick 1,"))
    calibration, rig = run_stage(stage_pitch, rig=rig)
    levels = dict(calibration.pitch.curve)
    assert 1.0 not in levels and 0.6 not in levels
    assert 0.4 in levels and levels[0.4] > 0
    assert calibration.pitch.max_rate is None
    assert any("Nothing measured at 0.6" in text for text in rig.said)


def test_degrees_per_pulse_match_the_camera():
    calibration, rig = run_stage(stage_angle)
    camera = SimCamera()
    assert [on_ms for on_ms, _ in calibration.pulse.angles] == [200.0, 133.3, 100.0, 66.7, 33.3]
    for on_ms, degrees in calibration.pulse.angles:
        # The camera turns for whole frames, and the gap averages over where they fall.
        assert degrees == pytest.approx(camera.max_rate * on_ms / 1000, rel=0.1)
    assert (rig.x, rig.y) == (0.0, 0.0)


def test_degrees_per_pulse_show_spin_up_losses():
    rig = make_rig(SimCamera(deadzone=0.0, spin_up_s=0.1))
    calibration, _ = run_stage(stage_angle, rig=rig)
    for on_ms, degrees in calibration.pulse.angles:
        assert degrees < 120.0 * on_ms / 1000
    assert "Pulse of 33.3 ms" in "\n".join(summarize(calibration))


def test_a_pulse_with_no_finished_lap_is_left_out_rather_than_saved_as_zero():
    rig = make_rig(skip_on=("Repeating 33.3 ms",))
    calibration, rig = run_stage(stage_angle, rig=rig)
    assert [on_ms for on_ms, _ in calibration.pulse.angles] == [200.0, 133.3, 100.0, 66.7]
    assert any("No result for 33.3 ms" in text for text in rig.said)


def test_ctrl_c_stops_without_a_traceback(monkeypatch, capsys):
    def interrupted(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr("sys.argv", ["mousecam", "calibrate", "--only", "pitch"])
    monkeypatch.setattr(cli, "claim_single_instance", lambda name: True)
    monkeypatch.setattr("mousecam.calibrate.run_calibration", interrupted)
    assert cli.main() == 0
    assert "Stopped." in capsys.readouterr().out


def test_angle_stage_keeps_other_pulse_results():
    start = Calibration(pulse=PulseCalibration(registered_ms=(16,), coasts=False))
    calibration, _ = run_stage(stage_angle, start)
    assert calibration.pulse.registered_ms == (16,)
    assert calibration.pulse.coasts is False


def test_pitch_can_be_skipped():
    rig = make_rig(answers={"tilt up and down": False})
    calibration, _ = run_stage(stage_pitch, rig=rig)
    assert calibration.pitch == AxisCalibration()


def test_stage_names_match_the_command_line():
    assert tuple(STAGES) == cli.STAGE_NAMES


def test_stray_key_press_cannot_answer_the_next_question():
    rig = make_rig()
    rig.peter.keys = lambda _: []  # Peter does nothing, apart from one early press
    presses = [[MARK]]
    answers = [[DONE]]
    rig.poll = lambda: presses.pop() if presses else (answers.pop() if answers else [])
    assert ask(rig, "Is this right?") is False  # the stray F9 is dropped, F7 answers


# --- A whole run ---


def test_full_run_gives_correct_results_and_saves_them(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[velocity]\nfull_speed_x = 1234.0\n', "utf-8")
    rig = make_rig()
    calibration, finished = run_stages(rig, Calibration(), list(STAGES), lambda c: save_calibration(path, c))

    assert finished
    assert (rig.x, rig.y) == (0.0, 0.0)
    config = load_config(path)
    assert config.calibration == calibration
    assert config.velocity.full_speed_x == 1234.0
    assert calibration.yaw.deadzone == pytest.approx(0.2, abs=0.03)
    assert calibration.yaw.max_rate == pytest.approx(120.0, rel=0.01)
    assert len(calibration.yaw.curve) >= 5
    assert calibration.pitch.max_rate is not None
    assert calibration.pulse.trains

    text = "\n".join(summarize(calibration))
    assert "roughly linear" in text
    assert "Yaw deadzone" in text
    assert "Pitch" in text


def test_only_chosen_stages_run_and_other_results_stay(tmp_path):
    earlier = Calibration(yaw=AxisCalibration(max_rate=99.0), pulse=PulseCalibration(coasts=True))
    calibration, finished = run_stages(make_rig(), earlier, ["deadzone"], lambda c: None)
    assert finished
    assert calibration.yaw.max_rate == 99.0
    assert calibration.pulse.coasts is True
    assert calibration.yaw.deadzone is not None


def test_abort_centres_the_stick_and_keeps_finished_stages(tmp_path):
    path = tmp_path / "config.toml"
    rig = make_rig(quit_on="Full stick left")
    calibration, finished = run_stages(rig, Calibration(), list(STAGES), lambda c: save_calibration(path, c))
    assert not finished
    assert (rig.x, rig.y) == (0.0, 0.0)
    saved = load_config(path).calibration
    assert saved.yaw.deadzone is not None  # the deadzone stage finished
    assert saved.yaw.max_rate is None  # the yaw stage didn't


def test_quit_key_raises_during_waits():
    rig = make_rig(quit_on="Deadzone, right")
    with pytest.raises(Aborted):
        stage_deadzone(rig, Calibration())
    assert (rig.x, rig.y) == (0.0, 0.0)


# --- Summary wording ---


def test_summary_spots_a_fixed_speed_camera():
    curve = ((0.3, 118.0), (0.6, 120.0), (1.0, 120.0))
    text = "\n".join(summarize(Calibration(yaw=AxisCalibration(deadzone=0.25, max_rate=120.0, curve=curve))))
    assert "fixed speed" in text


def test_summary_spots_a_curved_response():
    curve = ((0.4, 5.0), (0.6, 15.0), (0.8, 40.0), (1.0, 120.0))
    text = "\n".join(summarize(Calibration(yaw=AxisCalibration(deadzone=0.2, max_rate=120.0, curve=curve))))
    assert "curved" in text


def test_summary_flags_pulses_that_turn_less_than_predicted():
    pulse = PulseCalibration(trains=((50.0, 50.0, 0.6),))
    assert "turns less than the stick time predicts" in "\n".join(summarize(Calibration(pulse=pulse)))


def test_summary_flags_beating_against_the_frame_rate():
    pulse = PulseCalibration(trains=((50.0, 50.0, 1.33),))
    assert "beating against the frame rate" in "\n".join(summarize(Calibration(pulse=pulse)))


def test_summary_of_nothing_is_safe():
    assert summarize(Calibration())


def test_fixed_speed_camera_is_recognised_end_to_end():
    rig = make_rig(SimCamera(fixed_speed=True))
    calibration, finished = run_stages(rig, Calibration(), ["deadzone", "yaw", "curve"], lambda c: None)
    assert finished
    assert "fixed speed" in "\n".join(summarize(calibration))
