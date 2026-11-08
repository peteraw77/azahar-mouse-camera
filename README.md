# Azahar Mouse Camera

Controls the camera in Monster Hunter 4 Ultimate on the Azahar 3DS emulator with the mouse. It reads raw mouse movement and drives the right stick of a virtual Xbox 360 controller, which Azahar passes to the game as the 3DS C-Stick.

Generic mouse-to-stick remappers turn mouse speed into stick position, which makes the camera drift after you stop and lose slow movements. This tool's budget mode works from mouse distance instead: each movement becomes a target angle, spent in short timed pulses of the stick, and the camera stops when the turn is done.

It runs on Windows only, and has only been tested with MH4U.

## Using the exe

If you have the packaged build, you don't need Python. Unzip the folder anywhere, and keep everything in it together. Where this README says `python -m mousecam`, use these instead:

| To do this | Use |
| --- | --- |
| Run the mouse camera | Double-click `azahar-mouse-camera.exe` |
| Bind controls (`bind`) | Double-click `bind.bat` |
| Calibrate (`calibrate`) | Double-click `calibrate.bat` |
| Pass options, such as `--mode velocity` | Run `azahar-mouse-camera.exe` from a terminal with the same options |

Settings are in `config.toml`, next to the exe.

You still need the ViGEmBus driver and the Azahar setup below. If the driver is missing, its installer is in the folder, at `_internal\vgamepad\win\vigem\install\x64\ViGEmBusSetup_x64.msi`.

The exe isn't code-signed, so Windows SmartScreen may warn about it, and antivirus software may flag it. If SmartScreen blocks it, click **More info**, then **Run anyway**.

## Setup

If you're using the exe, skip step 2.

### 1. ViGEmBus driver

The virtual controller needs the ViGEmBus driver. To check whether you already have it, run this in PowerShell and look for `Running`:

```powershell
Get-Service ViGEmBus
```

If it's missing, installing vgamepad in the next step opens the driver installer, as long as you leave out the `VGAMEPAD_SKIP_VIGEMBUS_INSTALL` line. ViGEmBus is no longer developed, but it still works.

### 2. Python environment

Needs Python 3.11 or newer. From the project folder, in PowerShell:

```powershell
python -m venv .venv
$env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL = 'true'   # leave out if ViGEmBus is missing
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Check the virtual pad

```powershell
.\.venv\Scripts\python.exe -m mousecam bind
```

Leave that running, because the pad only exists while it does. Then press Win+R and run `joy.cpl`. An Xbox 360 controller should be listed. Open its **Properties**, go back to the bind window and press `r`, then click back on the Properties window before the beeps finish, because it only updates while it has focus. After the beeps, the X Rotation readout should move.

### 4. Azahar: New 3DS mode

The C-Stick is a New 3DS control. With no game running, open **Emulation > Configure > System** and turn on New 3DS mode.

Use in-game saves across this switch, because save states made in the old mode may not load in the new one.

### 5. Azahar: bind the C-Stick

Use **Set Analog Stick**. Don't use the separate Up/Down/Left/Right buttons in the C-Stick group, because those are digital and every deflection becomes the same fixed value.

1. Start `python -m mousecam bind` before opening the controls dialog, or restart Azahar if the pad doesn't show up.
2. Open **Emulation > Configure > Controls** and pick your controller profile.
3. In the bind window, press `a`. You then have 6 seconds, followed by two beeps. (`--prep 10` gives you 10 seconds.)
4. In Azahar, click **Set Analog Stick** in the C-Stick group. A message appears.
5. Click **OK** on the first beep. Don't click it after the second beep, because the stick starts moving right after that.
6. The bind window moves X and then Y, and Azahar fills in the binding.
7. Set the C-Stick **Deadzone** slider to **0%**. Otherwise Azahar's own deadzone sits on top of the game's and warps the low end of the stick.

Unplug other controllers while binding, since Azahar takes the first axis that moves on any device.

### 6. MH4U: camera setting

Start a quest, or go anywhere you can move the camera. In the bind window, press `r`, `l`, `u` and `d` in turn, and switch back to the game before the beeps finish. The camera should turn for each one.

If it doesn't, look through the in-game options for a camera control setting.

### 7. Optional: mouse buttons

While the camera is on, mouse buttons can press buttons on the virtual pad, which you then bind to game buttons in Azahar. `config.toml` sets which pad button each one presses. Keep your other controls bound however you like, because Azahar lets one profile mix keyboard, controllers and the virtual pad.

Bind them one at a time:

1. Start `python -m mousecam bind`. Its menu lists a number key for each mouse button.
2. In **Emulation > Configure > Controls**, find the game button you want. Then press that number in the bind window. You have 6 seconds, followed by two beeps.
3. Click the game button in Azahar on the first beep. The bind window presses the pad button right after the second beep, and Azahar fills in the binding.

These bindings only work while the tool is running, since that's when the virtual pad exists.

## Using the mouse camera

Quit the bind helper first with `q`, because only one copy of the tool can run at a time. Then, from the project folder:

```powershell
.\.venv\Scripts\python.exe -m mousecam run
```

It takes a few seconds to start. Wait for `Mouse camera: OFF`, then click into Azahar.

| Key | Action |
| --- | --- |
| F8 | Turn the mouse camera on or off |
| Ctrl+F8 | Quit |

While the camera is on, the cursor is hidden and locked, and clicks don't reach Azahar's touchscreen: they press pad buttons instead, if you've bound any. Keyboard input still goes to Azahar. Turning it off or quitting frees the cursor, centres the stick and releases the buttons, and clicks work as normal again, including on the touchscreen.

There are two modes. Set one with `mode` in `config.toml`, or try one for a single run:

```powershell
.\.venv\Scripts\python.exe -m mousecam run --mode budget
.\.venv\Scripts\python.exe -m mousecam run --mode velocity
```

- **`budget`:** moving the mouse a given distance turns the camera a set angle, and the camera stops when the turn is done. It needs calibration results. The game limits how fast the camera can turn, so that only holds up to its top speed: movement beyond that queues for a moment (`max_carry_ms`), and then the excess is dropped.
- **`velocity`:** mouse speed sets stick position, like generic remappers. It's a baseline for comparison.

F7, F8 and F9 are also Azahar shortcuts (custom textures, rotate screens, swap screens). The tool captures F8 only during `run`, and F7 and F9 only during `calibrate`, and not during the first few seconds of startup. Pressed at other times, they reach Azahar. If you don't use those shortcuts, clear them under **Emulation > Configure**.

If the tool is force-closed (for example from Task Manager), it can't clean up and the cursor may stay locked. Alt+Tab to another window should free it.

## Calibration

This measures how the game's camera really responds, and saves the results to `config.toml` without touching your other settings. Budget mode needs these numbers.

The `config.toml` in this repository already holds one set of results and sensitivities, tuned on one PC and mouse. They're a starting point, so adjust the sensitivities to suit your mouse, and recalibrate if turns land noticeably off.

Load a game somewhere you can stand still and look around, and pick a landmark that passes your character as the camera turns. Keep the tool's window visible on another monitor and keep Azahar focused. Then:

```powershell
.\.venv\Scripts\python.exe -m mousecam calibrate
```

The keys work from inside the game, and a beep means a new instruction.

| Key | Action |
| --- | --- |
| F9 | Mark / yes |
| F7 | Done / no |
| Ctrl+F8 | Stop early |

If a press doesn't seem to register, press it again.

The whole run takes about 10 minutes, and results are saved after each stage. A stage stopped partway isn't saved. To redo or finish part of it, name the stages, in any combination:

```powershell
.\.venv\Scripts\python.exe -m mousecam calibrate --only curve pulse
```

| Stage | What it measures |
| --- | --- |
| `deadzone` | Smallest stick deflection that turns the camera, each way |
| `yaw` | Turn rate at full stick, and whether the camera coasts after release |
| `curve` | Turn rate at lower deflections |
| `pulse` | Which short pulses register, and whether pulsing the stick loses rotation |
| `angle` | How many degrees each pulse length turns the camera |
| `pitch` | Deadzone and rates for vertical movement, timed between the camera's limits |

Run them in this order the first time, because later stages use earlier results. Pitch values use a nominal 90 degree range, since the true angle can't be measured by eye.

## Settings

Settings are in [config.toml](config.toml). Restart the tool after changing them.

| Setting | What it does |
| --- | --- |
| `velocity.full_speed_x`, `full_speed_y` | Mouse speed that gives full stick. Lower is more sensitive. |
| `velocity.smoothing_ms` | Higher is smoother, but the camera lags more. |
| `velocity.min_deflection` | Smallest stick value sent. Raise it if slow movements get lost. |
| `invert_y` | Flips the vertical camera direction. |
| `debug` | Prints a live line with the stick deflection and any pending turn. |
| `budget.sensitivity_x`, `sensitivity_y` | Degrees of camera turn per mouse count. Higher is faster. |
| `budget.ramp_ms`, `fade_ms` | How the camera speeds up, fitted to measurements. Change these if turns land consistently short or long. |
| `budget.frame_ms` | How often the game reads the stick. |
| `budget.max_carry_ms` | The longest the camera keeps turning after the mouse stops. Lower is snappier, but fast flicks turn less than the distance moved, because the excess is dropped. |
| `buttons.left`, `right`, `middle`, `x1`, `x2` | Which pad button each mouse button presses: `a`, `b`, `x`, `y`, `lb`, `rb`, `lt`, `rt`, `back`, `start`, `ls` or `rs`, or `""` for none. `x1` and `x2` are the side buttons. If you change one, bind the new pad button in Azahar. |
| `buttons.min_state_ms` | The shortest press or release, so the game can't miss a quick click. |

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Building the exe

This puts the exe folder and a zip of it in `dist`. The current `config.toml` is copied in as its default settings.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

## License

Public domain, under [the Unlicense](LICENSE).
