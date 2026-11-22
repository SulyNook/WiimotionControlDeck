# WiiLinux — WiiDeck + WiiSim (v0.11)

Two Linux programs for a **Wii Remote Plus through a Dolphin Bar (mode 4)**. Pure Python 3 (standard library only,
`tkinter` for the windows), packaged as AppImages in the same style as WiiHot (system `python3`, Steam's `LD_*` variables removed).

| Program | What it does |
|---|---|
| **WiiDeck** | Controls the Steam Deck, **also in Gaming Mode**: IR pointer → mouse, shake → change collection, buttons → virtual Xbox 360 gamepad, **gyro → motion for Switch emulators (DSU)**. Three modes (**Vertical**, **Horizontal**, **Nunchuk**), two built-in profiles (**Menus**, **Games**) plus your own blank profiles, a **Steam-Input-style button editor**, and a **Decky plugin** with a main on/off switch (full stop), restart button and IR toggle. |
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
* **Profile** (`+` and `−` together rotate only through the profiles ticked in **Acceso rápido** — window HOME tab or Decky; new custom profiles start unticked; LED 4 = not Menus): **Menus** — A is a mouse click, for Steam's UI. **Games** — A, B… are Deck buttons.

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
| Shake right / left | **R1 / L1** (right shake moves the collection left) | same | same |
| Shake up / down, Nunchuk shake | nothing (assignable) | same | same |

### Button editor (Steam Input style)

Window → **BOTONES** tab, or Decky → *Editar asignacion de botones*. Pick the profile and mode to edit, tap an input (A, B, 1, 2, +, −, Home, D-pad ×4, Nunchuk stick/C/Z, shake left/right/up/down, Nunchuk shake, IR pointer) and choose what it does:
a **type first** — *Mando* (gamepad buttons, D-pad, stick directions), *Teclado* (about 70 keys: Esc/Enter/arrows/Home/End/PgUp/PgDn/Shift/Ctrl/Alt/Super, A–Z, 0–9, F1–F12, volume and media keys), *Ratón* (clicks, wheel) or *Programa* (change mode/profile, gyro on/off, calibrate, IR on/off, open ··· menu, nothing) — and then the action inside it. In the Decky plugin each input is a collapsible line showing its summary ("A: A + B"); open it to pick *Tipo* and *Botón* for each slot.
**Edits are not applied immediately**: change as many inputs as you like (marked `*`), then press **APLICAR** to save and apply them all at once (*DESCARTAR* drops them). *Restaurar este modo* undoes saved changes (it asks for confirmation).
**Dangerous actions ask for confirmation (v0.11):** delete profile (3 clicks in the window / 2 dialogs in the plugin), restore a mode to factory values (2 clicks / 2 dialogs), restart everything and discard pending changes (1 extra confirmation). In the window the confirmation cancels itself after 4 s. In the window, each input has extra `+` slots to make combos (A + B); the Decky plugin does the same: choose a button and a new "+ Añadir otro botón" slot appears below it (up to 4; "Quitar este botón" removes one, "Nada" in the first slot clears all). Pressing the input presses all the buttons at once.
**+ Añadir perfil** (after the two built-ins, up to 6 custom ones) asks for a name and creates a **copy of the profile you are currently editing** (all modes, saved values only — pending unapplied edits are not copied); it can be selected with the profile dropdown or `+`/`−` on the remote and deleted again. Stored in `~/.config/wiideck/config.json` under `profiles`.
So the Nunchuk's C and Z are now independent buttons you can map to anything.

### Gyro / motion for Switch games

The motion data is served as a **DSU (cemuhook) server on `127.0.0.1:26760` and `127.0.0.1:26761` at the same time** (type either in the emulator; if another program such as SteamDeckGyroDSU already owns 26760, only 26761 is used — the log says which). In a Switch emulator on the Deck
(Ryujinx, Yuzu forks, Cemu, Dolphin…) enable *Motion* → *DSU / cemuhook client* with that address. Axis signs can be flipped in `config.json` (`dsu_invert`) if a game moves the wrong way.
**Drift and weak knocks (v0.11):** *Zona muerta del giro* (default 2°/s; raise it if the emulator cursor creeps) removes the slow circling drift; auto-zero at rest is now easier to trigger. *Ganancia del acelerómetro* multiplies the accelerometer sent to the emulator, and the window/plugin show the *peak acceleration* of the last 2 s so you can see whether the remote registers your shake at all (a hard shake should reach ≥2.5 g). If the peak is high but Mario Odyssey still ignores shakes, raise the gain; if it is low, the remote is not measuring them. **Not verified in a game.**
**Synthetic shake for the emulator (v0.11):** the emulator does not detect "hard movements" itself; the game decides. So WiiDeck can inject a strong, short acceleration swing into the DSU stream: assign a *Programa* action "Sacudida al emulador: arriba/abajo/izquierda/derecha/adelante/atrás" to any input (e.g. the four shake directions of the remote). Tune *Fuerza* (g), *Velocidad del vaivén* and *Vaivenes* and use **Probar sacudida** with the game open. Defaults imitate a Joy-Con shake (5 g, 8 Hz, 2 swings). **Not verified in Mario Odyssey; the right values are found by trying.**
**v0.11 — if Odyssey still ignores the shake:** the synthetic shake now also carries a gyro swing (*Giro que acompaña*, default 700°/s, like a wrist that shakes and rotates), has a **continuous test (5 s)** to watch the effect for as long as you need, and *Copiar el movimiento al pad 1* sends the same data as DSU pad 1 (for games/emulators that read a second sensor, "Motion 2"). Things to check in **Eden** itself (a log from Eden showed: *Handheld* mode and three UDP servers `127.0.0.1:26760`, `<LAN-IP>:26760`, `127.0.0.1:26761`):
1. In handheld mode the game may read the **Handheld** controller, not Player 1: set the *Motion* of **Handheld** (and of Player 1) to the WiiDeck server (`127.0.0.1`, port **26761**, pad 0), or use Player 1 as *Handheld* type.
2. Port 26760 was already taken by another program (probably the Deck's own gyro DSU). If a motion slot points to it, the game gets the Deck's sensor and not the Wii remote. Remove it from Eden's UDP servers (or stop that program) so there is no mix-up.
3. Try *Motion 2* with the mirror option, and a different game mode (docked/handheld).
**Not verified in a game: these are the likeliest causes, not a confirmed diagnosis.**
**How to check it works:** the events log (`~/.local/share/wiideck/logs/wiideck_eventos_*.log`) prints `Servidor DSU en ... puertos ...` at start and, the moment an emulator connects, `Cliente conectado: ...` and `Datos que recibe el emulador: ...`. If you never see "Cliente conectado", the emulator is not reaching the server (wrong port/address, or the emulator's motion option is off); the MOVIMIENTO tab also has the DSU monitor.
**Gyro without MotionPlus:** with the Nunchuk attached this Dolphin Bar gives no MotionPlus data, so the remote only has its accelerometer. WiiDeck now *estimates* pitch and roll from the accelerometer (option *Giro estimado*, on by default). It is much rougher than a real gyro: no yaw (turning around the vertical), and it only works with smooth movements. Real MotionPlus gyro is used in Vertical/Horizontal modes.
*Giroscopio → stick derecho* turns the gyro into the right stick instead, which works in any game (aiming). *Calibrar giroscopio*: hold the remote still for a second.
Making the gyro look like the *Deck's own* sensor to Steam Input is not possible with a virtual device from userspace; DSU + right-stick are the two routes that work today.

### Other notes

* **Shake sensitivity** (MOVIMIENTO tab / Decky): *Fuerza* (0.08–2.5 g, lower catches softer movements), *Cambios de sentido* (1–6; 2 = back and forth) and *Tiempo entre cambios* (0.2–1.2 s, higher accepts slower shaking). Applies to the remote and to the Nunchuk.
* **Shake** is directional (first stroke of the dominant axis decides). If left/right come out swapped, use the axis inversion options in the MOVIMIENTO tab. The cursor freezes while you shake. Sensitivity slider: *Fuerza de la sacudida*.
* **Hold chords** (held about 2 s, `hold_chord_seconds`): **Down + Plus** toggles the IR pointer (also a toggle in the window/plugin); **Home + Plus** opens Steam's ··· menu (QAM). With Decky the plugin opens it; without Decky it falls back to Steam+A on the virtual pad (best effort). Home/Plus/1/2/− wait 0.12 s to tell chords from single presses.
* **Notifications:** with Decky, every mode or profile change (from the remote, the window or the plugin) shows a Steam toast ("Modo: Vertical", "Perfil: Juegos") that disappears by itself (v0.10 asks Steam not to keep it in the notification history; this could not be verified, so there is an on/off switch *Avisos de modo y perfil*).
* **Off means off**: the Decky switch stops everything (remote released, rumble off, virtual devices closed) and remembers it; *Reiniciar WiiDeck* restarts everything keeping profiles and settings. Resuming from sleep is detected and restarts automatically. Rumble now retries its "off" report and has a keepalive, to fix the constant vibration on connect.
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

**Not tested (no hardware / no internet / no Tk here):** the sleep/vibration fix, the hold-chord timing, directional shake signs and the QAM opening on a real Deck, the gyro/DSU fixes (all in code, never run against real hardware), the real Tk windows (code was run against a fake `tkinter`), **the Decky plugin inside a real Decky Loader (the frontend was type-checked but never built or loaded: `dist/` is generated by `sh build.sh decky`)**, whether a Switch emulator takes the DSU motion with the right axis signs, `/dev/uinput` on a real Deck,
whether gamescope/Steam accept the virtual mouse/pad in Gaming Mode, whether L1/R1 switch collections in your Library view, the Dolphin Bar's behaviour with hidraw writes on Linux,
and building the AppImages. If something fails, send `~/.local/share/wiideck/logs/*` (or `~/Documents/WiiSim/Logs/*`).

Run (from `tests/`) `python3 test_deckcore.py`, `test_decky_backend.py`, `test_wiideck.py`, `test_link.py`, `test_e2e.py`, `test_gui_mock.py`, `test_lifecycle.py` to re-check the logic.
