# MouseCamera3DS

A small Windows tool that lets the mouse control the camera in **Monster Hunter 4 Ultimate** running on the **Azahar** 3DS emulator. It reads raw mouse movement and drives the **right stick of a virtual Xbox 360 controller**. In Azahar, that stick is bound to the 3DS **C-Stick** (New 3DS mode), which MH4U uses to control the camera.

The owner is Peter, on Windows 11 x64. He'll test in-game himself. You can't see the game, so whenever a step needs in-game verification, give him clear instructions and ask what he saw.

## Why this exists (the core idea)

Generic mouse-to-stick remappers (reWASD etc.) map **mouse speed → stick deflection**. MH4U's camera is **rate-based**: holding the stick turns the camera at a *speed*. That mismatch causes drift after you stop the mouse, slow movements lost in the deadzone, and turns that don't line up with how far you moved the mouse.

This tool's main feature is **angle-budget mapping** instead:

1. Convert each mouse delta into a target camera rotation in degrees (`deg = counts × sensitivity`), and add it to a pending yaw/pitch budget.
2. Spend that budget in **timed full-stick pulses**, because calibration showed stick position doesn't set the turn rate. Each pulse and each gap lasts a whole number of game frames, because the game reads the stick once a frame.
3. Use a model of the camera to work out what each frame of stick turns, and subtract that from the budget. Only hold the stick for a frame the budget can pay for in full, so the camera can't overshoot. What's left stays pending. No drift.

Result: moving the mouse a given distance turns the camera by the same angle, up to the game's top turn rate. Faster movement queues only briefly and the excess is dropped, because Peter found a long queue too floaty: he values the camera stopping when his hand stops over keeping every degree of a hard flick.

Also build a plain **velocity mode** (mouse speed → deflection, like reWASD) as a baseline, so Peter can A/B compare the two.

## What we've measured (one calibration run, marked by eye)

The values are in `config.toml`, filled by the calibration tool. In summary:

- **Turn rate:** about 170°/s on yaw. It's essentially the same at stick 0.6, 0.8 and 1.0, so past the threshold the camera has one fixed top speed. Pitch behaves the same way, and a sweep between its limits takes about 2.3 s.
- **Deadzone:** about 0.5–0.56 on both axes.
- **Acceleration:** the camera ramps up over about 164 ms and stops dead on release, but the ramp level fades over about 80 ms, so pressing again quickly starts partway up. A 33 ms pulse turns under 0.6°, and 200 ms turns about 21°. This model was fitted to measured pulses.
- **Raw input:** Windows 11 combines it into about 125 reports/s for background programs, keeping the totals. Most 500 Hz ticks therefore have no counts, so never limit a single tick's speed before smoothing.

## Things we still don't know (measure, don't assume)

- Whether pitch ramps like yaw. Only full sweeps were timed, so its true angle and pulse response are unknown, and its "degrees" are nominal.
- The game's exact frame timing, and how much it dips. A wrong frame rate adds no bias in simulation, but makes typical errors larger.
- How close real turns land to the target. Budget mode is open loop, so model errors can add up.

## Tech stack

- Python 3.11+, Windows only
- **vgamepad** (needs the ViGEmBus driver; the vgamepad installer offers it) for the virtual Xbox 360 pad. ViGEmBus is no longer developed but still works. If it causes problems, flag it rather than silently switching approaches.
- **Raw Input via ctypes** (`RegisterRawInputDevices` with `RIDEV_INPUTSINK` on a hidden message-only window) for mouse deltas. Do **not** use cursor-position polling (pynput etc.): positions clamp at screen edges, and Windows pointer acceleration distorts them.
- `tomllib` to read config; keep dependencies minimal
- `pytest` for tests

## Behaviour requirements

- **Toggle hotkey** (default F8) turns mouse-camera on/off. While on, hide the cursor and lock it (`ClipCursor` to a tiny rect), so clicks and movement don't hit Azahar's touchscreen. While off, release the cursor and centre the stick. Also release the cursor on exit and on crash (`try/finally` + `atexit`).
- **Quit hotkey** (default Ctrl+F8)
- Hotkeys must work while Azahar has focus (global hotkeys / low-level hook).
- Tick loop at ~250–500 Hz with a high-resolution timer (`timeBeginPeriod(1)`, `perf_counter`)
- Options for invert Y, separate X/Y sensitivity, and choice of mode (`budget` / `velocity`)
- A **bind helper** command that slowly sweeps the right stick up/down/left/right on cue, so Peter can bind C-Stick directions in Azahar's controls dialog. Azahar has to see movement to register a binding.
- Console output: active mode, on/off state, and an optional debug line (pending budget, current deflection)

## Calibration tool (`python -m mousecam calibrate`)

Interactive and keypress-driven, with Peter watching the game:

1. **Deadzone:** step right-stick X up from 0 in small increments; Peter presses a key the moment the camera starts moving.
2. **Max yaw rate:** hold full deflection; Peter presses a key each time the camera completes a full 360° (use a landmark). Average several laps.
3. **Response curve:** repeat step 2 at ~4–5 deflection levels (e.g. 0.25, 0.4, 0.6, 0.8) so we can fit or interpolate deflection → rate.
4. **Pulse test:** send short pulses (16/33/50/100 ms); Peter reports which ones register. This tells us the minimum pulse length and whether there's acceleration.
5. Repeat the relevant steps for pitch if the game supports vertical camera control.

Write the results to `config.toml`, and print a summary.

## Suggested layout

```
mousecam/
  __main__.py      # CLI: run | calibrate | bind
  config.py        # load/save config.toml, defaults
  raw_input.py     # Raw Input mouse deltas (thread → queue)
  pad.py           # vgamepad wrapper: set_right_stick(x, y), centre()
  mapper.py        # PURE logic: BudgetMapper, VelocityMapper (no I/O)
  calibrate.py
  hotkeys.py
  cursor.py        # hide/clip/release
tests/
  test_mapper.py   # uses a simulated camera model
config.toml
README.md
```

Keep `mapper.py` free of side effects: deltas + dt + calibration in, stick values out. Test it against a **simulated camera** (threshold, max rate, ramp, 30 fps sampling). Check that N counts of mouse movement produce N × sensitivity degrees of rotation, and that nothing drifts after input stops.

## Milestones

- **M0 – Environment check:** install deps, create the virtual pad, show that it appears in `joy.cpl` and that Azahar can bind its right stick to the C-Stick. Write a short setup section in README (ViGEmBus, Azahar New 3DS mode, C-Stick binding, MH4U in-game camera control option).
- **M1 – Velocity mode end-to-end:** raw input → velocity mapper → pad, plus toggle hotkey and cursor lock. Peter confirms the camera moves in-game.
- **M2 – Calibration tool,** producing a real `config.toml`
- **M3 – Budget mapper** with simulated-camera tests, then in-game test
- **M4 – Tuning & polish:** sensitivity, smoothing of the drain rate, pitch handling, optional PyInstaller exe

Finish each milestone before starting the next, and stop at each in-game check for Peter's feedback.

## Non-goals (v1)

- No modifying Azahar and no reading emulator memory. A closed loop on the real camera angle would be neat, but it's a later idea.
- No keyboard→button remapping. Peter binds movement and buttons directly in Azahar with the keyboard; this tool only handles the camera.
- No GUI beyond the console, at least for v1.
