import pytest

from mousecam.bind import button_keys, help_text
from mousecam.config import Config, ConfigError, parse_config
from mousecam.cursor import decode_button_message
from mousecam.mapper import ButtonMapper
from mousecam.pad import BUTTON_NAMES, BUTTONS

MIN_STATE = 0.07
MAPPING = {"left": "a", "right": "b"}


def run_events(mapper, until, step=0.002):
    """Tick until a time, and return every change with the time it happened."""
    changes = []
    now = 0.0
    while now <= until:
        changes += [(round(now, 3), *change) for change in mapper.tick(now)]
        now += step
    return changes


def pressed_times(changes, button="a"):
    return [(when, pressed) for when, name, pressed in changes if name == button]


# --- Reading clicks ---


@pytest.mark.parametrize(
    ("msg", "wparam", "expected"),
    [
        (0x0201, 0, ("left", True)),
        (0x0202, 0, ("left", False)),
        (0x0204, 0, ("right", True)),
        (0x0205, 0, ("right", False)),
        (0x0207, 0, ("middle", True)),
        (0x0208, 0, ("middle", False)),
        (0x020B, 1 << 16, ("x1", True)),
        (0x020C, 1 << 16, ("x1", False)),
        (0x020B, 2 << 16, ("x2", True)),
        (0x020C, 2 << 16, ("x2", False)),
    ],
)
def test_click_messages_are_decoded(msg, wparam, expected):
    assert decode_button_message(msg, wparam) == expected


@pytest.mark.parametrize(("msg", "wparam"), [(0x0200, 0), (0x0020, 0), (0x020B, 9 << 16)])
def test_other_messages_are_not_clicks(msg, wparam):
    assert decode_button_message(msg, wparam) is None


# --- From mouse button to pad button ---


def test_press_goes_through_at_once():
    mapper = ButtonMapper(MAPPING, MIN_STATE)
    mapper.mouse_event("left", True)
    assert mapper.tick(1.0) == [("a", True)]
    assert mapper.tick(1.001) == []


def test_slow_click_keeps_its_length():
    mapper = ButtonMapper(MAPPING, MIN_STATE)
    mapper.mouse_event("left", True)
    assert mapper.tick(1.0) == [("a", True)]
    assert mapper.tick(1.5) == []
    mapper.mouse_event("left", False)
    assert mapper.tick(1.5) == [("a", False)]


def test_very_quick_click_is_held_long_enough_for_the_game_to_see():
    mapper = ButtonMapper(MAPPING, MIN_STATE)
    mapper.mouse_event("left", True)
    mapper.mouse_event("left", False)
    changes = pressed_times(run_events(mapper, 0.2))
    assert [pressed for _, pressed in changes] == [True, False]
    assert changes[1][0] - changes[0][0] == pytest.approx(MIN_STATE, abs=0.003)


def test_quick_double_click_stays_two_presses():
    mapper = ButtonMapper(MAPPING, MIN_STATE)
    for _ in range(2):
        mapper.mouse_event("left", True)
        mapper.mouse_event("left", False)
    changes = pressed_times(run_events(mapper, 0.5))
    assert [pressed for _, pressed in changes] == [True, False, True, False]
    for earlier, later in zip(changes, changes[1:]):
        assert later[0] - earlier[0] >= MIN_STATE - 0.003


def test_buttons_are_independent():
    mapper = ButtonMapper(MAPPING, MIN_STATE)
    mapper.mouse_event("left", True)
    mapper.mouse_event("right", True)
    assert sorted(mapper.tick(0.0)) == [("a", True), ("b", True)]


def test_two_mouse_buttons_can_share_a_pad_button():
    mapper = ButtonMapper({"left": "a", "x1": "a"}, 0.0)
    mapper.mouse_event("left", True)
    mapper.mouse_event("x1", True)
    assert mapper.tick(1.0) == [("a", True)]
    mapper.mouse_event("left", False)
    assert mapper.tick(2.0) == []
    mapper.mouse_event("x1", False)
    assert mapper.tick(3.0) == [("a", False)]


def test_unmapped_buttons_are_ignored():
    mapper = ButtonMapper(MAPPING, MIN_STATE)
    mapper.mouse_event("x2", True)
    assert mapper.tick(1.0) == []
    assert mapper.held == set()


def test_release_with_no_press_is_ignored():
    """A button held as the camera came on, and let go after."""
    mapper = ButtonMapper(MAPPING, MIN_STATE)
    mapper.mouse_event("left", False)
    assert mapper.tick(1.0) == []


def test_held_reports_mouse_buttons():
    mapper = ButtonMapper(MAPPING, MIN_STATE)
    mapper.mouse_event("left", True)
    assert mapper.held == {"left"}
    mapper.mouse_event("left", False)
    assert mapper.held == set()


def test_release_all_releases_what_is_down_and_forgets_what_is_queued():
    mapper = ButtonMapper(MAPPING, MIN_STATE)
    mapper.mouse_event("left", True)
    mapper.tick(1.0)
    mapper.mouse_event("left", False)
    mapper.mouse_event("left", True)
    assert mapper.release_all() == [("a", False)]
    assert mapper.held == set()
    assert mapper.tick(5.0) == []


def test_release_all_with_nothing_down():
    assert ButtonMapper(MAPPING, MIN_STATE).release_all() == []


def test_a_press_after_release_all_works_at_once():
    mapper = ButtonMapper(MAPPING, MIN_STATE)
    mapper.mouse_event("left", True)
    mapper.tick(1.0)
    mapper.release_all()
    mapper.mouse_event("left", True)
    assert mapper.tick(1.001) == [("a", True)]


# --- Settings ---


def test_default_mapping_uses_all_five_buttons():
    assert Config().buttons.mapping() == {"left": "a", "right": "b", "middle": "x", "x1": "y", "x2": "lb"}


def test_empty_name_means_unused():
    mapping = parse_config({"buttons": {"middle": "", "x2": ""}}).buttons.mapping()
    assert "middle" not in mapping and "x2" not in mapping
    assert mapping["left"] == "a"


@pytest.mark.parametrize("name", BUTTON_NAMES)
def test_all_pad_button_names_are_accepted(name):
    assert parse_config({"buttons": {"left": name}}).buttons.left == name


@pytest.mark.parametrize(
    "buttons",
    [{"left": "attack"}, {"typo": "a"}, {"min_state_ms": -1}, {"min_state_ms": "long"}],
)
def test_bad_button_settings_are_rejected(buttons):
    with pytest.raises(ConfigError):
        parse_config({"buttons": buttons})


def test_every_pad_button_name_is_a_real_vgamepad_constant():
    """Importing vgamepad connects to the driver, which isn't available to every test run."""
    vgamepad = pytest.importorskip("vgamepad")
    for flag in BUTTONS.values():
        assert hasattr(vgamepad.XUSB_BUTTON, flag)


# --- Bind helper ---


def test_bind_helper_numbers_the_buttons_in_use():
    keys = button_keys({"left": "a", "x1": "y"})
    assert keys == {"1": ("left", "a"), "2": ("x1", "y")}
    text = help_text(keys)
    assert "1        Press pad button a once, for your left mouse button" in text
    assert "2        Press pad button y once, for your x1 mouse button" in text


def test_bind_helper_keys_do_not_clash_with_its_other_keys():
    keys = button_keys(Config().buttons.mapping())
    assert not set(keys) & {"a", "r", "l", "u", "d", "q"}


def test_bind_helper_text_with_no_buttons():
    assert "Press pad button" not in help_text({})
