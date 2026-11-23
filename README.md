# WimotionControlDeck

Use a **Wii Remote Plus** (through a **Mayflash Dolphin Bar in mode 4**) as a controller for the **Steam Deck**, in Desktop Mode **and Gaming Mode**:
IR pointer → mouse, buttons → virtual Xbox 360 gamepad, shake → assignable actions, and **gyro → motion for Switch emulators (DSU / cemuhook)**.

Pure Python 3 (standard library only, `tkinter` for the windows). It ships as:

* a **Decky Loader plugin** (recommended for Gaming Mode: Quick Access menu), and
* an **AppImage** with a Tk window (Desktop Mode, or added to Steam as a non-Steam game).

The repo also contains **WiiSim**, a Linux 3D simulator for the remote (orientation from MotionPlus + accelerometer, position from IR, pointer, gestures, Nunchuk, logs).

> **Status:** developed without access to a real Steam Deck session in the loop. See [What is tested](#tested-vs-not-tested) before relying on it.

## Features

* Three modes: **Vertical** (point at the screen), **Horizontal** (held sideways like a NES pad) and **Nunchuk**. Switch with `1 + 2` on the remote.
* Profiles: built-in **Menus** (A = mouse click, for Steam's UI) and **Games** (A, B… are Deck buttons), plus up to 6 custom profiles (a custom profile starts as a copy of the one being edited). `+` and `−` together cycle through the profiles ticked in *Quick access*.
* **Steam-Input-style button editor**: pick an input, then a *type* (Gamepad, Keyboard, Mouse, Program) and an action. Several buttons per input (combos such as `A + B`, up to 4). Edits are applied in batch (**APPLY** / **Discard**).
* **Directional shake** (up/down/left/right) and **Nunchuk shake**, with adjustable strength, direction changes and timing.
* **Hold chords** (about 2 s): `Down + Plus` toggles the IR pointer; `Home + Plus` opens Steam's `···` menu (QAM).
* **Gyro → DSU server** on `127.0.0.1:26760` and `:26761`, **gyro → right stick**, estimated gyro without MotionPlus, dead zone, accelerometer gain, and a **synthetic shake** injected into the DSU stream for games that decide "shake" themselves.
* **Off means off**: the main switch stops everything (remote released, rumble off, virtual devices closed). *Restart* restarts everything keeping profiles and settings. Resuming from sleep is detected and restarts automatically.
* Steam toast notifications on mode/profile changes (Decky).

## 1. One-time setup (Steam Deck, Desktop Mode, Konsole)

```sh
sudo sh install-udev.sh        # udev rules for the Dolphin Bar + /dev/uinput; disables the kernel hid_wiimote driver
```

Unplug and replug the Dolphin Bar (mode 4), then check:

```sh
python3 wimotioncontroldeck/wimotioncontroldeck.py --check   # shows the bar's hidraw ports and whether uinput is usable
```

`--keep-driver` keeps `hid_wiimote`; `--open-uinput` makes `/dev/uinput` world-writable if the session ACL does not work; `--remove` undoes everything.
(The Decky plugin runs as root, so it does not need the udev rules and separates `hid_wiimote` from the remotes by itself.)

## 2. Build

```sh
sh build.sh              # WimotionControlDeck-x86_64.AppImage and WiiSim-x86_64.AppImage (needs internet for appimagetool)
sh build.sh decky        # WimotionControlDeck-decky.zip (needs node, pnpm, zip)
```

Without building, `python3 wimotioncontroldeck/wimotioncontroldeck.py` and `python3 wiisim/wiisim.py` run directly from the repo. The window needs `tkinter` (`python3-tk`); without it the programs fall back to `--nogui`.

## 3. Use it in Gaming Mode

Two ways, **not at the same time** (the second one to start reports "another instance is running"):

**A. Decky plugin (recommended).** Install: Decky → Settings → Developer → *Install plugin from ZIP* → `WimotionControlDeck-decky.zip` (or copy the `WimotionControlDeck` folder to `~/homebrew/plugins/` and `sudo systemctl restart plugin_loader`). Open the Quick Access menu (`···`) and use the **Enable WimotionControlDeck** switch at the top.

**B. AppImage.** Desktop Mode → Steam → *Add a Non-Steam Game* → `WimotionControlDeck-x86_64.AppImage`. Launch it from the Library, press the Steam button and go back Home: it keeps running in the background.

### Default mappings (all editable)

| | Vertical / Nunchuk, *Menus* | Vertical / Nunchuk, *Games* | Horizontal (both profiles) |
|---|---|---|---|
| IR pointer | mouse cursor | mouse cursor | — |
| A | left click | gamepad A | X |
| B (trigger) | gamepad B | R2 | Y |
| 1 / 2 | X / Y | X / Y | **B / A** |
| D-pad | D-pad | D-pad | **left stick**, rotated 90° (Up→left, Right→up, Down→right, Left→down) |
| + / − / Home | Start / Select / Guide | same | same |
| Nunchuk stick / C / Z | left stick / **L1 / L2** | same | — |
| Shake right / left | **R1 / L1** | same | same |
| Shake up / down, Nunchuk shake | nothing (assignable) | same | same |

### Button editor

Window → **BUTTONS** tab, or Decky → *Edit button mapping*. Pick the profile and mode to edit, tap an input (A, B, 1, 2, +, −, Home, D-pad ×4, Nunchuk stick/C/Z, shake left/right/up/down, Nunchuk shake, IR pointer) and choose a **type** — *Gamepad* (buttons, D-pad, stick directions), *Keyboard* (about 70 keys), *Mouse* (clicks, wheel) or *Program* (change mode/profile, gyro on/off, calibrate, IR on/off, open `···` menu, synthetic shake, nothing) — then the action inside it.

Edits are not applied immediately: change as many inputs as you like (marked `*`), then press **APPLY** (or *Discard*). *Restore this mode* returns a mode to factory values. Dangerous actions ask for confirmation (delete profile, restore a mode, restart and discard pending edits). Profiles are stored in `~/.config/wimotioncontroldeck/config.json`.

### Gyro / motion for Switch emulators

Motion is served as a **DSU (cemuhook) server on `127.0.0.1:26760` and `127.0.0.1:26761` at the same time**. In the emulator (Ryujinx, Yuzu forks, Eden, Cemu, Dolphin…) enable *Motion* → *DSU / cemuhook client* with that address. Axis signs can be flipped in `config.json` (`dsu_invert`).

* **Drift and weak knocks:** *Gyro dead zone* (default 2°/s) removes slow drift. *Accelerometer gain* multiplies the accelerometer sent to the emulator; the window/plugin show the *peak acceleration* of the last 2 s so you can see whether the remote registers a shake at all (a hard shake should reach ≥ 2.5 g).
* **Synthetic shake:** the emulator does not detect "hard movements"; the game decides. WimotionControlDeck can inject a short, strong acceleration (and gyro) swing into the DSU stream: assign a *Program* action "Shake to emulator: up/down/left/right/forward/back" to any input. Tune *Strength*, *Shake rate*, *Number of shake cycles* and *Accompanying gyro*, and use **Test shake** (or the 5 s continuous test) with the game open. Defaults imitate a Joy-Con shake (5 g, 8 Hz, 2 cycles). *Copy motion to DSU pad 1* sends the same data as pad 1 for games that read a second sensor.
* **Eden tips:** in handheld mode the game may read the *Handheld* controller, not Player 1 — set *Motion* of both to this server (`127.0.0.1`, port **26761**, pad 0). Port 26760 is normally used by the Deck's own gyro DSU (e.g. SteamDeckGyroDSU); if a motion slot points to it, the game gets the Deck's sensor, not the remote.
* **"Deck mode":** WimotionControlDeck always tries to listen on 26760 and 26761. If 26760 is taken it shows **who** has it, retries every 5 s and takes it as soon as it is free. **Use port 26760 (like the Deck)** (two confirmations) stops that program with SIGTERM — only if its name or command contains "gyro" or "dsu"; other programs are never touched. After that, an existing 26760 binding receives the Wii remote instead of the Deck's sensor.
* **Gyro without MotionPlus:** with the Nunchuk attached the Dolphin Bar gives no MotionPlus data, so pitch and roll are *estimated* from the accelerometer (much rougher: no yaw). Real MotionPlus gyro is used in Vertical/Horizontal modes.
* **Gyro → right stick** turns the gyro into the right stick instead (aiming in any game). *Calibrate gyro*: hold the remote still for a second.
* Making the gyro look like the Deck's own sensor to Steam Input is not possible from userspace with a virtual device; DSU and right-stick are the two routes that work.
* **Checking it works:** the events log (`~/.local/share/wimotioncontroldeck/logs/`) prints the DSU server ports at start and, when an emulator connects, `Client connected: …` and `Data the emulator receives: …`. If you never see "Client connected", the emulator is not reaching the server (wrong port/address, or its motion option is off). The MOTION tab also has a DSU monitor.

### Other notes

* **Shake sensitivity** (MOTION tab / Decky): *Shake strength* (0.08–2.5 g, lower catches softer movements), *Direction changes* (1–6; 2 = back and forth) and *Time between changes* (0.2–1.2 s). Applies to the remote and the Nunchuk. Shake is directional (the first stroke of the dominant axis decides); if left/right come out swapped, use the axis inversion options. The cursor freezes while you shake.
* The pointer is a relative "air mouse" driven by the IR angle (45 px/degree by default, 1-euro smoothing); use *Invert X/Y* if it goes the wrong way.
* The Nunchuk is read as a normal extension (MotionPlus off), because the Dolphin Bar did not deliver Nunchuk frames in MotionPlus pass-through mode.
* While WimotionControlDeck is switched **off**, the remote does nothing, chords included: turn it back on from the window or Decky.

## 4. WiiSim

`./WiiSim-x86_64.AppImage` — drag = orbit, wheel = zoom, **C** calibrate gyro, **R**/Home centre yaw, **F2** = write a line in the log. Logs: `~/Documents/WiiSim/Logs` (events + CSV). *Nunchuk direct* switches the remote to Nunchuk-direct mode (no gyro). Not ported yet: accelerometer 6-face autocalibration and the Nunchuk wizard.

## Tested vs not tested

**Automated tests** (`tests/`, no hardware needed): the core (modes, profiles, custom bindings, horizontal D-pad → stick, Nunchuk C/Z, on/off switch, gyro → stick, DSU protocol incl. CRC and a client round-trip), the Decky backend against a fake `decky` module, the window code against a fake `tkinter`, the hidraw layer against a fake remote, report decoding against real frames, the simulator core replayed over a real session, and the Decky frontend **type-checked only** against stub typings.

```sh
cd tests && for t in test_deckcore test_decky_backend test_wimotioncontroldeck test_link test_e2e test_gui_mock test_lifecycle; do python3 $t.py | tail -1; done
```

**Not tested:** anything on real hardware or real software — the sleep/rumble fixes, hold-chord timing, directional shake signs, QAM opening on a Deck, gyro/DSU behaviour in a real emulator (axis signs, shake detection in games), `/dev/uinput` on a Deck, whether gamescope/Steam accept the virtual mouse/pad in Gaming Mode, the Dolphin Bar's behaviour with hidraw writes on Linux, building the AppImages, and **the Decky plugin inside a real Decky Loader** (the frontend was never built or loaded; `dist/` is produced by `sh build.sh decky`). If something fails, please open an issue with the logs from `~/.local/share/wimotioncontroldeck/logs/*` (or `~/Documents/WiiSim/Logs/*`).

## License

GPL-3.0-or-later (see `decky/WimotionControlDeck/package.json`). Add a `LICENSE` file before publishing.
