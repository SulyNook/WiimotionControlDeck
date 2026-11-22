# WiiLinux — WiiDeck + WiiSim (v0.2)

Two Linux programs for a **Wii Remote Plus through a Dolphin Bar (mode 4)**. Pure Python 3 (standard library only,
`tkinter` for the windows), packaged as AppImages in the same style as WiiHot (system `python3`, Steam's `LD_*` variables removed).

| Program | What it does |
|---|---|
| **WiiDeck** | Controls the Steam Deck, **also in Gaming Mode**: IR pointer → mouse, shake → change collection, buttons → virtual Xbox 360 gamepad, **gyro → motion for Switch emulators (DSU)**. Three modes (**Vertical**, **Horizontal**, **Nunchuk**), two profiles (**Menus**, **Games**), a **Steam-Input-style button editor**, and a **Decky plugin** with a main on/off switch. |
| **WiiSim** | Linux version of the 3D simulator (WiiMotionSim v0.5 for Windows): orientation (MotionPlus + accelerometer), position (IR + arm arc), IR pointer, gestures, Nunchuk (direct mode), logs with manual notes. |

## 1. One-time setup (Steam Deck, Desktop Mode, Konsole)

```sh
sudo sh install-udev.sh        # udev rules for the Dolphin Bar + /dev/uinput, and disables the kernel hid_wiimote driver
```
Unplug/replug the Dolphin Bar (in mode 4, as you already use it) and check:
```sh
python3 wiideck/wiideck.py --check      # shows the hidraw ports of the bar and whether uinput is usable
```
`--keep-driver` keeps `hid_wiimote`; `--open-uinput` makes `/dev/uinput` world-writable if the session ACL does not work; `--remove` undoes everything.

## 2. Build the AppImages (needs internet, once)

```sh
sh build.sh              # WiiDeck-x86_64.AppImage and WiiSim-x86_64.AppImage
```
Without building: `python3 wiideck/wiideck.py` / `python3 wiisim/wiisim.py` work directly from this folder.
The window needs `tkinter` (`python3-tk`); without it both programs fall back to `--nogui`.

## 3. Use WiiDeck in Gaming Mode

Two ways, **not at the same time** (the second one to start shows "another instance is running"):

**A. Decky plugin (recommended)** — quick-access menu (`...` button), main **Activar WiiDeck** switch on top.
```sh
sh build.sh decky        # needs node + pnpm + internet; makes WiiDeck-decky.zip
```
Decky → Settings → Developer → *Install plugin from ZIP*. (Or copy the `WiiDeck` folder from the zip to `~/homebrew/plugins/` and `sudo systemctl restart plugin_loader`.)
The plugin's backend runs as root, so it does not even need the udev rules, and it separates `hid_wiimote` from the remotes by itself.

**B. AppImage** — Desktop Mode → Steam → *Games → Add a Non-Steam Game* → *Browse* → `WiiDeck-x86_64.AppImage`. Launch it from the Library; press the **Steam button** and go back to Home: it keeps running in the background.

### Modes and profiles

* **Mode** (`1 + 2` on the remote): Vertical (pointing at the screen), Horizontal (held sideways like a NES pad, 1/2 on the right), Nunchuk.
* **Profile** (`+` and `−` together; LED 4 = Games): **Menus** — A is a mouse click, for Steam's UI. **Games** — A, B… are Deck buttons.

Defaults (all of it can be changed in the editor):

| | Vertical / Nunchuk, *Menus* | Vertical / Nunchuk, *Games* | Horizontal (both profiles) |
|---|---|---|---|
| IR pointer | mouse cursor | mouse cursor | — |
| A | left click | gamepad A | X |
| B (trigger) | gamepad B | R2 | Y |
| 1 / 2 | X / Y | X / Y | **B / A** |
| D-pad | D-pad | D-pad | **left stick**, rotated 90° (Up→left, Right→up, Down→right, Left→down). It is no longer a D-pad. |
| + / − / Home | Start / Select / Guide | same | same |
| Nunchuk stick / C / Z | left stick / **L1 / L2** | same | — |
| Shake / shake + B | R1 / L1 | same | same |

### Button editor (Steam Input style)

Window → **BOTONES** tab, or Decky → *Editar asignacion de botones*. Pick the profile and mode to edit, tap an input (A, B, 1, 2, +, −, Home, D-pad ×4, Nunchuk stick/C/Z, shake, shake+B, IR pointer) and choose what it does:
gamepad buttons (A B X Y L1 R1 L2 R2 L3 R3 Menu View Steam), D-pad, left/right stick directions, mouse (clicks, wheel), keyboard (Esc, Enter, Space, Tab, arrows…), or program actions (change mode/profile, gyro on/off, calibrate, WiiDeck on/off).
Changed entries are marked `*`; *Restaurar este modo* undoes them. Stored in `~/.config/wiideck/config.json` under `profiles`.
So the Nunchuk's C and Z are now independent buttons you can map to anything.

### Gyro / motion for Switch games

The MotionPlus gyro (+ accelerometer) is served as a **DSU (cemuhook) motion server on `127.0.0.1:26760`**. In a Switch emulator on the Deck
(Ryujinx, Yuzu forks, Cemu, Dolphin…) enable *Motion* → *DSU / cemuhook client* with that address. Axis signs can be flipped in `config.json` (`dsu_invert`) if a game moves the wrong way.
*Giroscopio → stick derecho* turns the gyro into the right stick instead, which works in any game (aiming). *Calibrar giroscopio*: hold the remote still for a second.
**Limit:** with this Dolphin Bar the Nunchuk and the gyro cannot be used together (Nunchuk mode switches the gyro off).
Making the gyro look like the *Deck's own* sensor to Steam Input is not possible with a virtual device from userspace; DSU + right-stick are the two routes that work today.

### Other notes

* **Shake** → R1 (next collection); shake + B → L1. The cursor freezes while you shake. Sensitivity slider: *Fuerza de la sacudida*.
* The pointer is a relative "air mouse" driven by the IR angle (45 px/degree by default, 1-euro smoothing); *Invertir X/Y* if it goes the wrong way.
* The Nunchuk is read as a normal extension (MotionPlus off) because your Dolphin Bar never delivered Nunchuk frames in MotionPlus pass-through mode.
* While WiiDeck is switched **off** the remote does nothing, including its chords: turn it back on from the window or Decky.

## 4. WiiSim

`./WiiSim-x86_64.AppImage` — same controls as the Windows one: drag = orbit, wheel = zoom, **C** calibrate gyro, **R**/Home centre yaw,
**F2** = write a line in the log (`// Prueba de nunchuck Inicio` / `Fin` buttons). Logs: `~/Documents/WiiSim/Logs` (events + CSV, same idea as Windows).
Options: *Nunchuk directo* switches the remote to Nunchuk-direct mode (no gyro). The experimental *auto-zero at stable rest* is off to match v0.5 behaviour.
Not ported yet: accelerometer 6-face autocalibration and the Nunchuk wizard (direct mode uses the standard bits).

## 5. What was tested here, and what was not

Tested (automated, in `tests/`): the WiiDeck core (modes, profiles, custom bindings, horizontal D-pad → stick, Nunchuk C/Z, on/off switch, gyro → stick, DSU protocol incl. CRC and a client round-trip), the Decky backend against a fake `decky` module, the window code against a fake `tkinter` (including a simulated "tap A → choose Enter" in the editor), the Decky frontend type-checked against stub typings; report decoding against real frames from your v0.5 logs; IR pointer vs the C# pointer (correlation 0.99);
the simulator core replayed over a real session (pitch/roll within ~2° of the C# values); button maps, chord 1+2, shake detection, Nunchuk stick/C/Z,
uinput struct sizes; the hidraw layer end to end against a fake remote (exact report sizes, init order); the 3D renderer (images checked by eye).

**Not tested (no hardware / no internet / no Tk here):** the real Tk windows (code was run against a fake `tkinter`), **the Decky plugin inside a real Decky Loader (the frontend was type-checked but never built or loaded: `dist/` is generated by `sh build.sh decky`)**, whether a Switch emulator takes the DSU motion with the right axis signs, `/dev/uinput` on a real Deck,
whether gamescope/Steam accept the virtual mouse/pad in Gaming Mode, whether L1/R1 switch collections in your Library view, the Dolphin Bar's behaviour with hidraw writes on Linux,
and building the AppImages. If something fails, send `~/.local/share/wiideck/logs/*` (or `~/Documents/WiiSim/Logs/*`).

Run (from `tests/`) `python3 test_deckcore.py`, `test_decky_backend.py`, `test_wiideck.py`, `test_link.py`, `test_e2e.py`, `test_gui_mock.py` to re-check the logic.
