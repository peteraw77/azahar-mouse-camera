"""Command line: python -m mousecam run | calibrate | bind. With no command, it runs."""

from __future__ import annotations

import argparse
import sys
import traceback
from dataclasses import replace
from pathlib import Path

from mousecam.config import MODES, ConfigError, default_config_path, load_config
from mousecam.hotkeys import HotkeyError
from mousecam.pad import PadError
from mousecam.win32 import Win32Error, claim_single_instance, started_by_double_click

STAGE_NAMES = ("deadzone", "yaw", "curve", "pulse", "angle", "pitch")


def console_main() -> int:
    """main() for the packaged exe. A double-clicked window closes as soon as the
    program exits, so an error has to wait, or nobody would get to read it."""
    try:
        code = main()
    except SystemExit as exc:  # argparse, for --help and for bad arguments
        code = exc.code if isinstance(exc.code, int) else 0 if exc.code is None else 1
    except Exception:
        traceback.print_exc()
        code = 1
    if code and started_by_double_click():
        try:
            input("\nPress Enter to close.")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


def main() -> int:
    parser = argparse.ArgumentParser(prog="mousecam", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the mouse camera")
    run.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        metavar="FILE",
        help="settings file (default: config.toml)",
    )
    run.add_argument(
        "--mode",
        choices=MODES,
        help="use this mode instead of the one in the settings file, for comparing them",
    )
    calibrate = commands.add_parser("calibrate", help="measure the game's camera and save the results")
    calibrate.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        metavar="FILE",
        help="settings file to read and save to (default: config.toml)",
    )
    calibrate.add_argument(
        "--only",
        nargs="+",
        choices=STAGE_NAMES,
        default=list(STAGE_NAMES),
        metavar="STAGE",
        help=f"run just these stages, keeping other saved results ({', '.join(STAGE_NAMES)})",
    )
    bind = commands.add_parser("bind", help="move the right stick on cue, for binding in Azahar")
    bind.add_argument(
        "--prep",
        type=float,
        default=6.0,
        metavar="SECONDS",
        help="time to switch to Azahar before the beeps (default: 6)",
    )
    bind.add_argument(
        "--config",
        type=Path,
        default=default_config_path(),
        metavar="FILE",
        help="settings file, for the mouse button mapping (default: config.toml)",
    )
    args = parser.parse_args(sys.argv[1:] or ["run"])

    try:
        # Two copies would mean two virtual pads, and Azahar only listens to one.
        if not claim_single_instance("MouseCamera3DS"):
            print("MouseCamera3DS is already running in another window. Quit that one first.", file=sys.stderr)
            return 1
        if args.command == "bind":
            from mousecam.bind import run_bind

            run_bind(args.prep, load_config(args.config).buttons.mapping())
        elif args.command == "calibrate":
            from mousecam.calibrate import run_calibration

            # Keep the stages in their proper order, however they were typed.
            stages = [name for name in STAGE_NAMES if name in args.only]
            run_calibration(load_config(args.config), args.config, stages)
        else:
            from mousecam.app import run_app

            config = load_config(args.config)
            if args.mode:
                config = replace(config, mode=args.mode)
            run_app(config)
    except (ConfigError, HotkeyError, PadError, Win32Error) as exc:
        print(exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # The stick and cursor have been released by now, on the way out of each command.
        print("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
