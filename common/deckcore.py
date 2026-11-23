#!/usr/bin/env python3
"""
deckcore - core of WimotionControlDeck (no window): controller, button profiles, virtual devices (uinput),
gyro -> DSU (cemuhook) server for emulators, and the service that ties it all together.
Used by the window (wimotioncontroldeck.py) and the Decky plugin (decky/WimotionControlDeck/main.py).
"""
import fcntl
import json
import math
import os
import random
import select
import socket
import struct
import threading
import time
import zlib
from collections import deque

import wiilink as wl

APP_NAME = "WimotionControlDeck"
VERSION = "0.13"
MODES = ("vertical", "horizontal", "nunchuk")
MODE_TITLES = {"vertical": "Vertical", "horizontal": "Horizontal", "nunchuk": "Nunchuk"}
MODE_LEDS = {"vertical": 0b0001, "horizontal": 0b0010, "nunchuk": 0b0100}
BUILTIN_PROFILES = ("menus", "juego")
PROFILES = BUILTIN_PROFILES          # factory profiles only; including the user's: profile_ids(cfg)
PROFILE_TITLES = {"menus": "Steam Menus", "juego": "Games"}
MAX_CUSTOM_PROFILES = 6
MAX_COMBO = 4                        # buttons that can be assigned at once to one input (A + B + ...)
SHAKE_INPUTS = ("ShakeLeft", "ShakeRight", "ShakeUp", "ShakeDown")

# ----------------------------------------------------------------------------- paths
CONFIG_DIR = os.path.expanduser("~/.config/wimotioncontroldeck")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_DIR = os.path.expanduser("~/.local/share/wimotioncontroldeck/logs")


HOME = os.path.expanduser("~")


def configure_paths(home):
    """For the Decky plugin: the backend runs as root, but the configuration is the user's."""
    global CONFIG_DIR, CONFIG_PATH, LOG_DIR, HOME
    HOME = home
    CONFIG_DIR = os.path.join(home, ".config/wimotioncontroldeck")
    CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
    LOG_DIR = os.path.join(home, ".local/share/wimotioncontroldeck/logs")


# ----------------------------------------------------------------------------- actions and profiles
INPUTS = [
    ("Pointer", "IR pointer"), ("A", "Remote: A"), ("B", "Remote: B (trigger)"), ("One", "Remote: 1"), ("Two", "Remote: 2"),
    ("Plus", "Remote: +"), ("Minus", "Remote: -"), ("Home", "Remote: Home"),
    ("Up", "D-pad up"), ("Down", "D-pad down"), ("Left", "D-pad left"), ("Right", "D-pad right"),
    ("NunC", "Nunchuk: C"), ("NunZ", "Nunchuk: Z"), ("NunStick", "Nunchuk: stick"), ("NunShake", "Nunchuk: shake"),
    ("ShakeLeft", "Shake left"), ("ShakeRight", "Shake right"),
    ("ShakeUp", "Shake up"), ("ShakeDown", "Shake down"),
]
INPUT_LABELS = dict(INPUTS)

ACTION_GROUPS = [
    ("Buttons", [("pad:A", "A"), ("pad:B", "B"), ("pad:X", "X"), ("pad:Y", "Y"), ("pad:TL", "L1"), ("pad:TR", "R1"),
                 ("trig:L2", "L2"), ("trig:R2", "R2"), ("pad:THUMBL", "L3"), ("pad:THUMBR", "R3"),
                 ("pad:START", "Menu"), ("pad:SELECT", "View"), ("pad:MODE", "Steam")]),
    ("D-pad", [("hat:up", "D-pad up"), ("hat:down", "D-pad down"), ("hat:left", "D-pad left"), ("hat:right", "D-pad right")]),
    ("Left stick", [("lstick:up", "Left stick up"), ("lstick:down", "Left stick down"),
                    ("lstick:left", "Left stick left"), ("lstick:right", "Left stick right")]),
    ("Right stick", [("rstick:up", "Right stick up"), ("rstick:down", "Right stick down"),
                     ("rstick:left", "Right stick left"), ("rstick:right", "Right stick right")]),
    ("Mouse", [("mouse:LEFT", "Left click"), ("mouse:RIGHT", "Right click"), ("mouse:MIDDLE", "Middle click"),
               ("wheel:up", "Wheel up"), ("wheel:down", "Wheel down")]),
    ("Keyboard: special", [("key:ESC", "Esc"), ("key:ENTER", "Enter"), ("key:SPACE", "Space"), ("key:TAB", "Tab"), ("key:BACKSPACE", "Backspace"),
                             ("key:UP", "Up arrow"), ("key:DOWN", "Down arrow"), ("key:LEFT", "Left arrow"), ("key:RIGHT", "Right arrow"),
                             ("key:HOME", "Home"), ("key:END", "End"), ("key:PAGEUP", "Page Up"), ("key:PAGEDOWN", "Page Down"),
                             ("key:INSERT", "Insert"), ("key:DELETE", "Delete"),
                             ("key:LSHIFT", "Shift"), ("key:LCTRL", "Ctrl"), ("key:LALT", "Alt"), ("key:LMETA", "Windows/Super key")]),
    ("Keyboard: letters", [("key:" + c, c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]),
    ("Keyboard: numbers", [("key:" + c, c) for c in "1234567890"]),
    ("Keyboard: F1-F12", [("key:F%d" % i, "F%d" % i) for i in range(1, 13)]),
    ("Keyboard: other", [("key:MINUS", "-"), ("key:EQUAL", "="), ("key:COMMA", ","), ("key:DOT", "."), ("key:SLASH", "/"),
                        ("key:VOLUMEUP", "Volumen +"), ("key:VOLUMEDOWN", "Volumen -"), ("key:MUTE", "Mute"),
                        ("key:PLAYPAUSE", "Play/Pausa"), ("key:NEXTSONG", "Next"), ("key:PREVSONG", "Previous")]),
    ("Program", [("app:cycle_mode", "Switch mode"), ("app:toggle_profile", "Switch profile"),
                 ("app:toggle_gyro", "Gyro on/off"), ("app:calibrate", "Calibrate gyro"),
                 ("app:eden_shake_up", "Shake to emulator: up"), ("app:eden_shake_down", "Shake to emulator: down"),
                 ("app:eden_shake_left", "Shake to emulator: left"), ("app:eden_shake_right", "Shake to emulator: right"),
                 ("app:eden_shake_forward", "Shake to emulator: forward"), ("app:eden_shake_back", "Shake to emulator: back"),
                 ("app:toggle_enabled", "WimotionControlDeck on/off"), ("app:toggle_pointer", "IR pointer on/off"),
                 ("app:open_qam", "Open ... menu (QAM)"), ("none", "None")]),
]
# Editor pre-layer: first pick the type (Gamepad / Keyboard / Mouse / Program), then the action within it
CATEGORIES = [
    ("Gamepad", ["Buttons", "D-pad", "Left stick", "Right stick"]),
    ("Keyboard", ["Keyboard: special", "Keyboard: letters", "Keyboard: numbers", "Keyboard: F1-F12", "Keyboard: other"]),
    ("Mouse", ["Mouse"]),
    ("Program", ["Program"]),
]


def category_of(action_id):
    """Type an action belongs to ('pad:A' -> 'Gamepad'); 'none' and unknown actions -> 'Program'."""
    for cat, groups in CATEGORIES:
        for g, items in ACTION_GROUPS:
            if g in groups and any(i == action_id for i, _ in items):
                return cat
    return "Program"


ACTION_LABELS = {aid: label for _, items in ACTION_GROUPS for aid, label in items}
POINTER_CHOICES = [("mouse", "Moves the mouse"), ("none", "Disabled")]
STICK_CHOICES = [("lstick", "Left stick"), ("rstick", "Right stick"), ("hat", "D-pad"), ("none", "None")]
ALL_ACTION_IDS = set(ACTION_LABELS)


def split_action(value):
    """'pad:A+pad:B' -> ['pad:A', 'pad:B'];  'none' / '' -> []"""
    return [p for p in (value or "").split("+") if p and p != "none"]


def join_actions(parts):
    parts = [p for p in parts if p and p != "none"]
    return "+".join(parts) if parts else "none"

# shake right = the list scrolls left (next collection, R1); shake left = previous (L1)
_COMMON_SHAKE = {"ShakeRight": "pad:TR", "ShakeLeft": "pad:TL", "ShakeUp": "none", "ShakeDown": "none"}
_NUN = {"NunC": "pad:TL", "NunZ": "trig:L2", "NunStick": "lstick"}
_DPAD_HAT = {"Up": "hat:up", "Down": "hat:down", "Left": "hat:left", "Right": "hat:right"}


def _b(**kw):
    d = {}
    for part in kw.values():
        d.update(part)
    return d


_SYS = {"Plus": "pad:START", "Minus": "pad:SELECT", "Home": "pad:MODE"}
_HORIZ = {"Pointer": "none", "Two": "pad:A", "One": "pad:B", "A": "pad:X", "B": "pad:Y",
          # remote held sideways: the D-pad rotates 90 degrees and acts as the left stick (not as a D-pad)
          "Up": "lstick:left", "Right": "lstick:up", "Down": "lstick:right", "Left": "lstick:down"}

DEFAULT_PROFILES = {
    # Steam Menus: the pointer clicks with A
    "menus": {
        "vertical": _b(a={"Pointer": "mouse", "A": "mouse:LEFT", "B": "pad:B", "One": "pad:X", "Two": "pad:Y"}, y=_SYS, d=_DPAD_HAT, n=_NUN, s=_COMMON_SHAKE),
        "horizontal": _b(a=_HORIZ, y=_SYS, n=_NUN, s=_COMMON_SHAKE),
        "nunchuk": _b(a={"Pointer": "mouse", "A": "mouse:LEFT", "B": "pad:B", "One": "pad:X", "Two": "pad:Y"}, y=_SYS, d=_DPAD_HAT, n=_NUN, s=_COMMON_SHAKE),
    },
    # Games: A, B... as Steam Deck buttons
    "juego": {
        "vertical": _b(a={"Pointer": "mouse", "A": "pad:A", "B": "trig:R2", "One": "pad:X", "Two": "pad:Y"}, y=_SYS, d=_DPAD_HAT, n=_NUN, s=_COMMON_SHAKE),
        "horizontal": _b(a=_HORIZ, y=_SYS, n=_NUN, s=_COMMON_SHAKE),
        "nunchuk": _b(a={"Pointer": "mouse", "A": "pad:A", "B": "trig:R2", "One": "pad:X", "Two": "pad:Y"}, y=_SYS, d=_DPAD_HAT, n=_NUN, s=_COMMON_SHAKE),
    },
}

# (buttons at once, program action, seconds they must be HELD: 0 = instant)
CHORDS = (
    (wl.BTN_ONE | wl.BTN_TWO, "cycle_mode", 0.0),
    (wl.BTN_PLUS | wl.BTN_MINUS, "toggle_profile", 0.0),
    (wl.BTN_DOWN | wl.BTN_PLUS, "toggle_pointer", None),     # None = cfg["hold_chord_seconds"]
    (wl.BTN_HOME | wl.BTN_PLUS, "open_qam", None),
)
CHORD_MEMBERS = {wl.BTN_ONE, wl.BTN_TWO, wl.BTN_PLUS, wl.BTN_MINUS, wl.BTN_HOME}   # wait chord_window before pressing
HOLD_FREE = {wl.BTN_DOWN}     # takes part in a hold chord without delaying its normal press (the D-pad cannot be delayed)

DEFAULT_CONFIG = {
    "mode": "vertical",
    "profile": "menus",
    "enabled": True,
    "px_per_deg": 45.0,
    "smooth_min_cut": 1.5,
    "smooth_beta": 0.35,
    "invert_x": False,
    "invert_y": False,
    "shake_enabled": True,
    "shake_threshold": 0.55,      # g of dynamic acceleration (lower = easier)
    "shake_reversals": 3,         # direction reversals required (2 = back and forth; more = a more "real shake")
    "shake_gap": 0.4,             # max seconds between direction reversals (higher = allows slower, gentler shaking)
    "ir_enabled": True,           # global IR pointer (toggled by holding Down + Plus, or from the plugin)
    "hold_chord_seconds": 2.0,    # how long Down+Plus / Home+Plus must be held
    "notify_enabled": True,        # pop-up notices when switching mode or profile (Decky plugin)
    "dsu_mirror": False,           # also send the motion as pad 1 (in case the game reads the 2nd sensor)
    "eden_shake_gyro": 700.0,      # rotation (deg/s) that accompanies the synthetic shake (a wrist that shakes also rotates)
    "eden_shake_amp": 5.0,         # strength (g) of the synthetic shake sent to the emulator over DSU
    "eden_shake_hz": 8.0,          # speed of the back-and-forth (Hz)
    "eden_shake_cycles": 2,        # number of back-and-forth swings
    "gyro_deadzone": 2.0,           # deg/s below which the gyro sent to DSU is 0 (removes slow drift)
    "dsu_accel_gain": 1.0,         # multiplies the accelerometer sent to DSU (raise it if a game does not notice hits)
    "gyro_from_accel": True,       # without MotionPlus (Nunchuk mode): approximate gyro from the accelerometer for DSU
    "shake_flip_x": False,        # flips left/right of the shake (if your remote detects it reversed)
    "shake_flip_y": False,        # flips up/down of the shake
    "nunchuk_deadzone": 0.15,
    "gyro_enabled": True,         # enables MotionPlus (not compatible with the Nunchuk, which needs it off)
    "gyro_stick": False,          # gyro -> right stick (aiming)
    "gyro_stick_gain": 1.0,
    "dsu_enabled": True,          # DSU/cemuhook server: motion for emulators
    "dsu_port": 26760,            # the usual emulator port; 26761 is also listened on (in case another program holds 26760)
    "dsu_invert": [False, False, False, False, False, False],   # accel x,y,z, gyro pitch,yaw,roll
    "profiles": {},               # user changes only: profiles[profile][mode][input] = action
    "quick_profiles": ["menus", "juego"],   # profiles that + and - on the remote cycle through (quick access)
    "custom_profiles": {},        # user-created profiles: id -> name (they start blank)
    "config_version": 4,
}


def makedirs_owned(path):
    """Creates the folder (under HOME). If we are root (Decky plugin) it leaves them owned by the user, so the AppImage can write."""
    try:
        st = os.stat(HOME)
    except OSError:
        os.makedirs(path, exist_ok=True)
        return
    rel = os.path.relpath(path, HOME)
    cur = HOME
    for part in ([] if rel.startswith("..") else rel.split(os.sep)):
        cur = os.path.join(cur, part)
        if not os.path.isdir(cur):
            os.mkdir(cur)
            if os.geteuid() == 0:
                try:
                    os.chown(cur, st.st_uid, st.st_gid)
                except OSError:
                    pass
    os.makedirs(path, exist_ok=True)


def _fix_owner(path):
    if os.geteuid() == 0:
        try:
            st = os.stat(HOME)
            os.chown(path, st.st_uid, st.st_gid)
        except OSError:
            pass


def default_bindings(profile, mode):
    """Factory bindings. User profiles start blank: everything set to 'None'."""
    base = {name: "none" for name, _ in INPUTS}
    if profile in DEFAULT_PROFILES:
        base.update(DEFAULT_PROFILES[profile][mode])
    return base


def profile_ids(cfg):
    return list(BUILTIN_PROFILES) + list(cfg.get("custom_profiles", {}))


def profile_title(cfg, pid):
    return PROFILE_TITLES.get(pid) or cfg.get("custom_profiles", {}).get(pid, pid)


def deep_copy(x):
    return json.loads(json.dumps(x))


def load_config():
    cfg = deep_copy(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH) as f:
            user = json.load(f)
    except (OSError, ValueError):
        user = {}
    for k, v in user.items():
        if k in cfg and k != "profiles":
            cfg[k] = v
    if isinstance(user.get("profiles"), dict):
        cfg["profiles"] = user["profiles"]
    # migration from v0.1: per-mode "bindings" = "menus" profile
    if isinstance(user.get("bindings"), dict):
        for mode, d in user["bindings"].items():
            if isinstance(d, dict) and mode in MODES:
                cfg["profiles"].setdefault("menus", {}).setdefault(mode, {}).update(d)
    if cfg["mode"] not in MODES:
        cfg["mode"] = "vertical"
    cp = cfg.get("custom_profiles")
    cfg["custom_profiles"] = ({str(k): str(v)[:24] for k, v in cp.items() if str(k) not in BUILTIN_PROFILES}
                              if isinstance(cp, dict) else {})
    if cfg["profile"] not in profile_ids(cfg):
        cfg["profile"] = "menus"
    # migration: port 26760 (the old one) clashes with EmuDeck's SteamDeckGyroDSU
    if int(user.get("config_version", 0) or 0) < 4 and cfg.get("dsu_port") in (26760, 26761):
        cfg["dsu_port"] = DEFAULT_CONFIG["dsu_port"]
    cfg["config_version"] = DEFAULT_CONFIG["config_version"]
    if not (isinstance(cfg["dsu_invert"], list) and len(cfg["dsu_invert"]) == 6):
        cfg["dsu_invert"] = [False] * 6
    return cfg


def save_config(cfg):
    try:
        makedirs_owned(CONFIG_DIR)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
        _fix_owner(tmp)
        os.replace(tmp, CONFIG_PATH)
    except OSError:
        pass


def effective_bindings(cfg, profile=None, mode=None):
    profile = profile or cfg["profile"]
    mode = mode or cfg["mode"]
    b = default_bindings(profile, mode)
    user = cfg.get("profiles", {}).get(profile, {}).get(mode, {})
    if isinstance(user, dict):
        b.update({k: v for k, v in user.items() if k in INPUT_LABELS})
    return b


def valid_value(input_name, value):
    if input_name == "Pointer":
        return value in dict(POINTER_CHOICES)
    if input_name == "NunStick":
        return value in dict(STICK_CHOICES)
    parts = (value or "").split("+")
    if not parts or len(parts) > MAX_COMBO or any(p not in ALL_ACTION_IDS for p in parts):
        return False
    return "none" not in parts or len(parts) == 1


# ----------------------------------------------------------------------------- uinput
EV_SYN, EV_KEY, EV_REL, EV_ABS = 0, 1, 2, 3
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL = 0, 1, 6, 8
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_HAT0X, ABS_HAT0Y = 0, 1, 2, 3, 4, 5, 0x10, 0x11
MOUSE_BUTTONS = {"LEFT": 0x110, "RIGHT": 0x111, "MIDDLE": 0x112}
PAD_BUTTONS = {"A": 0x130, "B": 0x131, "X": 0x133, "Y": 0x134, "TL": 0x136, "TR": 0x137,
               "SELECT": 0x13A, "START": 0x13B, "MODE": 0x13C, "THUMBL": 0x13D, "THUMBR": 0x13E}
_LET = dict(zip("QWERTYUIOP", range(16, 26)))
_LET.update(zip("ASDFGHJKL", range(30, 39)))
_LET.update(zip("ZXCVBNM", range(44, 51)))
KEYS = {"ESC": 1, "ENTER": 28, "SPACE": 57, "TAB": 15, "BACKSPACE": 14, "UP": 103, "DOWN": 108, "LEFT": 105, "RIGHT": 106,
        "HOME": 102, "END": 107, "PAGEUP": 104, "PAGEDOWN": 109, "INSERT": 110, "DELETE": 111,
        "LSHIFT": 42, "LCTRL": 29, "LALT": 56, "LMETA": 125,
        "MINUS": 12, "EQUAL": 13, "COMMA": 51, "DOT": 52, "SLASH": 53,
        "VOLUMEUP": 115, "VOLUMEDOWN": 114, "MUTE": 113, "PLAYPAUSE": 164, "NEXTSONG": 163, "PREVSONG": 165}
KEYS.update(_LET)
KEYS.update({str((i + 1) % 10): 2 + i for i in range(10)})          # 1..9 y 0
KEYS.update({"F%d" % i: 58 + i for i in range(1, 11)})              # F1..F10 = 59..68
KEYS.update({"F11": 87, "F12": 88})
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT, UI_SET_ABSBIT = 0x40045564, 0x40045565, 0x40045566, 0x40045567
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
UINPUT_PATHS = ("/dev/uinput", "/dev/input/uinput")
EVENT_FMT = "llHHi"


class UInput:
    """Virtual uinput device (uinput_user_dev interface, valid on all kernels)."""

    def __init__(self, name, vendor, product, keys=(), rels=(), abss=None, bustype=3, version=0x110):
        self.name, self.vendor, self.product, self.version, self.bustype = name, vendor, product, version, bustype
        self.keys, self.rels, self.abss = list(keys), list(rels), dict(abss or {})
        self.fd = None
        self.lock = threading.Lock()

    def open(self):
        last = None
        for p in UINPUT_PATHS:
            try:
                self.fd = os.open(p, os.O_WRONLY | os.O_NONBLOCK)
                break
            except OSError as e:
                last = e
        if self.fd is None:
            raise last or OSError("no /dev/uinput")
        try:
            if self.keys:
                fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
                for k in self.keys:
                    fcntl.ioctl(self.fd, UI_SET_KEYBIT, k)
            if self.rels:
                fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
                for r in self.rels:
                    fcntl.ioctl(self.fd, UI_SET_RELBIT, r)
            if self.abss:
                fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
                for a in self.abss:
                    fcntl.ioctl(self.fd, UI_SET_ABSBIT, a)
            absmax, absmin, absfuzz, absflat = [0] * 64, [0] * 64, [0] * 64, [0] * 64
            for code, (mn, mx, fuzz, flat) in self.abss.items():
                absmin[code], absmax[code], absfuzz[code], absflat[code] = mn, mx, fuzz, flat
            data = struct.pack("80s4HI" + "64i" * 4, self.name.encode()[:79], self.bustype, self.vendor, self.product,
                               self.version, 0, *absmax, *absmin, *absfuzz, *absflat)
            os.write(self.fd, data)
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError:
            self.close()
            raise

    def emit(self, events):
        """events: list of (type, code, value); SYN_REPORT is appended."""
        if self.fd is None or not events:
            return
        now = time.time()
        sec, usec = int(now), int((now % 1) * 1e6)
        buf = b"".join(struct.pack(EVENT_FMT, sec, usec, t, c, v) for t, c, v in events)
        buf += struct.pack(EVENT_FMT, sec, usec, EV_SYN, 0, 0)
        with self.lock:
            try:
                os.write(self.fd, buf)
            except OSError:
                pass

    def close(self):
        if self.fd is not None:
            try:
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


def make_pad():
    # Presents itself as an Xbox 360 controller: Steam and SDL recognise it without configuration.
    abss = {ABS_X: (-32768, 32767, 16, 128), ABS_Y: (-32768, 32767, 16, 128),
            ABS_RX: (-32768, 32767, 16, 128), ABS_RY: (-32768, 32767, 16, 128),
            ABS_Z: (0, 255, 0, 0), ABS_RZ: (0, 255, 0, 0), ABS_HAT0X: (-1, 1, 0, 0), ABS_HAT0Y: (-1, 1, 0, 0)}
    return UInput("Microsoft X-Box 360 pad", 0x045E, 0x028E, keys=PAD_BUTTONS.values(), abss=abss, version=0x0114)


def make_mouse():
    return UInput("WimotionControlDeck Mouse", 0x1209, 0x57D1, keys=MOUSE_BUTTONS.values(), rels=(REL_X, REL_Y, REL_WHEEL, REL_HWHEEL))


def make_keyboard():
    return UInput("WimotionControlDeck Keyboard", 0x1209, 0x57D2, keys=KEYS.values())


# ----------------------------------------------------------------------------- gyro
class GyroTracker:
    """MotionPlus -> angular velocity in the remote's body frame (deg/s) with bias calibration."""
    SLOW = 440.0 / 8192.0
    FAST = 2000.0 / 8192.0

    def __init__(self):
        self.zero_slow = [8192.0] * 3
        self.zero_fast = [8192.0] * 3
        self.win = deque(maxlen=60)
        self.n = 0
        self.cal_t0 = None
        self.cal_sum = [0.0] * 3
        self.cal_n = 0
        self.body = (0.0, 0.0, 0.0)       # (pitch +up, roll +right, yaw +left) deg/s

    def request_calibration(self, t):
        self.cal_t0 = t
        self.cal_sum = [0.0] * 3
        self.cal_n = 0

    @property
    def calibrating(self):
        return self.cal_t0 is not None

    def update(self, mp, t):
        yaw_r, roll_r, pitch_r, s_yaw, s_roll, s_pitch, _ext = mp
        raw = (yaw_r, roll_r, pitch_r)
        slow = (s_yaw, s_roll, s_pitch)
        all_slow = s_yaw and s_roll and s_pitch
        if self.cal_t0 is not None:
            if all_slow:
                for k in range(3):
                    self.cal_sum[k] += raw[k]
                self.cal_n += 1
            if t - self.cal_t0 >= 1.2 and self.cal_n >= 60:
                for k in range(3):
                    self.zero_slow[k] = self.zero_fast[k] = self.cal_sum[k] / self.cal_n
                self.cal_t0 = None
        # auto-zero while the remote rests steadily (noise ~0.3 deg/s = ~5 units)
        self.win.append(raw)
        self.n += 1
        if all_slow and len(self.win) == self.win.maxlen and self.n % 10 == 0:
            ok = True
            means = []
            for k in range(3):
                vals = [w[k] for w in self.win]
                m = sum(vals) / len(vals)
                sd = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5
                if sd > 20.0 or abs(m - self.zero_slow[k]) > 400.0:
                    ok = False
                    break
                means.append(m)
            if ok:
                for k in range(3):
                    self.zero_slow[k] += (means[k] - self.zero_slow[k]) * 0.06
                    self.zero_fast[k] = self.zero_slow[k]
        dps = [0.0, 0.0, 0.0]
        for k in range(3):
            zero = self.zero_slow[k] if slow[k] else self.zero_fast[k]
            dps[k] = (raw[k] - zero) * (self.SLOW if slow[k] else self.FAST)
        # raw: yaw +right, roll +right, pitch +up (verified with the IR)
        self.body = (dps[2], dps[1], -dps[0])
        return self.body


class AccGyro:
    """
    APPROXIMATE gyro derived from the accelerometer, for when there is no MotionPlus (Nunchuk mode). The "up" direction measured
    by the accelerometer rotates opposite to the remote: omega = -(a_before x a_now) / dt (deg/s, remote body axes).
    It only gives pitch and roll (rotation about the vertical -yaw- is not visible in gravity) and only works with gentle
    movements (if the remote accelerates hard, |a| drifts away from 1 g and is ignored). It is far less precise than a real gyro.
    """
    TAU = 0.04          # direction smoothing
    SPAN = 0.06         # time base of the derivative (s)
    DEAD = 6.0          # deg/s below which 0 is output (noise)

    def __init__(self):
        self.a = None
        self.last_t = None
        self.hist = deque()
        self.out = [0.0, 0.0, 0.0]

    def reset(self):
        self.a = None
        self.last_t = None
        self.hist.clear()
        self.out = [0.0, 0.0, 0.0]

    def update(self, acc, t):
        mag = math.sqrt(acc[0] ** 2 + acc[1] ** 2 + acc[2] ** 2)
        if mag < 0.75 or mag > 1.25:           # the remote is being shaken: gravity cannot be distinguished
            self.hist.clear()
            self.out = [v * 0.5 for v in self.out]
            return tuple(self.out)
        u = [acc[i] / mag for i in range(3)]
        if self.a is None or self.last_t is None:
            self.a = u
        else:
            k = 1.0 - math.exp(-max(t - self.last_t, 0.001) / self.TAU)
            self.a = [self.a[i] + (u[i] - self.a[i]) * k for i in range(3)]
        self.last_t = t
        self.hist.append((t, tuple(self.a)))
        while len(self.hist) > 1 and t - self.hist[0][0] > self.SPAN * 1.6:
            self.hist.popleft()
        t0, a0 = self.hist[0]
        dt = t - t0
        if dt < self.SPAN * 0.5:
            return tuple(self.out)
        a1 = self.a
        cx = a0[1] * a1[2] - a0[2] * a1[1]
        cy = a0[2] * a1[0] - a0[0] * a1[2]
        cz = a0[0] * a1[1] - a0[1] * a1[0]
        w = [-v / dt * 180.0 / math.pi for v in (cx, cy, cz)]
        for i in range(3):
            if abs(w[i]) < self.DEAD:
                w[i] = 0.0
            w[i] = max(-1500.0, min(1500.0, w[i]))
            self.out[i] += (w[i] - self.out[i]) * 0.5
        return tuple(self.out)


def motion_to_dsu(gyro_body, acc_body, preset, invert):
    """
    Converts to the axis system of a DS4/DSU controller. Remote (x right, y tip, z up) -> "gamepad"
    (x right, y forward, z up): vertical = identical; sideways (NES, tip to the left) = (-y, x, z).
    DS4: accel = (x, z, -y); gyro = (pitch, yaw, roll) = (gx, gz, -gy). Adjustable with dsu_invert.
    """
    def conv(v):
        if preset == "sideways":
            return (-v[1], v[0], v[2])
        return v
    g = conv(gyro_body)
    a = conv(acc_body)
    vals = [a[0], a[2], -a[1], g[0], g[2], -g[1]]
    for i in range(6):
        if invert[i]:
            vals[i] = -vals[i]
    return tuple(vals[:3]), tuple(vals[3:])


# ----------------------------------------------------------------------------- DSU server (cemuhook)
DSU_VERSION = 1001
MSG_VERSION, MSG_INFO, MSG_DATA = 0x100000, 0x100001, 0x100002


def port_owner(port):
    """(pid, name, command line) of the program holding the local UDP port open, or None. Reads /proc (seeing other
    users' processes requires root, as with the Decky plugin)."""
    hexport = ":%04X" % port
    inodes = set()
    for path in ("/proc/net/udp", "/proc/net/udp6"):
        try:
            with open(path) as f:
                next(f, None)
                for line in f:
                    p = line.split()
                    if len(p) > 9 and p[1].upper().endswith(hexport):
                        inodes.add(p[9])
        except OSError:
            pass
    if not inodes:
        return None
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            for fd in os.listdir("/proc/%s/fd" % pid):
                try:
                    link = os.readlink("/proc/%s/fd/%s" % (pid, fd))
                except OSError:
                    continue
                if link.startswith("socket:[") and link[8:-1] in inodes:
                    try:
                        name = open("/proc/%s/comm" % pid).read().strip()
                        cmd = open("/proc/%s/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
                    except OSError:
                        name, cmd = "?", ""
                    return int(pid), name, cmd
        except OSError:
            continue
    return None


class DSUServer:
    """DSU/cemuhook motion server over UDP (port 26760). Emulators connect and receive the remote's accel+gyro."""

    def __init__(self, port=26760, log=None, bind="127.0.0.1", extra_ports=()):
        self.port, self.log, self.bind = port, log, bind
        self.extra_ports = tuple(extra_ports)   # additional ports that are also listened on (if free)
        self.extra_socks = []
        self.client_sock = {}                   # addr -> socket that client talks through
        self.requested_port = port
        self.server_id = random.getrandbits(32)
        self.sock = None
        self.clients = {}            # addr -> expiry time
        self.packet_no = 0
        self.last_send = 0.0
        self.connected = False
        self.last_data = 0.0          # last time the controller gave us data from a remote
        self.sent = 0                 # motion packets sent
        self.battery = 0x05
        self._stop = False
        self._thread = None
        self.lock = threading.Lock()
        self._seen_bad = set()
        self.extra_state = {}         # extra port -> ("wimotioncontroldeck" | "busy", who)
        self.retry_s = 5.0
        self._extras_t = time.monotonic()
        self.mirror = False           # copies the same data to pad 1 (for the emulator's 2nd motion sensor)
        self.on_client = None         # callback() when an emulator connects (to log whether there is gyro)
        self.mac = bytes([0x57, 0x69, 0x69, 0x44, 0x65, 0x63])

    def start(self):
        """Opens the port. WITHOUT SO_REUSEADDR: on UDP it would allow sharing it with another server (e.g. SteamDeckGyroDSU on 26760)
        and emulators would talk to the other one without any error. If it is busy, the next 9 are tried."""
        self._stop = False
        first = self.requested_port
        last_err = None
        for port in range(first, first + 10):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.bind((self.bind, port))
                sock.settimeout(0.2)
            except OSError as e:
                sock.close()
                last_err = e
                if self.log:
                    self.log.event("APP", "DSU", "Port %d is busy (%s)" % (port, e))
                continue
            self.sock, self.port = sock, port
            break
        else:
            if self.log:
                self.log.event("APP", "DSU", "Could not open any port %d-%d: %s" % (first, first + 9, last_err))
            self.sock = None
            return False
        self.extra_socks = []
        self.extra_state = {}
        self._try_extras(first_time=True)
        self._thread = threading.Thread(target=self._loop, name="dsu", daemon=True)
        self._thread.start()
        if self.log:
            ports = [self.port] + [x.getsockname()[1] for x in self.extra_socks]
            self.log.event("APP", "DSU", "DSU server on %s, ports %s (use any of them in the emulator)" % (self.bind, ", ".join(map(str, ports))))
        return True

    def _try_extras(self, first_time=False):
        """Opens any missing extra ports. Repeated every few seconds: if the program that held 26760 (e.g. the Deck's own
        DSU gyro) stops, WimotionControlDeck takes it over by itself and emulators pointing there receive the remote."""
        have = {x.getsockname()[1] for x in self.extra_socks}
        for p in self.extra_ports:
            if p == self.port or p in have:
                continue
            xs = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                xs.bind((self.bind, p))
                xs.settimeout(0.2)
                self.extra_socks.append(xs)
                self.extra_state[p] = ("wimotioncontroldeck", "")
                if self.log and not first_time:
                    self.log.event("APP", "DSU", "Port %d freed: now served by WimotionControlDeck" % p)
            except OSError as e:
                xs.close()
                owner = port_owner(p)
                desc = "%s (pid %d)" % (owner[1], owner[0]) if owner else "another program"
                if self.extra_state.get(p, (None, None))[1] != desc and self.log:
                    self.log.event("APP", "DSU", "Port %d is busy, used by %s (%s): WimotionControlDeck will take it if it is freed" % (p, desc, e))
                self.extra_state[p] = ("busy", desc)

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(1.0)
        for x in self.extra_socks:
            try:
                x.close()
            except OSError:
                pass
        self.extra_socks = []
        self.client_sock = {}
        if self.sock:
            self.sock.close()
            self.sock = None

    def set_port(self, port):
        """Changes the port (restarts the server if it was open)."""
        was = self.sock is not None
        if was:
            self.stop()
        self.requested_port = self.port = int(port)
        if was:
            self.start()

    def mark_alive(self):
        self.last_data = time.monotonic()

    @property
    def alive(self):
        return self.connected or (time.monotonic() - self.last_data) < 2.0

    @property
    def client_count(self):
        now = time.monotonic()
        with self.lock:
            return sum(1 for t in self.clients.values() if t > now)

    def _packet(self, msg_type, payload):
        body = struct.pack("<I", msg_type) + payload
        pkt = b"DSUS" + struct.pack("<HHII", DSU_VERSION, len(body), 0, self.server_id) + body
        crc = zlib.crc32(pkt) & 0xFFFFFFFF
        return pkt[:8] + struct.pack("<I", crc) + pkt[12:]

    def _shared(self, slot, connected):
        state = 2 if (connected and (slot == 0 or (slot == 1 and self.mirror))) else 0
        model = 2 if state else 0
        conn = 2 if state else 0
        mac = self.mac if state else bytes(6)
        return struct.pack("<BBBB6sB", slot, state, model, conn, mac, self.battery if state else 0)

    def _loop(self):
        while not self._stop:
            if time.monotonic() - self._extras_t > self.retry_s:
                self._extras_t = time.monotonic()
                try:
                    self._try_extras()
                except Exception:
                    pass
            socks = [self.sock] + list(self.extra_socks)
            try:
                ready, _, _ = select.select(socks, [], [], 0.2)
            except (OSError, ValueError):
                return
            for sk in ready:
                try:
                    data, addr = sk.recvfrom(256)
                except socket.timeout:
                    continue
                except OSError:
                    continue
                try:
                    self._handle(data, addr, sk)
                except Exception as e:
                    if self.log:
                        self.log.event("APP", "DSU", "invalid packet: %r" % e)

    def _handle(self, data, addr, sock=None):
        sock = sock or self.sock
        if len(data) < 20 or data[:4] != b"DSUC":
            if self.log and addr not in self._seen_bad:
                self._seen_bad.add(addr)
                self.log.event("APP", "DSU", "Receiving data from %s:%d that is not DSU (another program?)" % addr)
            return
        _ver, length, crc, _cid = struct.unpack("<HHII", data[4:16])
        body = bytearray(data)
        body[8:12] = b"\x00\x00\x00\x00"
        if (zlib.crc32(bytes(body)) & 0xFFFFFFFF) != crc:
            return
        mtype = struct.unpack("<I", data[16:20])[0]
        payload = data[20:]
        if mtype == MSG_VERSION:
            sock.sendto(self._packet(MSG_VERSION, struct.pack("<H", DSU_VERSION)), addr)
        elif mtype == MSG_INFO:
            count = struct.unpack("<i", payload[:4])[0]
            for i in range(max(0, min(count, 4))):
                slot = payload[4 + i]
                sock.sendto(self._packet(MSG_INFO, self._shared(slot, self.alive) + b"\x00"), addr)
        elif mtype == MSG_DATA:
            flags = payload[0] if payload else 0
            slot = payload[1] if len(payload) > 1 else 0
            if flags == 0 or (flags & 1 and (slot == 0 or (slot == 1 and self.mirror))) or (flags & 2):
                with self.lock:
                    new = addr not in self.clients or self.clients[addr] < time.monotonic()
                    self.clients[addr] = time.monotonic() + 30.0
                    self.client_sock[addr] = sock
                if new:
                    if self.log:
                        self.log.event("APP", "DSU", "Client connected: %s:%d (port %d)" % (addr + (sock.getsockname()[1],)))
                    if self.on_client:
                        self.on_client()

    def push(self, acc, gyro, pad_state, t_us):
        """acc (g), gyro (pitch, yaw, roll deg/s), pad_state: button dict. Sent to the registered clients (max ~250/s)."""
        if not self.sock:
            return
        now = time.monotonic()
        if now - self.last_send < 0.004:
            return
        with self.lock:
            targets = [a for a, t in self.clients.items() if t > now]
        if not targets:
            return
        self.last_send = now
        self.sent += 1
        ps = pad_state.get
        b1 = (0x01 if ps("select") else 0) | (0x02 if ps("l3") else 0) | (0x04 if ps("r3") else 0) \
            | (0x08 if ps("start") else 0) | (0x10 if ps("up") else 0) | (0x20 if ps("right") else 0) \
            | (0x40 if ps("down") else 0) | (0x80 if ps("left") else 0)
        b2 = (0x01 if ps("l2") else 0) | (0x02 if ps("r2") else 0) | (0x04 if ps("l1") else 0) \
            | (0x08 if ps("r1") else 0) | (0x10 if ps("x") else 0) | (0x20 if ps("a") else 0) \
            | (0x40 if ps("b") else 0) | (0x80 if ps("y") else 0)

        def stick(v):
            return int(max(0, min(255, 128 + v * 127)))
        lx, ly, rx, ry = ps("lx", 0.0), ps("ly", 0.0), ps("rx", 0.0), ps("ry", 0.0)
        analog = bytes(255 if ps(k) else 0 for k in ("left", "down", "right", "up", "y", "b", "a", "x", "r1", "l1", "r2", "l2"))
        slots = (0, 1) if self.mirror else (0,)
        for slot in slots:
            self.packet_no = (self.packet_no + 1) & 0xFFFFFFFF
            payload = self._shared(slot, True) + struct.pack("<BI", 1, self.packet_no) + bytes([b1, b2, 1 if ps("home") else 0, 0]) \
                + bytes([stick(lx), stick(-ly), stick(rx), stick(-ry)]) + analog + bytes(12) \
                + struct.pack("<Q6f", int(t_us), acc[0], acc[1], acc[2], gyro[0], gyro[1], gyro[2])
            pkt = self._packet(MSG_DATA, payload)
            for a in targets:
                try:
                    (self.client_sock.get(a) or self.sock).sendto(pkt, a)
                except OSError:
                    pass


# ----------------------------------------------------------------------------- controller
class RemoteState:
    def __init__(self, cfg):
        self.prev_buttons = 0
        self.pointer = wl.IRPointer()
        self.oe_x = wl.OneEuro(cfg["smooth_min_cut"], cfg["smooth_beta"], 1.0)
        self.oe_y = wl.OneEuro(cfg["smooth_min_cut"], cfg["smooth_beta"], 1.0)
        self.ref = None
        self.last_ir_t = -9.0
        self.last_ptr_t = None
        self.frac = [0.0, 0.0]
        self.shake = wl.ShakeDetector(cfg["shake_threshold"], cfg["shake_reversals"], gap=cfg["shake_gap"])
        self.pending = {}
        self.active = {}
        self.suppressed = set()
        self.timers = []
        self.nun_center = None
        self.nun_acc = [0.0, 0.0]
        self.nun_n = 0
        self.nun_c = self.nun_z = False
        self.nun_seen_t = -9.0
        self.nun_x = self.nun_y = 0.0
        self.last_ir = []
        self.last_info = None
        self.last_event = ""
        self.last_event_t = 0.0
        self.gyro = GyroTracker()
        self.gyro_dps = (0.0, 0.0, 0.0)
        self.accgyro = AccGyro()
        self.acc_peak = 0.0
        self.acc_peak_t = 0.0
        self.acc_body = (0.0, 0.0, 1.0)
        self.dsu_acc = (0.0, 0.0, 0.0)
        self.dsu_gyro = (0.0, 0.0, 0.0)
        self.mp_seen_t = -9.0
        self.shake_on = False
        self.holds = {}                 # armed hold chord: name -> (mask, seconds, start)
        self.nun_shake = wl.ShakeDetector(cfg["shake_threshold"], cfg["shake_reversals"], gap=cfg["shake_gap"])


class DeckController:
    def __init__(self, cfg, log, pad=None, mouse=None, kbd=None, dsu=None):
        self.cfg = cfg
        self.log = log
        self.lock = threading.RLock()
        self.pad = pad if pad is not None else make_pad()
        self.mouse = mouse if mouse is not None else make_mouse()
        self.kbd = kbd if kbd is not None else make_keyboard()
        self.dsu = dsu
        self.devices_ok = False
        self.error = ""
        self.states = {}
        self.hat = {"up": 0, "down": 0, "left": 0, "right": 0}
        self.stick_dig = {"lstick": {"up": 0, "down": 0, "left": 0, "right": 0}, "rstick": {"up": 0, "down": 0, "left": 0, "right": 0}}
        self.stick_ana = {"lstick": (0.0, 0.0), "rstick": (0.0, 0.0)}
        self.stick_out = {"lstick": (0, 0), "rstick": (0, 0)}
        self.trig = {"L2": 0, "R2": 0}
        self.down = set()
        self.held = {}                  # action -> times pressed (two inputs with the same button are not released halfway)
        self.owner_slot = None
        self.wiimotes = []
        self.chord_window = 0.12
        self.on_mp_change = None        # callback(want_mp)
        self._eden_pulse = None         # [direction, t0] of the synthetic shake in progress
        self.on_notify = None           # callback(title, text): the plugin shows it as a Steam notification
        self.on_open_qam = None         # callback(): the Decky plugin opens the ... menu (QAM); without it, Steam + A is sent
        self._now = None                # time of the last frame (same time base as the timers)

    # -- virtual devices
    def open_devices(self):
        try:
            self.pad.open()
            self.mouse.open()
            self.kbd.open()
            self.devices_ok = True
            self.error = ""
            self.log.event("APP", "UINPUT", "Virtual devices created: Xbox 360 gamepad + mouse + keyboard")
        except OSError as e:
            self.devices_ok = False
            self.error = "Cannot create virtual devices (%s). Run install-udev.sh or: sudo chmod 666 /dev/uinput" % e
            self.log.event("APP", "ERROR", self.error)
        return self.devices_ok

    def close_devices(self):
        self.release_all()
        self.pad.close()
        self.mouse.close()
        self.kbd.close()

    @property
    def mode(self):
        return self.cfg["mode"]

    @property
    def profile(self):
        return self.cfg["profile"]

    def bindings(self):
        return effective_bindings(self.cfg)

    def want_mp(self):
        return bool(self.cfg["gyro_enabled"]) and self.mode != "nunchuk"

    # -- sticks / triggers
    def _emit_sticks(self):
        if not self.devices_ok:
            return
        ev = []
        for name, (cx, cy) in (("lstick", (ABS_X, ABS_Y)), ("rstick", (ABS_RX, ABS_RY))):
            d = self.stick_dig[name]
            ax, ay = self.stick_ana[name]
            x = ax + (d["right"] - d["left"])
            y = ay + (d["up"] - d["down"])            # positive y = up
            n = (x * x + y * y) ** 0.5
            if n > 1.0:
                x, y = x / n, y / n
            vx, vy = int(x * 32767), int(-y * 32767)   # the gamepad Y axis is positive downwards
            if (vx, vy) != self.stick_out[name]:
                self.stick_out[name] = (vx, vy)
                ev += [(EV_ABS, cx, vx), (EV_ABS, cy, vy)]
        if ev:
            self.pad.emit(ev)

    # -- actions
    HELD_KINDS = ("pad", "trig", "mouse", "key", "hat", "lstick", "rstick")

    def do_action(self, action, down):
        if not action or action == "none":
            return
        if "+" in action:                       # "A + B" combination: all are pressed and released
            parts = split_action(action)
            for part in (parts if down else reversed(parts)):
                self.do_action(part, down)
            return
        kind, _, name = action.partition(":")
        if kind == "app":
            if down:
                self._app(name)
            return
        if kind in self.HELD_KINDS:
            n = self.held.get(action, 0)
            if down:
                self.held[action] = n + 1
                if n:
                    return
            elif n > 1:
                self.held[action] = n - 1
                return
            else:
                self.held.pop(action, None)
        self._do(action, down)

    def _do(self, action, down):
        kind, _, name = action.partition(":")
        if not self.devices_ok:
            return
        mark = self.down.add if down else self.down.discard
        if kind == "pad" and name in PAD_BUTTONS:
            mark(action)
            self.pad.emit([(EV_KEY, PAD_BUTTONS[name], 1 if down else 0)])
        elif kind == "trig" and name in self.trig:
            mark(action)
            self.trig[name] = 255 if down else 0
            self.pad.emit([(EV_ABS, ABS_Z if name == "L2" else ABS_RZ, self.trig[name])])
        elif kind == "mouse" and name in MOUSE_BUTTONS:
            mark(action)
            self.mouse.emit([(EV_KEY, MOUSE_BUTTONS[name], 1 if down else 0)])
        elif kind == "key" and name in KEYS:
            mark(action)
            self.kbd.emit([(EV_KEY, KEYS[name], 1 if down else 0)])
        elif kind == "wheel":
            if down:
                self.mouse.emit([(EV_REL, REL_WHEEL, 1 if name == "up" else -1)])
        elif kind == "hat" and name in self.hat:
            mark(action)
            self.hat[name] = 1 if down else 0
            self.pad.emit([(EV_ABS, ABS_HAT0X, self.hat["right"] - self.hat["left"]),
                           (EV_ABS, ABS_HAT0Y, self.hat["down"] - self.hat["up"])])
        elif kind in ("lstick", "rstick") and name in self.stick_dig[kind]:
            mark(action)
            self.stick_dig[kind][name] = 1 if down else 0
            self._emit_sticks()

    def _app(self, name):
        if name == "cycle_mode":
            self.cycle_mode()
        elif name == "toggle_profile":
            ids = self.quick_profile_ids()
            if ids:
                self.set_profile(ids[(ids.index(self.profile) + 1) % len(ids)] if self.profile in ids else ids[0])
        elif name == "toggle_gyro":
            self.set_option("gyro_enabled", not self.cfg["gyro_enabled"])
        elif name == "calibrate":
            self.calibrate_gyro()
        elif name == "toggle_enabled":
            self.set_enabled(not self.cfg["enabled"])
        elif name == "toggle_pointer":
            on = not self.cfg["ir_enabled"]
            self.set_option("ir_enabled", on)
            self.log.event("APP", "IR", "IR pointer %s" % ("enabled" if on else "disabled"))
            self._rumble_all(0.1 if on else 0.35)
        elif name == "open_qam":
            self.open_qam()
        elif name.startswith("eden_shake_"):
            self.eden_shake(name[len("eden_shake_"):])

    SHAKE_DIRS = {"up": (0.0, 0.0, 1.0), "down": (0.0, 0.0, -1.0), "left": (-1.0, 0.0, 0.0), "right": (1.0, 0.0, 0.0),
                  "forward": (0.0, 1.0, 0.0), "back": (0.0, -1.0, 0.0)}

    SHAKE_GYRO_AXIS = {"up": 0, "down": 0, "forward": 0, "back": 0, "left": 2, "right": 2}

    def eden_shake(self, direction, repeat=0.0):
        """Fires a SYNTHETIC shake towards the emulator (DSU): a strong back-and-forth acceleration in that direction (remote
        axes: x right, y tip, z up) added on top of what the remote measures. It does not touch the buttons or the cursor."""
        d = self.SHAKE_DIRS.get(direction)
        if d is None:
            return False
        self._eden_pulse = [d, None, float(repeat), None, direction]   # t0 is taken from the next report (same clock as the data)
        self.log.event("APP", "GESTURE", "Synthetic shake to the emulator: %s (%.1f g + %.0f deg/s, %.0f Hz, %d swings%s)" % (
            direction, self.cfg["eden_shake_amp"], self.cfg["eden_shake_gyro"], self.cfg["eden_shake_hz"], int(self.cfg["eden_shake_cycles"]),
            ", repeated %.0f s" % repeat if repeat else ""))
        return True

    def _eden_offset(self, now):
        """(extra acceleration, extra gyro) of the synthetic shake at this instant, or None."""
        p = self._eden_pulse
        if not p:
            return None
        if p[1] is None:
            p[1] = now
            if p[3] is None:
                p[3] = now
        tau = now - p[1]
        hz = max(1.0, float(self.cfg["eden_shake_hz"]))
        if tau > int(self.cfg["eden_shake_cycles"]) / hz:
            if p[2] > 0 and now - p[3] < p[2]:          # continuous test: another shake right after
                p[1] = now
                tau = 0.0
            else:
                self._eden_pulse = None
                return None
        w = math.sin(2.0 * math.pi * hz * tau)
        v = float(self.cfg["eden_shake_amp"]) * w
        g = [0.0, 0.0, 0.0]
        g[self.SHAKE_GYRO_AXIS[p[4]]] = float(self.cfg["eden_shake_gyro"]) * w * (1 if p[0][2] + p[0][0] + p[0][1] >= 0 else -1)
        return (p[0][0] * v, p[0][1] * v, p[0][2] * v), tuple(g)

    def open_qam(self):
        """Opens Steam's ... menu: with the Decky plugin the UI does it; without it, Steam + A on the virtual gamepad."""
        self._rumble_all(0.15)
        cb = self.on_open_qam
        if cb:
            try:
                cb()
                return
            except Exception as e:
                self.log.event("APP", "ERROR", "open_qam: %r" % e)
        self.do_action("pad:MODE", True)
        self.do_action("pad:A", True)

        def up():
            with self.lock:
                self.do_action("pad:A", False)
                self.do_action("pad:MODE", False)
        threading.Timer(0.2, up).start()

    def release_all(self):
        with self.lock:
            for rs in self.states.values():
                rs.active.clear()
                rs.pending.clear()
                rs.timers.clear()
                rs.suppressed.clear()
                rs.holds.clear()
            self.held.clear()
            if self.devices_ok:
                for action in list(self.down):
                    self.do_action(action, False)
            self.held.clear()
            self.down.clear()
            for k in self.hat:
                self.hat[k] = 0
            for s in self.stick_dig.values():
                for k in s:
                    s[k] = 0
            self.stick_ana = {"lstick": (0.0, 0.0), "rstick": (0.0, 0.0)}
            self.trig = {"L2": 0, "R2": 0}
            if self.devices_ok:
                self.pad.emit([(EV_ABS, ABS_HAT0X, 0), (EV_ABS, ABS_HAT0Y, 0), (EV_ABS, ABS_X, 0), (EV_ABS, ABS_Y, 0),
                               (EV_ABS, ABS_RX, 0), (EV_ABS, ABS_RY, 0), (EV_ABS, ABS_Z, 0), (EV_ABS, ABS_RZ, 0)])
            self.stick_out = {"lstick": (0, 0), "rstick": (0, 0)}

    def pulse(self, rs, action, seconds=0.12):
        self.do_action(action, True)
        base = self._now if self._now is not None else time.monotonic()
        rs.timers.append((base + seconds, lambda a=action: self.do_action(a, False)))

    # -- modes, profiles, options
    def _led_mask(self):
        return MODE_LEDS[self.mode] | (0b1000 if self.profile != "menus" else 0)

    def _apply_leds(self):
        for wm in list(self.wiimotes):
            try:
                wm.set_led(self._led_mask())
            except Exception:
                pass

    def _rumble_all(self, seconds):
        for wm in list(self.wiimotes):
            try:
                wm.rumble(seconds)
            except Exception:
                pass

    def set_mode(self, mode, rumble=True):
        if mode not in MODES:
            return
        with self.lock:
            if mode == self.cfg["mode"]:
                return
            self.release_all()
            old_mp = self.want_mp()
            self.cfg["mode"] = mode
            self.log.event("APP", "MODE", "Mode %s" % MODE_TITLES[mode])
            self._apply_leds()
            if rumble:
                self._rumble_all(0.12)
            if old_mp != self.want_mp():
                self._mp_changed()
        save_config(self.cfg)
        self._notify("WimotionControlDeck", "Mode: %s" % MODE_TITLES[mode])

    def quick_profile_ids(self):
        """Quick-access profiles (those cycled by + and - on the remote), in profile-list order."""
        q = self.cfg.get("quick_profiles", [])
        return [p for p in profile_ids(self.cfg) if p in q]

    def set_quick_profiles(self, ids):
        with self.lock:
            valid = set(profile_ids(self.cfg))
            self.cfg["quick_profiles"] = [p for p in dict.fromkeys(ids or []) if p in valid]
        save_config(self.cfg)
        return True

    def _notify(self, title, body):
        cb = self.on_notify
        if cb and self.cfg.get("notify_enabled", True):
            try:
                cb(title, body)
            except Exception:
                pass

    def cycle_mode(self):
        self.set_mode(MODES[(MODES.index(self.mode) + 1) % len(MODES)])

    def set_profile(self, profile, rumble=True):
        if profile not in profile_ids(self.cfg):
            return
        with self.lock:
            if profile == self.cfg["profile"]:
                return
            self.release_all()
            self.cfg["profile"] = profile
            self.log.event("APP", "PROFILE", "Profile %s" % profile_title(self.cfg, profile))
            self._apply_leds()
            if rumble:
                self._rumble_all(0.1 if profile == "menus" else 0.25)
        save_config(self.cfg)
        self._notify("WimotionControlDeck", "Profile: %s" % profile_title(self.cfg, profile))

    def create_profile(self, name, copy_from=None):
        """Creates a custom profile. With copy_from (id of an existing profile) it is a COPY of that profile, in all modes;
        without it, blank (everything set to 'None'). Returns its id or None."""
        name = " ".join(str(name or "").split())[:24]
        with self.lock:
            cp = self.cfg.setdefault("custom_profiles", {})
            if not name or len(cp) >= MAX_CUSTOM_PROFILES:
                return None
            if name.lower() in [profile_title(self.cfg, p).lower() for p in profile_ids(self.cfg)]:
                n = 2
                while ("%s %d" % (name, n)).lower() in [profile_title(self.cfg, p).lower() for p in profile_ids(self.cfg)]:
                    n += 1
                name = ("%s %d" % (name, n))[:24]
            k = 1
            while "p%d" % k in cp:
                k += 1
            pid = "p%d" % k
            cp[pid] = name
            if copy_from in profile_ids(self.cfg) and copy_from != pid:
                prof = {}
                for m in MODES:
                    eff = effective_bindings(self.cfg, copy_from, m)
                    base = default_bindings(pid, m)
                    prof[m] = {k: v for k, v in eff.items() if v != base.get(k)}
                self.cfg.setdefault("profiles", {})[pid] = prof
                self.log.event("APP", "PROFILE", "New profile: %s (copy of %s)" % (name, profile_title(self.cfg, copy_from)))
            else:
                self.log.event("APP", "PROFILE", "New profile: %s" % name)
        save_config(self.cfg)
        return pid

    def delete_profile(self, pid):
        with self.lock:
            if pid not in self.cfg.get("custom_profiles", {}):
                return False
            if self.cfg["profile"] == pid:
                self.release_all()
                self.cfg["profile"] = "menus"
                self._apply_leds()
            del self.cfg["custom_profiles"][pid]
            self.cfg["quick_profiles"] = [p for p in self.cfg.get("quick_profiles", []) if p != pid]
            self.cfg.get("profiles", {}).pop(pid, None)
        save_config(self.cfg)
        return True

    def set_enabled(self, enabled):
        with self.lock:
            self.cfg["enabled"] = bool(enabled)
            if not enabled:
                self.release_all()
            self.log.event("APP", "APP", "WimotionControlDeck %s" % ("enabled" if enabled else "disabled"))
            self._rumble_all(0.2 if enabled else 0.08)
        save_config(self.cfg)

    def set_option(self, key, value):
        with self.lock:
            if key not in DEFAULT_CONFIG or key in ("profiles", "mode", "profile", "enabled", "custom_profiles", "quick_profiles", "config_version"):
                return False
            old_mp = self.want_mp()
            self.cfg[key] = value
            self.apply_filters_config()
            if old_mp != self.want_mp():
                self._mp_changed()
        save_config(self.cfg)
        return True

    def set_binding(self, input_name, value, mode=None, profile=None):
        mode = mode or self.mode
        profile = profile or self.profile
        if profile not in profile_ids(self.cfg) or mode not in MODES:
            return False
        if input_name not in INPUT_LABELS or not valid_value(input_name, value):
            return False
        with self.lock:
            self.release_all()
            self.cfg.setdefault("profiles", {}).setdefault(profile, {}).setdefault(mode, {})[input_name] = value
        save_config(self.cfg)
        return True

    def apply_bindings(self, changes):
        """Applies a list of (profile, mode, input, value) at once. All or nothing: if one is invalid, none is applied.
        Saves only once (the editor accumulates changes and applies them with the APPLY button)."""
        parsed = []
        for ch in changes or []:
            try:
                profile, mode, name, value = ch
            except (TypeError, ValueError):
                return False
            if (profile not in profile_ids(self.cfg) or mode not in MODES or name not in INPUT_LABELS
                    or not valid_value(name, value)):
                return False
            parsed.append((profile, mode, name, value))
        if not parsed:
            return True
        with self.lock:
            self.release_all()
            for profile, mode, name, value in parsed:
                user = self.cfg.setdefault("profiles", {}).setdefault(profile, {}).setdefault(mode, {})
                user[name] = value
        save_config(self.cfg)
        self.log.event("APP", "BUTTONS", "Applied %d changes" % len(parsed))
        return True

    def reset_bindings(self, mode=None, profile=None):
        mode = mode or self.mode
        profile = profile or self.profile
        with self.lock:
            self.release_all()
            self.cfg.get("profiles", {}).get(profile, {}).pop(mode, None)
        save_config(self.cfg)

    def _mp_changed(self):
        want = self.want_mp()
        self.log.event("APP", "GYRO", "MotionPlus %s" % ("enabled" if want else "disabled"))
        for wm in list(self.wiimotes):
            wm.use_mp = want
            wm.request_reinit()
        if self.on_mp_change:
            self.on_mp_change(want)

    def calibrate_gyro(self):
        t = time.monotonic()
        for rs in self.states.values():
            rs.gyro.request_calibration(t)
        self.log.event("APP", "GYRO", "Calibrating gyro: keep the remote still for 1 second")

    def apply_filters_config(self):
        for rs in self.states.values():
            rs.oe_x.min_cut = rs.oe_y.min_cut = self.cfg["smooth_min_cut"]
            rs.oe_x.beta = rs.oe_y.beta = self.cfg["smooth_beta"]
            for det in (rs.shake, rs.nun_shake):
                det.threshold = self.cfg["shake_threshold"]
                det.reversals = int(self.cfg["shake_reversals"])
                det.gap = self.cfg["shake_gap"]

    # -- remote reports
    def state_for(self, wm):
        rs = self.states.get(wm.slot)
        if rs is None:
            rs = RemoteState(self.cfg)
            self.states[wm.slot] = rs
            if wm not in self.wiimotes:
                self.wiimotes.append(wm)
            try:
                wm.set_led(self._led_mask())
            except Exception:
                pass
        return rs

    def on_frame(self, wm, f):
        with self.lock:
            rs = self.state_for(wm)
            now = f.t
            self._now = now
            if self.owner_slot is None:
                self.owner_slot = wm.slot
            self._run_timers(rs, now)
            acc = tuple((f.acc_raw[i] - wm.acc_zero[i]) / (wm.acc_one[i] - wm.acc_zero[i]) for i in range(3))
            rs.acc_body = (-acc[0], -acc[1], acc[2])           # remote body: x right, y tip, z up
            mag = math.sqrt(acc[0] ** 2 + acc[1] ** 2 + acc[2] ** 2)
            if mag >= rs.acc_peak or now - rs.acc_peak_t > 2.0:    # acceleration peak of the last 2 s (diagnostics)
                rs.acc_peak, rs.acc_peak_t = mag, now
            mp = wl.decode_mp(f) if getattr(wm, "use_mp", False) else None
            if mp:
                rs.mp_seen_t = now
                rs.gyro_dps = rs.gyro.update(mp, now)
            elif self.cfg["gyro_from_accel"] and not getattr(wm, "use_mp", False):
                rs.gyro_dps = rs.accgyro.update(rs.acc_body, now)
            else:
                rs.accgyro.reset()
                rs.gyro_dps = (0.0, 0.0, 0.0)
            if not self.cfg["enabled"]:
                rs.prev_buttons = f.buttons
                return
            b = self.bindings()
            self._buttons(wm, rs, f, now, b)
            self._flush_pending(wm, rs, now, b)
            # shaking is only watched if some direction has an action: with all set to "None" the remote is shaken "for real"
            # (the motion reaches DSU intact and the cursor does not freeze)
            rs.shake_on = self._shake_active(b)
            if rs.shake_on:
                if rs.shake.update(now, self._shake_axes(rs.acc_body)):
                    self._on_shake(wm, rs, b)
            else:
                rs.shake.lp = None
            rs.last_ir = f.ir
            if b.get("Pointer") == "mouse" and wm.slot == self.owner_slot and self.cfg["ir_enabled"]:
                self._pointer(rs, f, now)
            elif not self.cfg["ir_enabled"]:
                rs.ref = None
            if self.mode == "nunchuk" and not getattr(wm, "use_mp", False):
                self._nunchuk(rs, f, now, b)
            self._motion(rs, wm, now, bool(mp))

    def _run_timers(self, rs, now):
        if not rs.timers:
            return
        due = [t for t in rs.timers if t[0] <= now]
        if due:
            rs.timers = [t for t in rs.timers if t[0] > now]
            for _, fn in due:
                fn()

    # -- buttons (members of a chord wait 120 ms in case it is the chord)
    def _try_chord(self, rs, f, now, bit):
        """bit was just pressed: if it completes a chord with another just-pressed button, arms it and returns True."""
        for mask, cname, hold in CHORDS:
            if not mask & bit:
                continue
            partner = mask & ~bit
            if not f.buttons & partner:
                continue
            free = partner in HOLD_FREE and partner in rs.active
            if not (partner in rs.pending or partner in rs.suppressed or (hold != 0.0 and free)):
                continue
            rs.pending.pop(partner, None)
            if free:                                     # the D-pad was already pressed: release it, so it does not keep pushing for 2 s
                self.do_action(rs.active.pop(partner), False)
            rs.suppressed.update((bit, partner))
            if hold == 0.0:
                self._app(cname)
            else:
                rs.holds[cname] = (mask, self.cfg["hold_chord_seconds"] if hold is None else hold, now)
            return True
        return False

    def _buttons(self, wm, rs, f, now, b):
        changed = f.buttons ^ rs.prev_buttons
        rs.prev_buttons = f.buttons
        if not changed:
            return
        for bit, name in wl.BUTTON_NAMES.items():
            if not changed & bit:
                continue
            down = bool(f.buttons & bit)
            if not down and bit in rs.suppressed:
                rs.suppressed.discard(bit)
                continue
            if down and self._try_chord(rs, f, now, bit):
                continue
            if bit in CHORD_MEMBERS:
                if down:
                    rs.pending[bit] = now
                elif bit in rs.pending:        # quick tap: press and release
                    rs.pending.pop(bit)
                    act = b.get(name)
                    self.do_action(act, True)
                    rs.timers.append((now + 0.06, lambda a=act: self.do_action(a, False)))
                elif bit in rs.active:
                    self.do_action(rs.active.pop(bit), False)
                continue
            action = b.get(name)
            if down:
                rs.active[bit] = action
                self.do_action(action, True)
            elif bit in rs.active:
                self.do_action(rs.active.pop(bit), False)
        rs.last_event, rs.last_event_t = "buttons %04X" % f.buttons, now

    def _flush_pending(self, wm, rs, now, b):
        for cname, (mask, hold, t0) in list(rs.holds.items()):      # hold chords
            if (rs.prev_buttons & mask) != mask:
                del rs.holds[cname]
            elif now - t0 >= hold:
                del rs.holds[cname]
                self.log.event("W%d" % (wm.slot + 1), "CHORD", "%s held %.1f s" % (cname, hold))
                self._app(cname)
        if not rs.pending:
            return
        for bit, t in list(rs.pending.items()):
            if now - t >= self.chord_window:
                del rs.pending[bit]
                action = b.get(wl.BUTTON_NAMES[bit])
                rs.active[bit] = action
                self.do_action(action, True)

    # -- shake
    def _shake_active(self, b):
        return bool(self.cfg["shake_enabled"]) and any(split_action(b.get(k)) for k in SHAKE_INPUTS)

    def _shake_axes(self, acc_body):
        """Remote body (x right, y tip, z up) -> (right, other, up) depending on how you hold it."""
        x, y, z = acc_body
        if self.mode == "horizontal":        # sideways, tip to the left, 1/2 on the right: right = -y, up = x
            return (-y, z, x)
        return (x, y, z)

    def _on_shake(self, wm, rs, b):
        axis, sign = rs.shake.fired_axis, rs.shake.fired_sign
        if axis == 0:
            name = "ShakeRight" if (sign > 0) != bool(self.cfg["shake_flip_x"]) else "ShakeLeft"
        elif axis == 2:
            name = "ShakeUp" if (sign > 0) != bool(self.cfg["shake_flip_y"]) else "ShakeDown"
        else:
            return                            # forward/back: no assignable direction
        action = b.get(name)
        if not split_action(action):
            return
        self.pulse(rs, action, 0.12)
        self.log.event("W%d" % (wm.slot + 1), "GESTURE", "%s -> %s" % (INPUT_LABELS[name], action))
        rs.last_event, rs.last_event_t = INPUT_LABELS[name].lower(), time.monotonic()
        try:
            wm.rumble(0.1)
        except Exception:
            pass

    # -- IR pointer -> relative mouse
    def _pointer(self, rs, f, now):
        info = rs.pointer.update(f.ir, now)
        if info is None:
            if now - rs.last_ir_t > 0.25:
                rs.ref = None
                rs.oe_x.reset()
                rs.oe_y.reset()
                rs.last_ptr_t = None
            return
        rs.last_ir_t = now
        rs.last_info = info
        dt = 0.006 if rs.last_ptr_t is None else wl.clamp(now - rs.last_ptr_t, 0.001, 0.1)
        rs.last_ptr_t = now
        x = rs.oe_x.filter(info["ex"] / wl.DEG, dt)
        y = rs.oe_y.filter(info["ez"] / wl.DEG, dt)
        if rs.ref is None:
            rs.ref = (x, y)
            return
        dx, dy = x - rs.ref[0], y - rs.ref[1]
        rs.ref = (x, y)
        if rs.shake_on and rs.shake.moving:
            return
        k = self.cfg["px_per_deg"]
        sx = -1.0 if self.cfg["invert_x"] else 1.0
        sy = -1.0 if self.cfg["invert_y"] else 1.0
        rs.frac[0] += dx * k * sx
        rs.frac[1] += -dy * k * sy
        ix, iy = int(rs.frac[0]), int(rs.frac[1])
        if ix or iy:
            rs.frac[0] -= ix
            rs.frac[1] -= iy
            if self.devices_ok:
                self.mouse.emit([(EV_REL, REL_X, ix), (EV_REL, REL_Y, iy)])

    # -- Nunchuk
    def _nunchuk(self, rs, f, now, b):
        n = wl.decode_nunchuk_plain(f)
        if n is None:
            if now - rs.nun_seen_t > 0.7:
                self._nun_buttons(rs, False, False, b)
                self._nun_stick(rs, 0.0, 0.0, b)
            return
        rs.nun_seen_t = now
        if self.cfg["shake_enabled"] and split_action(b.get("NunShake")):
            if rs.nun_shake.update(now, n["acc"]):
                action = b.get("NunShake")
                self.pulse(rs, action, 0.12)
                self.log.event("APP", "GESTURE", "Nunchuk shaken -> %s" % action)
                rs.last_event, rs.last_event_t = "nunchuk shaken", time.monotonic()
        else:
            rs.nun_shake.lp = None
        if rs.nun_center is None:
            rs.nun_n += 1
            rs.nun_acc[0] += n["sx"]
            rs.nun_acc[1] += n["sy"]
            if rs.nun_n >= 15:
                rs.nun_center = (rs.nun_acc[0] / rs.nun_n, rs.nun_acc[1] / rs.nun_n)
                self.log.event("APP", "NUNCHUK", "Stick center: (%.1f, %.1f)" % rs.nun_center)
            return
        dz = self.cfg["nunchuk_deadzone"]
        sx = wl.clamp((n["sx"] - rs.nun_center[0]) / 95.0, -1, 1)
        sy = wl.clamp((n["sy"] - rs.nun_center[1]) / 95.0, -1, 1)

        def dead(v):
            return 0.0 if abs(v) < dz else (abs(v) - dz) / (1 - dz) * (1 if v > 0 else -1)
        self._nun_stick(rs, dead(sx), dead(sy), b)
        self._nun_buttons(rs, n["c"], n["z"], b)

    def _nun_stick(self, rs, x, y, b):
        rs.nun_x, rs.nun_y = x, y
        target = b.get("NunStick", "lstick")
        if target in ("lstick", "rstick"):
            self.stick_ana[target] = (x, y)
            self._emit_sticks()
        elif target == "hat":
            for name, active in (("left", x < -0.5), ("right", x > 0.5), ("up", y > 0.5), ("down", y < -0.5)):
                key = "hat:" + name
                if active and key not in self.down:
                    self.do_action(key, True)
                elif not active and key in self.down:
                    self.do_action(key, False)

    def _nun_buttons(self, rs, c, z, b):
        if c != rs.nun_c:
            rs.nun_c = c
            self.do_action(b.get("NunC"), c)
        if z != rs.nun_z:
            rs.nun_z = z
            self.do_action(b.get("NunZ"), z)

    # -- gyro: DSU and right stick
    def _motion(self, rs, wm, now, has_gyro=True):
        """Accelerometer always (swaying, shaking); gyro only with MotionPlus. Both go to DSU."""
        preset = "sideways" if self.mode == "horizontal" else "pointer"
        g_in = rs.gyro_dps
        dz = float(self.cfg["gyro_deadzone"])
        if has_gyro and dz > 0:         # soft deadzone: removes slow drift without jumps when rotation starts
            g_in = tuple((abs(v) - dz) * (1 if v > 0 else -1) if abs(v) > dz else 0.0 for v in g_in)
        gain = float(self.cfg["dsu_accel_gain"])
        a_in = tuple(v * gain for v in rs.acc_body) if gain != 1.0 else rs.acc_body
        off = self._eden_offset(now) if wm.slot == self.owner_slot else None
        if off:
            a_in = tuple(a_in[i] + off[0][i] for i in range(3))
            g_in = tuple(g_in[i] + off[1][i] for i in range(3))
        if self.dsu:
            self.dsu.mirror = bool(self.cfg["dsu_mirror"])
        acc, gyro = motion_to_dsu(g_in, a_in, preset, self.cfg["dsu_invert"])
        rs.dsu_acc, rs.dsu_gyro = acc, gyro
        if self.dsu and self.cfg["dsu_enabled"] and wm.slot == self.owner_slot:
            self.dsu.mark_alive()
            self.dsu.push(acc, gyro, self._dsu_pad_state(), now * 1e6)
        if has_gyro and self.cfg["gyro_stick"] and wm.slot == self.owner_slot:
            pitch, roll, yaw_left = rs.gyro_dps
            g = self.cfg["gyro_stick_gain"]
            x = wl.clamp(-yaw_left / 120.0 * g, -1, 1)
            y = wl.clamp(pitch / 120.0 * g, -1, 1)
            if abs(x) < 0.03:
                x = 0.0
            if abs(y) < 0.03:
                y = 0.0
            self.stick_ana["rstick"] = (x, y)
            self._emit_sticks()

    def _dsu_pad_state(self):
        d = self.down

        def has(a):
            return a in d
        lx, ly = self.stick_out["lstick"]
        rx, ry = self.stick_out["rstick"]
        return {"a": has("pad:A"), "b": has("pad:B"), "x": has("pad:X"), "y": has("pad:Y"), "l1": has("pad:TL"), "r1": has("pad:TR"),
                "l2": has("trig:L2"), "r2": has("trig:R2"), "l3": has("pad:THUMBL"), "r3": has("pad:THUMBR"),
                "start": has("pad:START"), "select": has("pad:SELECT"), "home": has("pad:MODE"),
                "up": has("hat:up"), "down": has("hat:down"), "left": has("hat:left"), "right": has("hat:right"),
                "lx": lx / 32767.0, "ly": -ly / 32767.0, "rx": rx / 32767.0, "ry": -ry / 32767.0}


# ----------------------------------------------------------------------------- service
class AlreadyRunning(Exception):
    pass


LOCK_PATH = "/tmp/wimotioncontroldeck.lock"


def free_wiimote_driver(log=None):
    """As root: detaches the kernel hid_wiimote driver from the remotes (it fights with direct reading)."""
    base = "/sys/bus/hid/drivers/hid-wiimote"
    if os.geteuid() != 0 or not os.path.isdir(base):
        return
    for name in os.listdir(base):
        if ":057E:" in name.upper():
            try:
                with open(base + "/unbind", "w") as f:
                    f.write(name)
                if os.path.isdir("/sys/bus/hid/drivers/hid-generic"):
                    with open("/sys/bus/hid/drivers/hid-generic/bind", "w") as f:
                        f.write(name)
                if log:
                    log.event("APP", "HID", "hid_wiimote detached from %s" % name)
            except OSError as e:
                if log:
                    log.event("APP", "HID", "could not detach hid_wiimote from %s: %s" % (name, e))


class DeckService:
    """Ties together configuration, log, controller, DSU server and remotes. Used by the window and the Decky plugin."""

    def __init__(self, pad=None, mouse=None, kbd=None, use_lock=True):
        self.cfg = None
        self.log = None
        self.ctrl = None
        self.dsu = None
        self.mgr = None
        self._lock_fd = None
        self.use_lock = use_lock
        self._fakes = (pad, mouse, kbd)
        self.started = False
        self._overrides = {}
        self._watch_stop = threading.Event()
        self.on_notify = None
        self.on_open_qam = None          # callback for "Home + Plus" (set by the Decky plugin BEFORE start)
    WATCH_PERIOD = 1.0

    def _take_lock(self):
        try:
            fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o666)
            try:
                os.chmod(LOCK_PATH, 0o666)
            except OSError:
                pass
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd = fd
        except BlockingIOError:
            raise AlreadyRunning("Another instance of WimotionControlDeck is already running (the Decky plugin or the app).")
        except OSError:
            pass

    def _release_lock(self):
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    @staticmethod
    def _boot_gap():
        """CLOCK_BOOTTIME counts suspend time and CLOCK_MONOTONIC does not: the difference grows on wake-up."""
        try:
            return time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()
        except (AttributeError, OSError):
            return 0.0

    def _start_watchdog(self):
        self._watch_stop = ev = threading.Event()

        def run():
            last = self._boot_gap()
            while not ev.wait(self.WATCH_PERIOD):
                gap = self._boot_gap()
                if gap - last > 3.0 and self.started:
                    self.log.event("APP", "SUSPEND", "Woke up after %.0f s of suspend: restarting everything" % (gap - last))
                    try:
                        self.restart()
                    except Exception as e:
                        self.log.event("APP", "ERROR", "restart after suspend: %r" % e)
                    return
                last = gap
        threading.Thread(target=run, name="wimotioncontroldeck-watch", daemon=True).start()

    def restart(self):
        """Shuts EVERYTHING down (remotes, virtual devices, DSU) and starts it again, reading the saved configuration."""
        self.stop(release_lock=False)
        self.start()

    def start(self, overrides=None):
        if self.started:
            return
        if overrides is not None:
            self._overrides = dict(overrides)
        overrides = self._overrides
        if self.use_lock and self._lock_fd is None:
            self._take_lock()
        self.cfg = load_config()
        for k, v in (overrides or {}).items():
            if k in self.cfg:
                self.cfg[k] = v
        if self.cfg["profile"] not in profile_ids(self.cfg):
            self.cfg["profile"] = "menus"
        if self.cfg["mode"] not in MODES:
            self.cfg["mode"] = "vertical"
        try:
            makedirs_owned(LOG_DIR)
        except OSError:
            pass
        self.log = wl.EventLog(LOG_DIR, "wimotioncontroldeck")
        self.log.event("APP", "APP", "%s %s started" % (APP_NAME, VERSION))
        free_wiimote_driver(self.log)
        self.dsu = DSUServer(self.cfg["dsu_port"], self.log, extra_ports=(26760, 26761))
        self.dsu.on_client = self._dsu_client_log
        self.dsu.requested_port = self.cfg["dsu_port"]
        if self.cfg["dsu_enabled"]:
            self.dsu.start()
        self.ctrl = DeckController(self.cfg, self.log, *self._fakes, dsu=self.dsu)
        self.ctrl.open_devices()
        self.mgr = wl.Manager(log=self.log, on_frame=self.ctrl.on_frame, use_mp=self.ctrl.want_mp(), ir=True)
        self.ctrl.on_mp_change = lambda want: setattr(self.mgr, "use_mp", want)
        self.ctrl.on_open_qam = self.on_open_qam
        self.ctrl.on_notify = self.on_notify
        self.mgr.start()
        self.started = True
        self._start_watchdog()

    def stop(self, release_lock=True):
        """COMPLETE shutdown: closes the remotes (with rumble off), the virtual devices and DSU.
        The configuration (profiles, bindings, options) is saved and restored on the next start."""
        self._watch_stop.set()
        if not self.started:
            if release_lock:
                self._release_lock()
            return
        self.started = False
        try:
            self.mgr.stop()
            self.ctrl.close_devices()
            self.dsu.stop()
            save_config(self.cfg)
            self.log.event("APP", "APP", "Closing")
            self.log.close()
        finally:
            if release_lock:
                self._release_lock()

    def status(self):
        ctrl, mgr = self.ctrl, self.mgr
        now = time.monotonic()
        remotes = []
        for wm in mgr.wiimotes():
            rs = ctrl.states.get(wm.slot)
            remotes.append({
                "slot": wm.slot + 1, "status": wm.status_text, "battery": wm.battery, "connected": wm.connected,
                "ir": len(rs.last_ir) if rs else 0,
                "nunchuk": bool(rs and now - rs.nun_seen_t < 1.0),
                "gyro": bool(rs and now - rs.mp_seen_t < 1.0),
                "owner": ctrl.owner_slot == wm.slot,
                "last": rs.last_event if rs and now - rs.last_event_t < 3 else "",
            })
        problems = ([ctrl.error] if ctrl.error else []) + list(mgr.problems)
        return {
            "version": VERSION, "enabled": self.cfg["enabled"], "mode": ctrl.mode, "profile": ctrl.profile,
            "devices_ok": ctrl.devices_ok, "hid_seen": mgr.hid_seen, "problems": problems, "remotes": remotes,
            "gyro_enabled": self.cfg["gyro_enabled"], "dsu_enabled": self.cfg["dsu_enabled"],
            "dsu_clients": self.dsu.client_count if self.dsu else 0,
            "dsu_port": self.dsu.port if (self.dsu and self.dsu.sock) else self.cfg["dsu_port"],
            "dsu_ports": ({str(p): {"state": v[0], "owner": v[1]} for p, v in self.dsu.extra_state.items()} if self.dsu else {}),
            "dsu_port_wanted": self.cfg["dsu_port"], "dsu_open": bool(self.dsu and self.dsu.sock),
            "dsu_sent": self.dsu.sent if self.dsu else 0,
            "profile_title": profile_title(self.cfg, ctrl.profile),
            "quick_profiles": list(self.cfg.get("quick_profiles", [])),
            "ir_enabled": self.cfg["ir_enabled"],
            "profiles": [{"id": p, "title": profile_title(self.cfg, p), "custom": p not in BUILTIN_PROFILES} for p in profile_ids(self.cfg)],
            "shake_flip_x": self.cfg["shake_flip_x"], "shake_flip_y": self.cfg["shake_flip_y"],
            "motion": self._motion_view(),
            "px_per_deg": self.cfg["px_per_deg"], "shake_threshold": self.cfg["shake_threshold"],
            "shake_reversals": self.cfg["shake_reversals"], "shake_gap": self.cfg["shake_gap"], "gyro_deadzone": self.cfg["gyro_deadzone"], "notify_enabled": self.cfg["notify_enabled"], "eden_shake_amp": self.cfg["eden_shake_amp"], "eden_shake_gyro": self.cfg["eden_shake_gyro"], "dsu_mirror": self.cfg["dsu_mirror"], "eden_shake_hz": self.cfg["eden_shake_hz"], "eden_shake_cycles": self.cfg["eden_shake_cycles"], "dsu_accel_gain": self.cfg["dsu_accel_gain"], "gyro_from_accel": self.cfg["gyro_from_accel"], "shake_enabled": self.cfg["shake_enabled"],
            "gyro_stick": self.cfg["gyro_stick"], "gyro_stick_gain": self.cfg["gyro_stick_gain"],
            "dsu_invert": self.cfg["dsu_invert"],
        }

    FREEABLE = ("gyro", "dsu")        # only a program whose name or command contains one of these words is stopped

    def free_dsu_port(self, port=26760):
        """Stops (SIGTERM) the program holding a DSU port, e.g. SteamDeckGyroDSU, so WimotionControlDeck can take it. Only if it looks
        like a gyro/DSU server: an arbitrary process is never killed. Returns (ok, message)."""
        own = os.getpid()
        owner = port_owner(port)
        if not owner:
            return False, "Nobody is using port %d" % port
        pid, name, cmd = owner
        if pid == own:
            return False, "Port %d belongs to WimotionControlDeck" % port
        text = (name + " " + cmd).lower()
        if not any(k in text for k in self.FREEABLE):
            return False, "Port %d is used by %s (pid %d) and does not look like a gyro server: not stopping it. Stop it yourself." % (port, name, pid)
        try:
            os.kill(pid, 15)
        except OSError as e:
            return False, "Could not stop %s (pid %d): %s" % (name, pid, e)
        if self.log:
            self.log.event("APP", "DSU", "Stopped %s (pid %d) to free port %d" % (name, pid, port))
        return True, "Stopped %s (pid %d). WimotionControlDeck will take port %d in a few seconds." % (name, pid, port)

    def _dsu_client_log(self):
        """An emulator just connected to DSU: logs what data it is going to receive."""
        ctrl = self.ctrl
        rs = ctrl.states.get(ctrl.owner_slot) if ctrl else None
        if rs is None:
            self.log.event("APP", "DSU", "...but there is no remote with data yet")
            return
        real = ctrl.want_mp()
        if real:
            msg = "real gyro (MotionPlus) + accelerometer"
        elif self.cfg["gyro_from_accel"]:
            msg = "accelerometer + APPROXIMATE gyro (no MotionPlus in %s mode)" % ctrl.mode
        else:
            msg = "accelerometer only (no MotionPlus in %s mode)" % ctrl.mode
        self.log.event("APP", "DSU", "Data the emulator receives: " + msg)

    def _motion_view(self):
        rs = self.ctrl.states.get(self.ctrl.owner_slot)
        if rs is None:
            return {"acc": [0, 0, 0], "gyro": [0, 0, 0], "peak": 0.0}
        return {"acc": [round(v, 2) for v in rs.dsu_acc], "gyro": [round(v, 1) for v in rs.dsu_gyro], "peak": round(rs.acc_peak, 1)}

    def set_option(self, key, value):
        """Like DeckController.set_option, but also starts the DSU server if it is enabled while the program is running."""
        ok = self.ctrl.set_option(key, value)
        if ok and key == "dsu_enabled" and value and self.dsu and self.dsu.sock is None:
            self.dsu.start()
        if ok and key == "dsu_port" and self.dsu:
            self.dsu.set_port(value)
        return ok

    def bindings_view(self, mode=None, profile=None):
        mode = mode or self.ctrl.mode
        profile = profile or self.ctrl.profile
        b = effective_bindings(self.cfg, profile, mode)
        out = []
        for name, label in INPUTS:
            if name == "Pointer":
                options = [{"id": i, "label": l} for i, l in POINTER_CHOICES]
            elif name == "NunStick":
                options = [{"id": i, "label": l} for i, l in STICK_CHOICES]
            else:
                options = None
            out.append({"input": name, "label": label, "value": b.get(name, "none"), "options": options})
        return {"mode": mode, "profile": profile, "inputs": out,
                "actions": [{"id": aid, "label": l, "group": g, "cat": category_of(aid)} for g, items in ACTION_GROUPS for aid, l in items],
                "categories": [c for c, _ in CATEGORIES]}
