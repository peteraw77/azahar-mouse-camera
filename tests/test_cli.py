import sys
from pathlib import Path

import pytest

from mousecam import __main__ as cli
from mousecam import config as config_module
from mousecam.config import default_config_path
from mousecam.win32 import started_by_double_click


@pytest.fixture
def launched(monkeypatch):
    """Record which command ran, and with which settings path."""
    calls = {}
    monkeypatch.setattr(cli, "claim_single_instance", lambda name: True)
    monkeypatch.setattr(
        "mousecam.app.run_app", lambda config: calls.setdefault("run", config)
    )
    return calls


def test_no_command_means_run(monkeypatch, launched):
    monkeypatch.setattr(sys, "argv", ["azahar-mouse-camera"])
    assert cli.main() == 0
    assert "run" in launched


def test_run_with_options_still_works(monkeypatch, launched):
    monkeypatch.setattr(sys, "argv", ["mousecam", "run", "--mode", "velocity"])
    assert cli.main() == 0
    assert launched["run"].mode == "velocity"


def test_config_is_in_the_current_folder_from_source():
    assert default_config_path() == Path("config.toml")


def test_config_is_beside_the_exe_when_packaged(monkeypatch):
    exe = Path("C:/Games/azahar-mouse-camera/azahar-mouse-camera.exe")
    monkeypatch.setattr(config_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_module.sys, "executable", str(exe))
    assert default_config_path() == exe.parent / "config.toml"


# --- Keeping the window open, so a double-click's error can be read ---


@pytest.fixture
def waits(monkeypatch):
    """Pretend to be double-clicked, and count waits for Enter."""
    pressed = []
    monkeypatch.setattr(cli, "started_by_double_click", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": pressed.append(prompt))
    return pressed


def test_clean_exit_closes_straight_away(monkeypatch, waits):
    monkeypatch.setattr(cli, "main", lambda: 0)
    assert cli.console_main() == 0
    assert waits == []


def test_error_exit_waits_for_enter(monkeypatch, waits):
    monkeypatch.setattr(cli, "main", lambda: 1)
    assert cli.console_main() == 1
    assert len(waits) == 1


def test_crash_is_shown_and_waits_for_enter(monkeypatch, waits, capsys):
    def crash():
        raise ValueError("something broke")

    monkeypatch.setattr(cli, "main", crash)
    assert cli.console_main() == 1
    assert "something broke" in capsys.readouterr().err
    assert len(waits) == 1


def test_bad_arguments_wait_for_enter(monkeypatch, waits):
    def bad_arguments():
        raise SystemExit(2)

    monkeypatch.setattr(cli, "main", bad_arguments)
    assert cli.console_main() == 2
    assert len(waits) == 1


def test_help_closes_straight_away(monkeypatch, waits):
    def help_text():
        raise SystemExit(0)

    monkeypatch.setattr(cli, "main", help_text)
    assert cli.console_main() == 0
    assert waits == []


def test_from_a_terminal_errors_do_not_wait(monkeypatch, waits):
    monkeypatch.setattr(cli, "started_by_double_click", lambda: False)
    monkeypatch.setattr(cli, "main", lambda: 1)
    assert cli.console_main() == 1
    assert waits == []


def test_no_input_to_read_is_safe(monkeypatch):
    def no_input(prompt=""):
        raise EOFError

    monkeypatch.setattr(cli, "started_by_double_click", lambda: True)
    monkeypatch.setattr("builtins.input", no_input)
    monkeypatch.setattr(cli, "main", lambda: 1)
    assert cli.console_main() == 1


def test_console_check_runs():
    assert started_by_double_click() in (True, False)
