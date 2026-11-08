"""Load config.toml, and save calibration results into it.

Any setting left out falls back to the defaults here.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

MODES = ("budget", "velocity")


CALIBRATION_NOTE = "# Written by `python -m mousecam calibrate`. Rerun it rather than editing below."


class ConfigError(ValueError):
    """config.toml can't be read or has an invalid value."""


@dataclass(frozen=True)
class HotkeyConfig:
    toggle: str = "F8"
    quit: str = "Ctrl+F8"


@dataclass(frozen=True)
class VelocityConfig:
    full_speed_x: float = 3000.0
    full_speed_y: float = 1000.0
    smoothing_ms: float = 40.0
    min_deflection: float = 0.0


@dataclass(frozen=True)
class BudgetConfig:
    sensitivity_x: float = 0.03  # degrees per mouse count
    sensitivity_y: float = 0.09  # in pitch's nominal degrees
    ramp_ms: float = 164.0  # fitted to measured pulses
    fade_ms: float = 80.0  # fitted to measured pulses
    frame_ms: float = 33.4  # two 3DS screen refreshes at 59.83 Hz
    max_carry_ms: float = 150.0  # the longest the camera can keep turning after the mouse stops


@dataclass(frozen=True)
class AxisCalibration:
    """Measured behaviour of one camera axis. None or empty means not measured yet."""

    deadzone: float | None = None  # smallest stick deflection that moves the camera
    max_rate: float | None = None  # degrees/s at full deflection
    curve: tuple[tuple[float, float], ...] = ()  # (deflection, degrees/s), sorted
    range_deg: float | None = None  # distance between the limits, if the axis has them


@dataclass(frozen=True)
class PulseCalibration:
    """How the camera responds to short stick pulses. Empty means not measured yet."""

    registered_ms: tuple[int, ...] = ()  # single pulse lengths that moved the camera
    missed_ms: tuple[int, ...] = ()  # single pulse lengths that didn't
    # (on ms, off ms, turn rate as a fraction of what max_rate predicts for that duty)
    trains: tuple[tuple[float, float, float], ...] = ()
    angles: tuple[tuple[float, float], ...] = ()  # (pulse ms, degrees turned per pulse)
    coasts: bool | None = None  # keeps turning after the stick is released


@dataclass(frozen=True)
class Calibration:
    yaw: AxisCalibration = field(default_factory=AxisCalibration)
    pitch: AxisCalibration = field(default_factory=AxisCalibration)
    pulse: PulseCalibration = field(default_factory=PulseCalibration)


@dataclass(frozen=True)
class Config:
    mode: str = "velocity"
    invert_y: bool = False
    debug: bool = False
    tick_hz: int = 500
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    velocity: VelocityConfig = field(default_factory=VelocityConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    calibration: Calibration = field(default_factory=Calibration)


def load_config(path: Path) -> Config:
    """Read the config file. A missing file just means all defaults."""
    if not path.exists():
        return Config()
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return parse_config(data)


def parse_config(data: dict) -> Config:
    data = dict(data)
    hotkeys = HotkeyConfig(**_section(data, "hotkeys", HotkeyConfig))
    velocity = VelocityConfig(**_section(data, "velocity", VelocityConfig))
    budget = BudgetConfig(**_section(data, "budget", BudgetConfig))
    calibration = _parse_calibration(data)
    _reject_unknown(data, Config, "top level")
    config = Config(hotkeys=hotkeys, velocity=velocity, budget=budget, calibration=calibration, **data)
    _validate(config)
    return config


def _parse_calibration(data: dict) -> Calibration:
    section = _section(data, "calibration", Calibration)
    return Calibration(
        yaw=_parse_axis(section, "yaw"),
        pitch=_parse_axis(section, "pitch"),
        pulse=_parse_pulse(section),
    )


def _parse_axis(section: dict, name: str) -> AxisCalibration:
    values = _section(section, name, AxisCalibration)
    where = f"calibration.{name}"
    for key in ("deadzone", "max_rate", "range_deg"):
        if key in values:
            _require_number(f"{where}.{key}", values[key])
    if "deadzone" in values and not 0 <= values["deadzone"] <= 1:
        raise ConfigError(f"{where}.deadzone must be between 0 and 1")
    return AxisCalibration(**{**values, "curve": _rows(values.get("curve", ()), 2, f"{where}.curve")})


def _parse_pulse(section: dict) -> PulseCalibration:
    values = _section(section, "pulse", PulseCalibration)
    where = "calibration.pulse"
    for key in ("registered_ms", "missed_ms"):
        items = values.get(key, ())
        for item in items:
            _require_number(f"{where}.{key}", item)
        values[key] = tuple(items)
    values["trains"] = _rows(values.get("trains", ()), 3, f"{where}.trains")
    values["angles"] = _rows(values.get("angles", ()), 2, f"{where}.angles")
    if "coasts" in values:
        _require_type(f"{where}.coasts", values["coasts"], bool)
    return PulseCalibration(**values)


def _rows(rows, width: int, name: str) -> tuple[tuple[float, ...], ...]:
    """Check a TOML list of equal-length number lists, and make it hashable."""
    result = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != width:
            raise ConfigError(f"{name} must be a list of {width}-number lists")
        for value in row:
            _require_number(name, value)
        result.append(tuple(row))
    return tuple(result)


def save_calibration(path: Path, calibration: Calibration) -> None:
    """Write the calibration into the config file, leaving everything else as it was."""
    text = path.read_text("utf-8") if path.exists() else ""
    kept = _without_calibration(text).rstrip()
    block = calibration_to_toml(calibration)
    new_text = f"{kept}\n\n{block}" if kept else block

    # Prove the result reads back correctly before touching the real file.
    try:
        written = parse_config(tomllib.loads(new_text))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Not saving calibration, the result wouldn't be valid: {exc}") from exc
    if written.calibration != calibration:
        raise ConfigError(f"Not saving calibration: it wouldn't read back correctly from {path}")

    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(new_text, "utf-8")
    os.replace(temporary, path)  # a crash mid-save can't leave a half-written config


def _without_calibration(text: str) -> str:
    """Drop the calibration tables, so a fresh block can replace them."""
    kept = []
    skipping = False
    for line in text.splitlines():
        header = re.match(r"\s*\[+\s*([^\]\s]+)", line)
        if header:
            skipping = header.group(1).split(".")[0] == "calibration"
        if not skipping and line.strip() != CALIBRATION_NOTE:
            kept.append(line)
    return "\n".join(kept)


def calibration_to_toml(calibration: Calibration) -> str:
    """Tables for the measured values. Anything not measured yet is left out."""
    lines = [CALIBRATION_NOTE]
    for name, axis in (("yaw", calibration.yaw), ("pitch", calibration.pitch)):
        lines.append(f"[calibration.{name}]")
        for key in ("deadzone", "max_rate", "range_deg"):
            if getattr(axis, key) is not None:
                lines.append(f"{key} = {getattr(axis, key)}")
        lines.append(f"curve = {_toml_rows(axis.curve)}")
        lines.append("")
    pulse = calibration.pulse
    lines.append("[calibration.pulse]")
    lines.append(f"registered_ms = {list(pulse.registered_ms)}")
    lines.append(f"missed_ms = {list(pulse.missed_ms)}")
    lines.append(f"trains = {_toml_rows(pulse.trains)}")
    lines.append(f"angles = {_toml_rows(pulse.angles)}")
    if pulse.coasts is not None:
        lines.append(f"coasts = {str(pulse.coasts).lower()}")
    return "\n".join(lines) + "\n"


def _toml_rows(rows: tuple[tuple[float, ...], ...]) -> str:
    return "[" + ", ".join("[" + ", ".join(str(v) for v in row) + "]" for row in rows) + "]"


def _section(data: dict, name: str, cls: type) -> dict:
    section = data.pop(name, {})
    if not isinstance(section, dict):
        raise ConfigError(f"[{name}] must be a section")
    _reject_unknown(section, cls, f"[{name}]")
    return section


def _reject_unknown(values: dict, cls: type, where: str) -> None:
    """A typo would otherwise silently leave the default in place."""
    unknown = set(values) - set(cls.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"Unknown setting in {where}: {', '.join(sorted(unknown))}")


def _validate(config: Config) -> None:
    velocity = config.velocity
    _require_type("invert_y", config.invert_y, bool)
    _require_type("debug", config.debug, bool)
    _require_type("hotkeys.toggle", config.hotkeys.toggle, str)
    _require_type("hotkeys.quit", config.hotkeys.quit, str)
    _require_number("tick_hz", config.tick_hz)
    _require_number("velocity.full_speed_x", velocity.full_speed_x)
    _require_number("velocity.full_speed_y", velocity.full_speed_y)
    _require_number("velocity.smoothing_ms", velocity.smoothing_ms)
    _require_number("velocity.min_deflection", velocity.min_deflection)

    if config.mode not in MODES:
        raise ConfigError(f"mode must be one of {', '.join(MODES)}, not {config.mode!r}")
    if not 60 <= config.tick_hz <= 1000:
        raise ConfigError("tick_hz must be between 60 and 1000")
    if velocity.full_speed_x <= 0 or velocity.full_speed_y <= 0:
        raise ConfigError("velocity.full_speed_x and full_speed_y must be above 0")
    if velocity.smoothing_ms < 0:
        raise ConfigError("velocity.smoothing_ms can't be negative")
    if not 0 <= velocity.min_deflection < 1:
        raise ConfigError("velocity.min_deflection must be at least 0 and below 1")
    for name in BudgetConfig.__dataclass_fields__:
        value = getattr(config.budget, name)
        _require_number(f"budget.{name}", value)
        if value <= 0:
            raise ConfigError(f"budget.{name} must be above 0")


def _require_type(name: str, value: object, expected: type) -> None:
    if not isinstance(value, expected):
        raise ConfigError(f"{name} must be a {expected.__name__}")


def _require_number(name: str, value: object) -> None:
    # bool is a subclass of int, but `tick_hz = true` is a mistake.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a number")
