"""Tests for the WimotionControlDeck core (deckcore): profiles, bindings, modes, Nunchuk, gyro and DSU server."""
import socket, struct, sys, tempfile, time, zlib
from helpers import *
import deckcore as dc

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ok   ", name)
    else:
        FAIL += 1; print("  FAIL ", name, extra)


dc.save_config = lambda c: None
dc.CONFIG_PATH = "/nonexistent/config.json"


def new(mode="vertical", profile="menus", user_profiles=None):
    cfg = dc.load_config()
    cfg["mode"], cfg["profile"] = mode, profile
    cfg["profiles"] = user_profiles or {}
    log = wl.EventLog(tempfile.mkdtemp(), "t")
    pad, mouse, kbd = FakeUInput(), FakeUInput(), FakeUInput()
    c = dc.DeckController(cfg, log, pad, mouse, kbd)
    c.open_devices()
    return c, pad, mouse, kbd


def feed(c, wm, frames, t0=100.0, dt=0.006):
    t = t0
    for rep in frames:
        c.on_frame(wm, wl.parse_data_report(rep, t)); t += dt
    return t


def tap(c, wm, btn, t, hold=40):
    return feed(c, wm, [make_report(btn)] * hold + [make_report(0)] * 5, t)


def nun_ext(sx=131, sy=125, z=False, c_=False):
    return (sx, sy, 128, 128, 154, 0xFC | (0 if z else 1) | (0 if c_ else 2))


def mp_ext(yaw=8192, roll=8192, pitch=8192):
    """MotionPlus frame (standalone mode) with all three axes in "slow" mode."""
    return (yaw & 0xFF, roll & 0xFF, pitch & 0xFF,
            ((yaw >> 8) << 2) | 0x02 | 0x01, ((roll >> 8) << 2) | 0x02 | 0x01, ((pitch >> 8) << 2) | 0x02)


# ----------------------------------------------------------------- horizontal mode
print("horizontal: the D-pad is the left stick")
c, pad, mouse, kbd = new("horizontal"); wm = FakeWm()
t = tap(c, wm, wl.BTN_UP, 100.0)
xs = pad.where(dc.EV_ABS, dc.ABS_X)
check("Up (remote held sideways) -> left stick to the left", xs and min(xs) <= -32000, xs)
check("...and does NOT touch the digital D-pad", not pad.where(dc.EV_ABS, dc.ABS_HAT0X) and not pad.where(dc.EV_ABS, dc.ABS_HAT0Y))
check("...and returns to 0 on release", xs[-1] == 0, xs)
pad.events.clear()
t = tap(c, wm, wl.BTN_RIGHT, t)
ys = pad.where(dc.EV_ABS, dc.ABS_Y)
check("Right -> stick up (negative Y on the gamepad)", ys and min(ys) <= -32000, ys)
pad.events.clear()
t = tap(c, wm, wl.BTN_DOWN, t)
check("Down -> stick to the right", max(pad.where(dc.EV_ABS, dc.ABS_X)) >= 32000)
pad.events.clear()
t = tap(c, wm, wl.BTN_LEFT, t)
check("Left -> stick down", max(pad.where(dc.EV_ABS, dc.ABS_Y)) >= 32000)
pad.events.clear()
t = feed(c, wm, [make_report(wl.BTN_UP | wl.BTN_RIGHT)] * 5, t)
xs, ys = pad.where(dc.EV_ABS, dc.ABS_X), pad.where(dc.EV_ABS, dc.ABS_Y)
check("diagonal normalized (magnitude <= 1)", xs and ys and (xs[-1] ** 2 + ys[-1] ** 2) ** 0.5 <= 32768 * 1.001, (xs[-1], ys[-1]))

# ----------------------------------------------------------------- bindings and profiles
print("bindings")
c, pad, mouse, kbd = new("vertical", "menus"); wm = FakeWm()
t = tap(c, wm, wl.BTN_A, 100.0)
check("Steam Menus profile: A = left click", mouse.where(dc.EV_KEY, 0x110) == [1, 0])
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
t = tap(c, wm, wl.BTN_A, 100.0)
check("Games profile: A = gamepad A button", pad.where(dc.EV_KEY, 0x130) == [1, 0] and not mouse.where(dc.EV_KEY, 0x110))
t = tap(c, wm, wl.BTN_B, t)
check("Games profile: B = R2 trigger", 255 in pad.where(dc.EV_ABS, dc.ABS_RZ) and pad.where(dc.EV_ABS, dc.ABS_RZ)[-1] == 0)

c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
check("set_binding accepts a valid action", c.set_binding("A", "pad:Y") is True)
check("set_binding rejects a made-up action", c.set_binding("A", "pad:NOEXISTE") is False)
check("set_binding rejects a made-up input", c.set_binding("Zzz", "pad:A") is False)
t = tap(c, wm, wl.BTN_A, 100.0)
check("A remapped to Y works", pad.where(dc.EV_KEY, 0x134) == [1, 0] and not pad.where(dc.EV_KEY, 0x130))
c.set_binding("A", "key:ENTER")
t = tap(c, wm, wl.BTN_A, t)
check("A remapped to a key (Enter) works", kbd.where(dc.EV_KEY, 28) == [1, 0])
c.set_binding("A", "mouse:RIGHT")
t = tap(c, wm, wl.BTN_A, t)
check("A remapped to right click works", mouse.where(dc.EV_KEY, 0x111) == [1, 0])
check("the binding only applies to the edited mode/profile", dc.effective_bindings(c.cfg, "menus", "vertical")["A"] == "mouse:LEFT"
      and dc.effective_bindings(c.cfg, "juego", "horizontal")["A"] == "pad:X")
c.reset_bindings()
check("reset_bindings restores the factory defaults", c.bindings()["A"] == "pad:A")
check("Pointer only accepts mouse/none", c.set_binding("Pointer", "none") and not c.set_binding("Pointer", "pad:A"))
check("NunStick only accepts stick/D-pad/none", c.set_binding("NunStick", "rstick") and not c.set_binding("NunStick", "mouse:LEFT"))

# user-saved bindings are loaded
c, pad, mouse, kbd = new("vertical", "juego", {"juego": {"vertical": {"Plus": "pad:Y"}}}); wm = FakeWm()
t = tap(c, wm, wl.BTN_PLUS, 100.0)
check("user config: + = Y", pad.where(dc.EV_KEY, 0x134) == [1, 0])

# pointer can be disabled by binding
c, pad, mouse, kbd = new("vertical", "menus", {"menus": {"vertical": {"Pointer": "none"}}}); wm = FakeWm()
dots = [(450, 384), (570, 384)]
t = feed(c, wm, [make_report(dots=dots)] * 100)
t = feed(c, wm, [make_report(dots=[(380, 384), (500, 384)])] * 100, t)
check("Pointer = none: IR does not move the cursor", not mouse.where(dc.EV_REL, dc.REL_X))

# ----------------------------------------------------------------- Nunchuk: C and Z are distinct
print("nunchuk")
c, pad, mouse, kbd = new("nunchuk", "menus"); wm = FakeWm()
t = feed(c, wm, [make_report(ext=nun_ext())] * 40)
t = feed(c, wm, [make_report(ext=nun_ext(c_=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
check("C by default = L1", pad.where(dc.EV_KEY, 0x136) == [1, 0])
t = feed(c, wm, [make_report(ext=nun_ext(z=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
check("Z by default = L2 (distinct from C)", pad.where(dc.EV_ABS, dc.ABS_Z)[:2] == [255, 0] and pad.where(dc.EV_KEY, 0x136) == [1, 0])
c.set_binding("NunC", "pad:X"); c.set_binding("NunZ", "pad:Y")
t = feed(c, wm, [make_report(ext=nun_ext(c_=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
t = feed(c, wm, [make_report(ext=nun_ext(z=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
check("C and Z are remappable (C=X, Z=Y)", pad.where(dc.EV_KEY, 0x133) == [1, 0] and pad.where(dc.EV_KEY, 0x134) == [1, 0])
c.set_binding("NunStick", "rstick")
t = feed(c, wm, [make_report(ext=nun_ext(sx=131 + 95))] * 5, t)
check("Nunchuk stick -> right stick when assigned", pad.where(dc.EV_ABS, dc.ABS_RX) and pad.where(dc.EV_ABS, dc.ABS_RX)[-1] > 30000)

# ----------------------------------------------------------------- master switch and profiles
print("master switch and profiles")
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_A)] * 3, 100.0)
c.set_enabled(False)
check("disabling releases whatever is pressed", pad.where(dc.EV_KEY, 0x130) == [1, 0], pad.where(dc.EV_KEY, 0x130))
n = len(pad.events)
t = feed(c, wm, [make_report(0)] * 3 + [make_report(wl.BTN_A)] * 10 + [make_report(0)] * 3, t)
check("disabled: the remote generates nothing", len(pad.events) == n and not mouse.events)
c.set_enabled(True)
t = tap(c, wm, wl.BTN_A, t)
check("re-enabled: works again", pad.where(dc.EV_KEY, 0x130)[-2:] == [1, 0] and len(pad.where(dc.EV_KEY, 0x130)) == 4)
c, pad, mouse, kbd = new("vertical", "menus"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_PLUS | wl.BTN_MINUS)] * 30 + [make_report(0)] * 5, 100.0)
check("+ and - together switch profile", c.profile == "juego", c.profile)
check("the chord does not press Start/Select", not pad.where(dc.EV_KEY, 0x13B) and not pad.where(dc.EV_KEY, 0x13A))
check("LED4 indicates the Games profile", wm.leds[-1] & 0b1000, wm.leds)

# ----------------------------------------------------------------- gyroscope
print("gyroscope")
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm(); wm.use_mp = True
c.cfg["gyro_stick"] = True
t = feed(c, wm, [make_report(ext=mp_ext())] * 20)
check("MotionPlus still: right stick at 0", not pad.where(dc.EV_ABS, dc.ABS_RY) or pad.where(dc.EV_ABS, dc.ABS_RY)[-1] == 0)
t = feed(c, wm, [make_report(ext=mp_ext(pitch=8192 + 2000))] * 5, t)
ry = pad.where(dc.EV_ABS, dc.ABS_RY)
check("raising the tip (pitch+) -> right stick up (negative Y)", ry and ry[-1] < -20000, ry[-3:])
c.cfg["gyro_stick"] = False
c.stick_ana["rstick"] = (0.0, 0.0); c._emit_sticks()
pad.events.clear()
t = feed(c, wm, [make_report(ext=mp_ext(pitch=8192 + 2000))] * 5, t)
check("gyro_stick off: the right stick does not move", not pad.where(dc.EV_ABS, dc.ABS_RY))
check("want_mp: vertical yes, nunchuk no", c.want_mp() and (c.set_mode("nunchuk") or True) and not c.want_mp())

# ----------------------------------------------------------------- DSU
print("DSU (motion for emulators)")
PORT = 26791
srv = dc.DSUServer(PORT, None)
check("the DSU server starts", srv.start())
cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
cli.settimeout(1.0)


def creq(mtype, payload=b""):
    body = struct.pack("<I", mtype) + payload
    pkt = b"DSUC" + struct.pack("<HHII", dc.DSU_VERSION, len(body), 0, 1234) + body
    return pkt[:8] + struct.pack("<I", zlib.crc32(pkt) & 0xFFFFFFFF) + pkt[12:]


def valid(pkt):
    b = bytearray(pkt); crc = struct.unpack("<I", bytes(b[8:12]))[0]; b[8:12] = bytes(4)
    return pkt[:4] == b"DSUS" and zlib.crc32(bytes(b)) & 0xFFFFFFFF == crc


cli.sendto(creq(dc.MSG_VERSION), ("127.0.0.1", PORT))
r = cli.recv(256)
check("answers the version request with a correct CRC", valid(r) and struct.unpack("<I", r[16:20])[0] == dc.MSG_VERSION)
srv.connected = True
cli.sendto(creq(dc.MSG_INFO, struct.pack("<i", 1) + bytes([0, 0, 0, 0])), ("127.0.0.1", PORT))
r = cli.recv(256)
check("reports remote 0 as connected", valid(r) and r[21] == 2, r[16:32].hex())
cli.sendto(creq(dc.MSG_DATA, bytes([0, 0]) + bytes(6)), ("127.0.0.1", PORT))
time.sleep(0.2)
check("registers the client", srv.client_count == 1)
srv.push((0.0, 0.0, 1.0), (10.0, 20.0, 30.0), {"a": True}, 5_000_000)
r = cli.recv(256)
vals = struct.unpack("<Q6f", r[-32:])
check("valid data packet with accel+gyro", valid(r) and len(r) == 100 and abs(vals[4] - 10.0) < 1e-4 and abs(vals[6] - 30.0) < 1e-4 and abs(vals[3] - 1.0) < 1e-4, (len(r), vals))
check("the A button arrives in the buttons byte", r[37] & 0x20, r[37])
srv.stop(); cli.close()

# integration: the remote in vertical mode with MotionPlus feeds the DSU server
srv = dc.DSUServer(PORT + 1, None); srv.start()
c, pad, mouse, kbd = new("vertical", "juego"); c.dsu = srv
wm = FakeWm(); wm.use_mp = True
cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); cli.settimeout(1.0)
cli.sendto(creq(dc.MSG_DATA, bytes([0, 0]) + bytes(6)), ("127.0.0.1", PORT + 1)); time.sleep(0.2)
t = feed(c, wm, [make_report(ext=mp_ext())] * 20)
pk = None
for i in range(30):                      # the server limits to ~250 packets/s: feed it at a realistic rate
    t = feed(c, wm, [make_report(ext=mp_ext(yaw=8192 + 1000))], t)
    time.sleep(0.006)
try:
    while True:
        pk = cli.recv(256)
        cli.settimeout(0.05)
except socket.timeout:
    pass
g = struct.unpack("<Q6f", pk[-32:])[4:] if pk else None
check("DeckController -> DSU: the gyro reaches the emulator", g is not None and max(abs(x) for x in g) > 20.0, g)
srv.stop(); cli.close()

# ----------------------------------------------------------------- button combinations (A + B ...)
print("combinations")
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
check("A + B is a valid binding", c.set_binding("A", "pad:A+pad:B") is True)
check("three and four buttons too", c.set_binding("B", "pad:A+pad:B+pad:X") and c.set_binding("B", "pad:A+pad:B+pad:X+pad:Y"))
check("five buttons no (maximum 4)", c.set_binding("B", "pad:A+pad:B+pad:X+pad:Y+pad:TL") is False)
check("'None' is not mixed with others", c.set_binding("B", "pad:A+none") is False and c.set_binding("B", "none"))
check("one made-up piece invalidates the whole combination", c.set_binding("B", "pad:A+pad:NOPE") is False)
check("the pointer does not accept combinations", c.set_binding("Pointer", "mouse+none") is False)
c.set_binding("A", "pad:A+pad:B+key:ENTER")
t = tap(c, wm, wl.BTN_A, 100.0)
check("A -> A+B+Enter: all three are pressed", pad.where(dc.EV_KEY, 0x130)[:1] == [1] and pad.where(dc.EV_KEY, 0x131)[:1] == [1] and kbd.where(dc.EV_KEY, 28)[:1] == [1])
check("...and all three are released", pad.where(dc.EV_KEY, 0x130) == [1, 0] and pad.where(dc.EV_KEY, 0x131) == [1, 0] and kbd.where(dc.EV_KEY, 28) == [1, 0])
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
c.set_binding("A", "pad:X"); c.set_binding("One", "pad:X"); c.set_binding("Two", "none")
t = feed(c, wm, [make_report(wl.BTN_A)] * 3, 100.0)
t = feed(c, wm, [make_report(wl.BTN_A | wl.BTN_ONE)] * 40, t)
t = feed(c, wm, [make_report(wl.BTN_ONE)] * 3, t)
check("two inputs with the same button: releasing one does not release it", pad.where(dc.EV_KEY, 0x133) == [1], pad.where(dc.EV_KEY, 0x133))
t = feed(c, wm, [make_report(0)] * 3, t)
check("...it is released when the last one is released", pad.where(dc.EV_KEY, 0x133) == [1, 0], pad.where(dc.EV_KEY, 0x133))
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
c.set_binding("A", "app:toggle_gyro+pad:A"); g0 = c.cfg["gyro_enabled"]
t = tap(c, wm, wl.BTN_A, 100.0)
check("a combination can include program actions", c.cfg["gyro_enabled"] != g0 and pad.where(dc.EV_KEY, 0x130) == [1, 0])
check("split/join of actions", dc.split_action("pad:A+pad:B") == ["pad:A", "pad:B"] and dc.join_actions(["pad:A", "none", "pad:B"]) == "pad:A+pad:B" and dc.join_actions([]) == "none")

# ----------------------------------------------------------------- custom profiles
print("custom profiles")
c, pad, mouse, kbd = new("vertical", "menus"); wm = FakeWm()
pid = c.create_profile("  My   profile  ")
check("creating a profile returns an id and stores the cleaned name", pid and c.cfg["custom_profiles"][pid] == "My profile", c.cfg["custom_profiles"])
check("it appears after the two factory profiles", dc.profile_ids(c.cfg) == ["menus", "juego", pid])
check("empty name rejected", c.create_profile("   ") is None and c.create_profile("") is None)
pid2 = c.create_profile("my PROFILE")
check("duplicate name is renamed with a number", c.cfg["custom_profiles"][pid2] == "my PROFILE 2", c.cfg["custom_profiles"])
blank = dc.effective_bindings(c.cfg, pid, "vertical")
check("the new profile starts BLANK (everything set to None)", all(v == "none" for v in blank.values()) and set(blank) == set(dict(dc.INPUTS)), blank)
c.set_profile(pid)
check("it can be activated", c.profile == pid)
pad.events.clear(); mouse.events.clear(); kbd.events.clear()    # on profile change the axes are released to 0
t = tap(c, wm, wl.BTN_A, 100.0); t = tap(c, wm, wl.BTN_B, t); t = tap(c, wm, wl.BTN_HOME, t)
check("blank: no button does anything", not pad.events and not mouse.events and not kbd.events)
dots = [(450, 384), (570, 384)]
t = feed(c, wm, [make_report(dots=dots)] * 100, t); t = feed(c, wm, [make_report(dots=[(380, 384), (500, 384)])] * 100, t)
check("blank: the pointer does not move the cursor either", not mouse.events)
c.set_binding("A", "pad:Y")
t = tap(c, wm, wl.BTN_A, t)
check("buttons can be assigned to it", pad.where(dc.EV_KEY, 0x134) == [1, 0])
check("bindings of a custom profile do not touch the factory ones", dc.effective_bindings(c.cfg, "juego", "vertical")["A"] == "pad:A")
check("set_binding on a nonexistent profile is rejected", c.set_binding("A", "pad:A", "vertical", "p99") is False)
check("set_profile to a nonexistent one is ignored", (c.set_profile("p99") or True) and c.profile == pid)
c.set_quick_profiles(["menus", pid, pid2])      # by default custom profiles do NOT rotate: they are added by hand
t = feed(c, wm, [make_report(wl.BTN_PLUS | wl.BTN_MINUS)] * 30 + [make_report(0)] * 5, t)
check("+ and - cycle through the custom profiles included in quick access (next: the second)", c.profile == pid2, c.profile)
t = feed(c, wm, [make_report(wl.BTN_PLUS | wl.BTN_MINUS)] * 30 + [make_report(0)] * 5, t)
check("...and then returns to Steam Menus", c.profile == "menus", c.profile)
check("LED 4 on custom profiles", (c.set_profile(pid) or True) and wm.leds[-1] & 0b1000, wm.leds)
check("deleting a factory profile is rejected", c.delete_profile("menus") is False and c.delete_profile("juego") is False)
check("deleting the active profile returns to Steam Menus", c.delete_profile(pid) and c.profile == "menus" and pid not in c.cfg["custom_profiles"] and pid not in c.cfg["profiles"])
for k in range(20):
    c.create_profile("x%d" % k)
check("there is a maximum number of profiles", len(c.cfg["custom_profiles"]) <= dc.MAX_CUSTOM_PROFILES, len(c.cfg["custom_profiles"]))
# they are saved and reloaded
import json, os
cfgfile = os.path.join(tempfile.mkdtemp(), "config.json")
json.dump({"custom_profiles": {"p1": "Zelda"}, "profile": "p1", "profiles": {"p1": {"vertical": {"A": "pad:X+pad:Y"}}}}, open(cfgfile, "w"))
dc.CONFIG_PATH = cfgfile
cfg = dc.load_config()
check("config with a custom profile loads", cfg["profile"] == "p1" and dc.profile_title(cfg, "p1") == "Zelda" and dc.effective_bindings(cfg)["A"] == "pad:X+pad:Y")
json.dump({"custom_profiles": {"p1": "Zelda"}, "profile": "p7"}, open(cfgfile, "w"))
check("vanished active profile -> Steam Menus", dc.load_config()["profile"] == "menus")
json.dump({"dsu_port": 26760}, open(cfgfile, "w"))
check("migration: DSU port 26760 stays 26760", dc.load_config()["dsu_port"] == 26760)
json.dump({"dsu_port": 26761, "config_version": 3}, open(cfgfile, "w"))
check("migration: 26761 from v0.4-0.6 goes back to 26760 (the emulators' port)", dc.load_config()["dsu_port"] == 26760)
json.dump({"dsu_port": 26770, "config_version": 3}, open(cfgfile, "w"))
check("a manually chosen port is respected", dc.load_config()["dsu_port"] == 26770)
dc.CONFIG_PATH = "/nonexistent/config.json"

# ----------------------------------------------------------------- directional shake
print("directional shake")
import math


def shake(mode, axis, sign, profile="menus", prep=None):
    """Remote at rest, then 1.2 s of shaking on the RAW axis 'axis' (0=x,1=y,2=z) starting towards 'sign'."""
    c, pad, mouse, kbd = new(mode, profile); wm = FakeWm()
    if prep:
        prep(c)
    t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 300)
    out = []
    for i in range(200):
        a = sign * 1.6 * math.sin(2 * math.pi * 5.0 * i * 0.006)
        v = [128, 128, 154]
        v[axis] = max(0, min(255, int(round(v[axis] + 26 * a))))
        out.append(make_report(acc=tuple(v)))
    t = feed(c, wm, out, t)
    t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 40, t)
    return c, pad, kbd


def pressed(pad, code):
    return pad.where(dc.EV_KEY, code)[:2] == [1, 0]


c, pad, kbd = shake("vertical", 0, -1)
check("vertical: shake RIGHT -> R1 (list scrolls left)", pressed(pad, 0x137) and not pad.where(dc.EV_KEY, 0x136))
c, pad, kbd = shake("vertical", 0, +1)
check("vertical: shake LEFT -> L1", pressed(pad, 0x136) and not pad.where(dc.EV_KEY, 0x137))
c, pad, kbd = shake("vertical", 2, +1, prep=lambda c: c.set_binding("ShakeUp", "pad:A"))
check("vertical: shake UP -> whatever is assigned to Up", pressed(pad, 0x130) and not pad.where(dc.EV_KEY, 0x136) and not pad.where(dc.EV_KEY, 0x137), pad.events[:6])
c, pad, kbd = shake("vertical", 2, -1, prep=lambda c: c.set_binding("ShakeDown", "key:ESC"))
check("vertical: shake DOWN -> whatever is assigned to Down", kbd.where(dc.EV_KEY, 1)[:2] == [1, 0])
c, pad, kbd = shake("vertical", 2, +1)
check("up/down have no factory action (they do nothing)", not pad.events and not kbd.events)
c, pad, kbd = shake("vertical", 1, +1, prep=lambda c: c.set_binding("ShakeUp", "pad:A"))
check("shaking forward/back triggers no direction", not pad.where(dc.EV_KEY, 0x130) and not pad.where(dc.EV_KEY, 0x136))
c, pad, kbd = shake("horizontal", 1, +1)       # sideways: right is the raw y axis (+)
check("horizontal: shake right -> R1", pressed(pad, 0x137) and not pad.where(dc.EV_KEY, 0x136), pad.events[:4])
c, pad, kbd = shake("horizontal", 1, -1)
check("horizontal: shake left -> L1", pressed(pad, 0x136))
c, pad, kbd = shake("horizontal", 0, -1, prep=lambda c: c.set_binding("ShakeUp", "pad:A"))
check("horizontal: shake up", pressed(pad, 0x130))
c, pad, kbd = shake("vertical", 0, -1, prep=lambda c: c.cfg.update(shake_flip_x=True))
check("shake_flip_x swaps left/right", pressed(pad, 0x136) and not pad.where(dc.EV_KEY, 0x137))
c, pad, kbd = shake("vertical", 2, +1, prep=lambda c: (c.cfg.update(shake_flip_y=True), c.set_binding("ShakeDown", "pad:B")))
check("shake_flip_y swaps up/down", pressed(pad, 0x131))
c, pad, kbd = shake("vertical", 0, -1, prep=lambda c: c.set_binding("ShakeRight", "pad:A+pad:B"))
check("a shake direction can be a combination", pressed(pad, 0x130) and pressed(pad, 0x131))

print("real shaking (everything set to None)")


def none_all(c):
    for k in dc.SHAKE_INPUTS:
        c.set_binding(k, "none")


c, pad, kbd = shake("vertical", 0, -1, prep=none_all)
check("with all 4 directions set to None no button comes out", not pad.where(dc.EV_KEY, 0x136) and not pad.where(dc.EV_KEY, 0x137))
rs = c.states[0]
check("...and the detector is turned off", rs.shake_on is False)
# the cursor does NOT freeze while shaking
c, pad, mouse, kbd = new("vertical", "menus"); none_all(c); wm = FakeWm()
dots = lambda dx: [(450 - dx, 384), (570 - dx, 384)]
t = feed(c, wm, [make_report(dots=dots(0), acc=(128, 128, 154))] * 200)
mouse.events.clear()
t = feed(c, wm, [make_report(dots=dots(i // 3), acc=(int(128 + 26 * 2 * math.sin(i / 3.0)), 128, 154)) for i in range(150)], t)
check("with no shake assigned the cursor keeps moving even when you shake", abs(sum(mouse.where(dc.EV_REL, dc.REL_X))) > 20, sum(mouse.where(dc.EV_REL, dc.REL_X)))
c, pad, mouse, kbd = new("vertical", "menus"); wm = FakeWm()
t = feed(c, wm, [make_report(dots=dots(0), acc=(128, 128, 154))] * 200)
mouse.events.clear()
t = feed(c, wm, [make_report(dots=dots(i // 3), acc=(int(128 + 26 * 2 * math.sin(i / 3.0)), 128, 154)) for i in range(150)], t)
check("(with shake assigned, the cursor freezes as before)", abs(sum(mouse.where(dc.EV_REL, dc.REL_X))) < 20, sum(mouse.where(dc.EV_REL, dc.REL_X)))
c, pad, kbd = shake("vertical", 0, -1, prep=lambda c: c.cfg.update(shake_enabled=False))
check("shake_enabled=False turns it off too", not pad.where(dc.EV_KEY, 0x137))

# ----------------------------------------------------------------- DSU: busy port, connection and accelerometer without MotionPlus
print("DSU: port and connection")
blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); blocker.bind(("127.0.0.1", 26830))
srv = dc.DSUServer(26830, None)
check("with the port taken by another program the next one is used", srv.start() and srv.port == 26831 and srv.requested_port == 26830, srv.port)
srv.stop()
blocker2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
blocker2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); blocker2.bind(("127.0.0.1", 26840))
srv = dc.DSUServer(26840, None)
check("even if the other program uses SO_REUSEADDR the port is not shared", srv.start() and srv.port == 26841, srv.port)
srv.stop(); blocker.close(); blocker2.close()
srv = dc.DSUServer(26850, None); srv.start()
check("DSUServer.set_port changes port on the fly", (srv.set_port(26860) or True) and srv.sock and srv.port == 26860)
srv.stop()
srv = dc.DSUServer(26870, None); srv.start()
check("with no data from the remote the server does not announce itself as connected", srv.alive is False)
cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); cli.settimeout(1.0)
cli.sendto(creq(dc.MSG_INFO, struct.pack("<i", 1) + bytes([0, 0, 0, 0])), ("127.0.0.1", 26870))
r = cli.recv(256); check("...and tells the emulator (state 0)", r[21] == 0, r[21])
srv.mark_alive()
cli.sendto(creq(dc.MSG_INFO, struct.pack("<i", 1) + bytes([0, 0, 0, 0])), ("127.0.0.1", 26870))
r = cli.recv(256); check("with an active remote it does (state 2)", r[21] == 2, r[21])
srv.stop(); cli.close()

# accelerometer only: without MotionPlus (Nunchuk mode) motion still arrives and the remote shows as connected
srv = dc.DSUServer(26880, None); srv.start()
c, pad, mouse, kbd = new("nunchuk", "menus"); c.dsu = srv
wm = FakeWm()                                           # use_mp False
cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); cli.settimeout(1.0)
cli.sendto(creq(dc.MSG_DATA, bytes([0, 0]) + bytes(6)), ("127.0.0.1", 26880)); time.sleep(0.2)
pk = None
for i in range(40):
    t = feed(c, wm, [make_report(acc=(128, 128, 128 + 26))], 100.0 + i * 0.01)
    time.sleep(0.006)
try:
    while True:
        pk = cli.recv(256); cli.settimeout(0.05)
except socket.timeout:
    pass
vals = struct.unpack("<Q6f", pk[-32:]) if pk else None
check("without MotionPlus the accelerometer reaches the DSU (z ~ 1 g)", vals is not None and abs(vals[2] - -1.0) < 0.2 or (vals is not None and abs(abs(vals[2]) - 1.0) < 0.2), vals)
check("...with the gyro at zero", vals is not None and max(abs(x) for x in vals[4:]) < 0.01, vals)
check("...and the server counts the packets sent", srv.sent > 0 and srv.alive)
srv.stop(); cli.close()

# ----------------------------------------------------------------- hold chords: IR and QAM menu
print("hold chords")
def held(c, wm, mask, secs, t, dt=0.01):
    return feed(c, wm, [make_report(mask)] * int(secs / dt), t, dt=dt)

c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
check("IR is active by default", c.cfg["ir_enabled"] is True)
t = held(c, wm, wl.BTN_DOWN | wl.BTN_PLUS, 1.0, 100.0)
check("Down + Plus held 1 s: does nothing yet", c.cfg["ir_enabled"] is True)
t = held(c, wm, wl.BTN_DOWN | wl.BTN_PLUS, 1.3, t)
check("Down + Plus held 2 s -> IR pointer disabled", c.cfg["ir_enabled"] is False)
check("...without pressing Menu (Plus) or leaving the D-pad pressed", not pad.where(dc.EV_KEY, 0x13B) and pad.where(dc.EV_ABS, dc.ABS_HAT0Y)[-1:] != [1], (pad.where(dc.EV_KEY, 0x13B), pad.where(dc.EV_ABS, dc.ABS_HAT0Y)))
check("...and signals by rumbling", wm.rumbles >= 1)
t = feed(c, wm, [make_report(0)] * 10, t)
t = held(c, wm, wl.BTN_DOWN | wl.BTN_PLUS, 2.2, t)
check("repeating it enables it again", c.cfg["ir_enabled"] is True)
t = feed(c, wm, [make_report(0)] * 10, t)
# release before 2 s: nothing, and Plus does not leak through as Menu
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
t = held(c, wm, wl.BTN_DOWN | wl.BTN_PLUS, 0.8, 100.0)
t = feed(c, wm, [make_report(0)] * 30, t)
check("releasing early does not change IR", c.cfg["ir_enabled"] is True)
check("...nor leaves the Menu button pressed", pad.where(dc.EV_KEY, 0x13B)[-1:] != [1])
# the D-pad alone still has no delay
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
feed(c, wm, [make_report(wl.BTN_DOWN)] * 2, 100.0)
check("the D-pad alone is pressed instantly (without waiting for chords)", 1 in pad.where(dc.EV_ABS, dc.ABS_HAT0Y))
# with IR off the cursor does not move, but A still clicks
c, pad, mouse, kbd = new("vertical", "menus"); wm = FakeWm(); c.cfg["ir_enabled"] = False
dots = lambda dx: [(450 - dx, 384), (570 - dx, 384)]
t = feed(c, wm, [make_report(dots=dots(0))] * 200)
t = feed(c, wm, [make_report(dots=dots(i // 3)) for i in range(150)], t)
check("IR off: the cursor does not move", not mouse.where(dc.EV_REL, dc.REL_X))
t = tap(c, wm, wl.BTN_A, t)
check("...but A still clicks", mouse.where(dc.EV_KEY, 0x110) == [1, 0])
c.cfg["ir_enabled"] = True
t = feed(c, wm, [make_report(dots=dots(0))] * 100, t)
t = feed(c, wm, [make_report(dots=dots(i // 3)) for i in range(150)], t)
check("IR re-enabled: the cursor moves again", abs(sum(mouse.where(dc.EV_REL, dc.REL_X))) > 20)
# Home + Plus -> QAM
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
calls = []; c.on_open_qam = lambda: calls.append(1)
t = held(c, wm, wl.BTN_HOME | wl.BTN_PLUS, 1.0, 100.0)
check("Home + Plus 1 s: does not open the menu yet", not calls)
t = held(c, wm, wl.BTN_HOME | wl.BTN_PLUS, 1.3, t)
check("Home + Plus 2 s -> opens the ... menu (plugin callback)", calls == [1], calls)
check("...without pressing the Steam or Menu button", not pad.where(dc.EV_KEY, 0x13C) and not pad.where(dc.EV_KEY, 0x13B))
t = held(c, wm, wl.BTN_HOME | wl.BTN_PLUS, 3.0, t)
check("holding longer does not repeat it", calls == [1], calls)
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()          # without plugin: Steam + A
t = held(c, wm, wl.BTN_HOME | wl.BTN_PLUS, 2.3, 100.0)
time.sleep(0.4)
check("without the Decky plugin it sends Steam + A", pad.where(dc.EV_KEY, 0x13C)[:1] == [1] and pad.where(dc.EV_KEY, 0x130)[:1] == [1], (pad.where(dc.EV_KEY, 0x13C), pad.where(dc.EV_KEY, 0x130)))
check("...and releases them", pad.where(dc.EV_KEY, 0x13C)[-1:] == [0] and pad.where(dc.EV_KEY, 0x130)[-1:] == [0])
# Home alone is still Guide, + and - still switch profile, Plus alone is still Menu
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_PLUS)] * 15 + [make_report(0)] * 15, 100.0)
check("Plus alone = Menu (Start)", pad.where(dc.EV_KEY, 0x13B) == [1, 0])
t = feed(c, wm, [make_report(wl.BTN_PLUS | wl.BTN_MINUS)] * 30 + [make_report(0)] * 5, t)
check("+ and - still switch profile", c.profile != "juego")
# assignable to any button
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
c.set_binding("A", "app:toggle_pointer"); t = tap(c, wm, wl.BTN_A, 100.0)
check("'IR pointer on/off' can be assigned to a button", c.cfg["ir_enabled"] is False)
check("'Open QAM menu' exists as an assignable action", c.set_binding("B", "app:open_qam"))

# ----------------------------------------------------------------- shaking the Nunchuk
print("nunchuk shake")
def nun_acc_ext(ax):
    """Nunchuk ext with X acceleration (10 bits, zero 512, 1 g = 200) and the stick centered."""
    v = max(0, min(1023, int(512 + 200 * ax)))
    return (128, 128, v >> 2, 154, 154, 0xFF & ((v & 3) << 2 | 0x03 | 0xC0 & 0))
def nun_shake(bind=None, secs=1.2, amp=2.0):
    c, pad, mouse, kbd = new("nunchuk", "juego"); wm = FakeWm()
    if bind:
        c.set_binding("NunShake", bind)
    t = feed(c, wm, [make_report(ext=nun_acc_ext(0))] * 200)
    fr = [make_report(ext=nun_acc_ext(amp * math.sin(2 * math.pi * 5 * i * 0.006))) for i in range(int(secs / 0.006))]
    t = feed(c, wm, fr, t)
    t = feed(c, wm, [make_report(ext=nun_acc_ext(0))] * 40, t)
    return c, pad, kbd
c, pad, kbd = nun_shake()
check("by default shaking the Nunchuk does nothing (behavior unchanged)", not pad.where(dc.EV_KEY, 0x130) and not kbd.events)
c, pad, kbd = nun_shake("pad:A")
check("shaking the Nunchuk -> assigned button", pad.where(dc.EV_KEY, 0x130)[:2] == [1, 0], pad.events[:6])
c, pad, kbd = nun_shake("key:ESC")
check("...or any key / action", kbd.where(dc.EV_KEY, 1)[:2] == [1, 0])
c, pad, kbd = nun_shake("pad:A", amp=0.05)
check("a gentle Nunchuk movement triggers nothing", not pad.where(dc.EV_KEY, 0x130))
c, pad, kbd = nun_shake("pad:A", secs=0.0)
check("rest: nothing", not pad.where(dc.EV_KEY, 0x130))
check("Nunchuk: shake is an editor input", "NunShake" in dict(dc.INPUTS))

# ----------------------------------------------------------------- batch apply
print("batch apply")
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
pid = c.create_profile("Lote")
saves = []; dc.save_config = lambda cfg: saves.append(1)
ok = c.apply_bindings([("juego", "vertical", "A", "pad:Y"), ("juego", "horizontal", "Plus", "key:ESC"), (pid, "vertical", "B", "pad:A+pad:X")])
check("apply_bindings applies several changes at once", ok and dc.effective_bindings(c.cfg, "juego", "vertical")["A"] == "pad:Y"
      and dc.effective_bindings(c.cfg, "juego", "horizontal")["Plus"] == "key:ESC" and dc.effective_bindings(c.cfg, pid, "vertical")["B"] == "pad:A+pad:X")
check("...and saves only ONCE", len(saves) == 1, len(saves))
saves.clear()
before = json.dumps(c.cfg["profiles"], sort_keys=True)
ok = c.apply_bindings([("juego", "vertical", "B", "pad:X"), ("juego", "vertical", "A", "pad:NOPE")])
check("all or nothing: one invalid change prevents applying any", ok is False and json.dumps(c.cfg["profiles"], sort_keys=True) == before and not saves)
check("nonexistent profile or mode -> rejected", c.apply_bindings([("p99", "vertical", "A", "pad:A")]) is False and c.apply_bindings([("juego", "raro", "A", "pad:A")]) is False)
check("garbage -> rejected, empty list -> fine", c.apply_bindings([("a", "b")]) is False and c.apply_bindings([]) is True)
dc.save_config = lambda c: None

# ----------------------------------------------------------------- service / API used by the window and Decky
print("service API")
svc = dc.DeckService(*[FakeUInput() for _ in range(3)], use_lock=False)
svc.cfg = dc.load_config(); svc.log = wl.EventLog(tempfile.mkdtemp(), "t")
svc.dsu = dc.DSUServer(PORT + 2, svc.log)
svc.ctrl = dc.DeckController(svc.cfg, svc.log, *svc._fakes, dsu=svc.dsu); svc.ctrl.open_devices()
svc.mgr = wl.Manager(log=svc.log, on_frame=svc.ctrl.on_frame)
view = svc.bindings_view("horizontal", "juego")
names = {i["input"]: i for i in view["inputs"]}
check("bindings_view lists all inputs", set(names) == set(dict(dc.INPUTS)))
check("the horizontal D-pad appears as a stick", names["Up"]["value"] == "lstick:left", names["Up"]["value"])
check("Pointer/NunStick come with their own options", names["Pointer"]["options"] and names["NunStick"]["options"] and names["A"]["options"] is None)
check("there are actions for buttons, sticks, mouse, keyboard and program", {a["cat"] for a in view["actions"]} == {"Gamepad", "Keyboard", "Mouse", "Program"} and view["categories"] == ["Gamepad", "Keyboard", "Mouse", "Program"])
st = svc.status()
check("status() is JSON-serializable", __import__("json").dumps(st) and st["profile"] in dc.PROFILES)


print("profile quick access and notifications")
c, pad, mouse, kbd = new("vertical", "menus")
notes = []
c.on_notify = lambda t, b: notes.append(b)
c.set_mode("horizontal"); c.set_mode("horizontal")
check("changing mode notifies once (and not if it does not change)", notes == ["Mode: Horizontal"], notes)
c.set_profile("juego")
check("changing profile notifies with its name", notes[-1] == "Profile: Games", notes)
pid = c.create_profile("My profile")
check("a new profile does NOT enter quick access", pid not in c.cfg["quick_profiles"] and pid not in c.quick_profile_ids())
c.set_profile("menus")
c._app("toggle_profile")
check("+ and - rotate only through the quick-access ones", c.profile == "juego", c.profile)
c._app("toggle_profile")
check("...and return to the first without passing through the new one", c.profile == "menus", c.profile)
c.set_quick_profiles(["menus", pid, "nope"])
check("ids that do not exist are ignored", c.cfg["quick_profiles"] == ["menus", pid], c.cfg["quick_profiles"])
c._app("toggle_profile")
check("now it rotates through the new profile", c.profile == pid, c.profile)
c.set_quick_profiles([])
c._app("toggle_profile")
check("empty list: + and - do nothing", c.profile == pid, c.profile)
c.set_quick_profiles(["menus", pid])
c.delete_profile(pid)
check("deleting a profile removes it from quick access", c.cfg["quick_profiles"] == ["menus"], c.cfg["quick_profiles"])
c.on_notify = lambda t, b: 1 / 0
c.set_mode("vertical")
check("a failure in the notification does not break the change", c.mode == "vertical")
check("set_option does not touch quick_profiles", c.set_option("quick_profiles", ["x"]) is False)


print("DSU on several ports, estimated gyro and gentle shake")
srv = dc.DSUServer(26905, None, extra_ports=(26906,)); srv.start()
got = []
srv.on_client = lambda: got.append(1)
cl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); cl.settimeout(1.0)
cl.sendto(creq(dc.MSG_DATA, bytes([0, 0]) + bytes(6)), ("127.0.0.1", 26906)); time.sleep(0.2)
srv.push((0, 0, 1.0), (1.0, 2.0, 3.0), {}, 1_000_000)
r, frm = cl.recvfrom(256)
check("also listens on the extra port and answers from it", valid(r) and frm[1] == 26906 and srv.client_count == 1, frm)
check("reports that an emulator has connected", got == [1], got)
cl.sendto(creq(dc.MSG_VERSION), ("127.0.0.1", 26905)); r, frm = cl.recvfrom(256)
check("and on the main one", valid(r) and frm[1] == 26905, frm)
busy = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); busy.bind(("127.0.0.1", 26908))
srv.stop(); srv = dc.DSUServer(26907, None, extra_ports=(26908,)); check("a busy extra port does not prevent starting", srv.start() and srv.extra_socks == [])
srv.stop(); busy.close(); cl.close()

ag = dc.AccGyro()
out = (0, 0, 0)
for i in range(100):
    out = ag.update((0.0, 0.0, 1.0), i * 0.01)
check("still: estimated gyro 0", max(abs(v) for v in out) < 1.0, out)
ag = dc.AccGyro(); w = 60.0
for i in range(100):
    th = math.radians(w * i * 0.01)
    out = ag.update((0.0, math.sin(th), math.cos(th)), i * 0.01)
check("pitching up at 60 deg/s -> x axis ~ +60", 45 < out[0] < 75 and abs(out[1]) < 8 and abs(out[2]) < 8, out)
ag = dc.AccGyro()
for i in range(100):
    th = math.radians(w * i * 0.01)
    out = ag.update((-math.sin(th), 0.0, math.cos(th)), i * 0.01)
check("rolling right at 60 deg/s -> y axis ~ +60", 45 < out[1] < 75 and abs(out[0]) < 8, out)
for i in range(20):
    out = ag.update((0.0, 0.0, 3.0), 2.0 + i * 0.01)
check("with a bump (3 g) the estimate switches off", max(abs(v) for v in out) < 1.0, out)

c, pad, mouse, kbd = new("nunchuk", "juego"); wm = FakeWm(); wm.use_mp = False
t = feed(c, wm, [make_report()] * 50)
big = 0.0
for i in range(120):
    th = math.radians(80 * i * 0.006)
    raw = (128, int(round(128 - 26 * math.sin(th))), int(round(128 + 26 * math.cos(th))))
    t = feed(c, wm, [make_report(acc=raw)], t)
    big = max(big, max(abs(v) for v in c.states[0].dsu_gyro))
check("Nunchuk mode (no MotionPlus): the DSU receives estimated gyro", big > 25, big)
c, pad, mouse, kbd = new("nunchuk", "juego"); c.cfg["gyro_from_accel"] = False; wm = FakeWm(); wm.use_mp = False
t = feed(c, wm, [make_report()] * 50)
big = 0.0
for i in range(120):
    th = math.radians(80 * i * 0.006)
    raw = (128, int(round(128 - 26 * math.sin(th))), int(round(128 + 26 * math.cos(th))))
    t = feed(c, wm, [make_report(acc=raw)], t)
    big = max(big, max(abs(v) for v in c.states[0].dsu_gyro))
check("...and with the option off the gyro is 0", big == 0.0, big)


def wave(det, amp, hz, secs=3.0):
    fired = 0
    for i in range(int(secs / 0.006)):
        if det.update(i * 0.006, (amp * math.sin(2 * math.pi * hz * i * 0.006), 0.0, 1.0)):
            fired += 1
    return fired


check("gentle shake (0.3 g): with the default strength it does not trigger", wave(wl.ShakeDetector(0.55, 3), 0.3, 2.0) == 0)
check("...and lowering the strength (0.1 g) it does", wave(wl.ShakeDetector(0.1, 3), 0.3, 2.0) >= 1)
check("slow shake (1 Hz): with 0.4 s between reversals it does not trigger", wave(wl.ShakeDetector(0.3, 3), 0.9, 1.0) == 0)
check("...and with 0.8 s it does", wave(wl.ShakeDetector(0.3, 3, gap=0.8), 0.9, 1.0) >= 1)
check("2 reversals are enough to shake at 1 Hz and 0.8 s", wave(wl.ShakeDetector(0.3, 2, gap=0.8), 0.9, 1.0) >= 1)
c, pad, mouse, kbd = new("vertical", "juego")
c.set_option("shake_gap", 0.9); c.set_option("shake_threshold", 0.12)
rs = c.state_for(FakeWm())
check("set_option reaches the hand detector and the Nunchuk one", rs.shake.gap == 0.9 and rs.nun_shake.gap == 0.9 and rs.nun_shake.threshold == 0.12, (rs.shake.gap, rs.nun_shake.threshold))


print("v0.9: profile copy, keys, gyro dead zone")
c, pad, mouse, kbd = new("vertical", "juego")
c.set_binding("A", "key:ENTER", "vertical", "juego")
c.set_binding("B", "pad:X+key:Q", "horizontal", "juego")
pid = c.create_profile("Copy", "juego")
for m in dc.MODES:
    check("copy of Games in mode %s" % m, dc.effective_bindings(c.cfg, pid, m) == dc.effective_bindings(c.cfg, "juego", m))
c.set_binding("A", "pad:Y", "vertical", pid)
check("changing the copy does not touch the original", dc.effective_bindings(c.cfg, "juego", "vertical")["A"] == "key:ENTER")
pid2 = c.create_profile("Steam Menus copy", "menus")
check("copying a factory profile copies its factory values (A = click)", dc.effective_bindings(c.cfg, pid2, "vertical")["A"] == "mouse:LEFT")
pid3 = c.create_profile("Empty")
check("without copy_from it is still blank", all(v == "none" for v in dc.effective_bindings(c.cfg, pid3, "vertical").values()))
check("unknown copy_from too", all(v == "none" for v in dc.effective_bindings(c.cfg, c.create_profile("X", "nope"), "vertical").values()))
ids = [i for g, it in dc.ACTION_GROUPS for i, _ in it if i.startswith("key:")]
check("all editor keys exist and are valid", all(i[4:] in dc.KEYS for i in ids) and all(dc.valid_value("A", i) for i in ids) and len(ids) >= 70, len(ids))
check("key codes are not repeated", len(set(dc.KEYS.values())) == len(dc.KEYS))
check("category_of", dc.category_of("pad:A") == "Gamepad" and dc.category_of("key:Q") == "Keyboard" and dc.category_of("mouse:LEFT") == "Mouse" and dc.category_of("app:open_qam") == "Program")
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
c.set_binding("A", "key:Q+key:LSHIFT", "vertical", "juego")
t = tap(c, wm, wl.BTN_A, 100.0)
check("A = Shift + Q presses both keys", kbd.where(dc.EV_KEY, dc.KEYS["Q"]) == [1, 0] and kbd.where(dc.EV_KEY, dc.KEYS["LSHIFT"]) == [1, 0])

def gyro_out(dz, rate, gain=1.0):
    c, pad, mouse, kbd = new("vertical", "juego"); c.cfg["gyro_deadzone"] = dz; c.cfg["dsu_accel_gain"] = gain
    wm = FakeWm(); wm.use_mp = True
    rs = c.state_for(wm); rs.gyro_dps = (0.0, 0.0, rate); rs.acc_body = (0.0, 0.0, 1.0)
    c._motion(rs, wm, 1.0, True)
    return rs.dsu_gyro, rs.dsu_acc
g, a = gyro_out(2.0, 1.5)
check("dead zone: a 1.5 deg/s rotation (drift) is sent as 0", all(abs(v) < 1e-9 for v in g), g)
g, a = gyro_out(2.0, 10.0)
check("...and a real 10 deg/s one arrives trimmed by 2 (smooth, no jump)", abs(max(g, key=abs)) == 8.0, g)
g, a = gyro_out(0.0, 1.5)
check("with the dead zone at 0 it arrives whole", abs(max(g, key=abs)) == 1.5, g)
g, a = gyro_out(2.0, 0.0, gain=2.0)
check("the accelerometer gain multiplies what is sent", abs(max(a, key=abs) - 2.0) < 1e-9, a)
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 5)
t = feed(c, wm, [make_report(acc=(128, 128, 154 + 52))] * 3, t)
check("the acceleration peak is recorded (diagnostics)", c.states[0].acc_peak > 2.0, c.states[0].acc_peak)


print("v0.10: synthetic shake to the emulator")
def run_pulse(direction, amp=5.0, hz=8.0, cycles=2):
    c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm(); wm.use_mp = True
    c.cfg["eden_shake_amp"], c.cfg["eden_shake_hz"], c.cfg["eden_shake_cycles"] = amp, hz, cycles
    c.set_binding("ShakeRight", "app:eden_shake_" + direction, "vertical", "juego")
    t = feed(c, wm, [make_report()] * 30)
    rs = c.states[0]
    base = rs.dsu_acc
    c.eden_shake(direction)
    seen = []
    for i in range(80):
        t = feed(c, wm, [make_report()], t)
        seen.append(tuple(rs.dsu_acc))
    return base, seen, c
base, seen, c = run_pulse("up")
peak = max(max(abs(v) for v in a) for a in seen)
check("the upward shake raises the sent acceleration to ~5 g", 4.0 < peak < 6.5, peak)
check("...and ends on its own (returns to the resting value)", max(abs(seen[-1][i] - base[i]) for i in range(3)) < 0.2, (seen[-1], base))
check("...lasts about 0.25 s (2 swings at 8 Hz): ~40 reports of 6 ms", 25 <= sum(1 for a in seen if max(abs(a[i] - base[i]) for i in range(3)) > 0.3) <= 45)
xs = {}
for d in ("up", "left", "forward"):
    b, sn, _ = run_pulse(d)
    xs[d] = max(range(3), key=lambda i: max(abs(a[i] - b[i]) for a in sn))
check("each direction moves a different axis", len(set(xs.values())) == 3, xs)
b, sn, _ = run_pulse("up", amp=9.0)
check("the strength is adjustable", max(max(abs(v) for v in a) for a in sn) > 8.0)
check("unknown direction: does nothing", run_pulse("up")[2].eden_shake("up-left") is False)
c, pad, mouse, kbd = new("vertical", "juego")
c._app("eden_shake_back")
check("the 'Program' action triggers the pulse", c._eden_pulse is not None)
c.cfg["notify_enabled"] = False
got = []; c.on_notify = lambda t_, b_: got.append(b_); c.set_mode("horizontal")
check("notifications off: no notification is sent (the mode still changes)", got == [] and c.mode == "horizontal")
check("the 6 actions are in the editor", {i for g, it in dc.ACTION_GROUPS for i, _ in it if i.startswith("app:eden_shake_")} == {"app:eden_shake_" + d for d in ("up", "down", "left", "right", "forward", "back")})


print("v0.11: shake with gyro, continuous test and mirrored pad 1")
def gyro_pulse(direction, gyro):
    c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm(); wm.use_mp = True
    c.cfg["eden_shake_gyro"] = gyro
    t = feed(c, wm, [make_report()] * 30)
    c.eden_shake(direction)
    best = 0.0
    for i in range(60):
        t = feed(c, wm, [make_report()], t)
        best = max(best, max(abs(v) for v in c.states[0].dsu_gyro))
    return best
check("the shake also carries gyro (~700 deg/s by default)", 500 < gyro_pulse("up", 700.0) < 900, gyro_pulse("up", 700.0))
check("with the gyro at 0 there is only acceleration", gyro_pulse("up", 0.0) < 30.0, gyro_pulse("up", 0.0))
check("left/right rotate about a different axis than up/down", gyro_pulse("left", 700.0) > 500)
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm(); wm.use_mp = True
t = feed(c, wm, [make_report()] * 30)
c.eden_shake("up", 1.0)
active = 0
for i in range(250):
    t = feed(c, wm, [make_report()], t)
    if c._eden_pulse is not None:
        active += 1
check("continuous test: lasts ~1 s repeating and then stops on its own", 140 <= active <= 190 and c._eden_pulse is None, active)

srv = dc.DSUServer(26910, None); srv.mirror = True; srv.start()
cl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); cl.settimeout(1.0)
cl.sendto(creq(dc.MSG_INFO, struct.pack("<i", 2) + bytes([0, 1])), ("127.0.0.1", 26910))
srv.mark_alive()
cl.sendto(creq(dc.MSG_INFO, struct.pack("<i", 2) + bytes([0, 1])), ("127.0.0.1", 26910))
states = {}
for _ in range(2):
    r, _f = cl.recvfrom(256); states[r[20]] = r[21]
check("with the mirror, pad 1 is announced as connected", states.get(1) == 2, states)
cl.sendto(creq(dc.MSG_DATA, bytes([1, 1]) + bytes(6)), ("127.0.0.1", 26910)); time.sleep(0.2)
srv.push((0, 0, 1.0), (1.0, 2.0, 3.0), {}, 1_000_000)
pk = []
try:
    while True:
        pk.append(cl.recvfrom(256)[0])
except socket.timeout:
    pass
check("...and sends one packet per pad (0 and 1) with different numbers", sorted(p[20] for p in pk if len(p) > 80) == [0, 1] and len({p[32:36] for p in pk if len(p) > 80}) == 2, [p[20] for p in pk])
srv.mirror = False
check("without the mirror pad 1 is free again", srv._shared(1, True)[1] == 0)
srv.stop(); cl.close()


print("v0.12: taking port 26760 on the Deck")
blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); blocker.bind(("127.0.0.1", 26920))
own = dc.port_owner(26920)
check("port_owner finds the port owner (this process)", own is not None and own[0] == os.getpid(), own)
check("port_owner of a free port is None", dc.port_owner(26921) is None)
srv = dc.DSUServer(26922, None, extra_ports=(26920,)); srv.retry_s = 0.3; srv.start()
check("with the extra port busy, who is using it is recorded", srv.extra_state[26920][0] == "busy" and str(os.getpid()) in srv.extra_state[26920][1], srv.extra_state)
blocker.close(); time.sleep(0.9)
check("once freed, WimotionControlDeck takes it on its own (no restart)", srv.extra_state[26920][0] == "wimotioncontroldeck" and len(srv.extra_socks) == 1, srv.extra_state)
cl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); cl.settimeout(1.0)
cl.sendto(creq(dc.MSG_VERSION), ("127.0.0.1", 26920)); r, frm = cl.recvfrom(256)
check("...and answers emulators pointing at that port", valid(r) and frm[1] == 26920)
srv.stop(); cl.close()

svc = dc.DeckService(FakeUInput(), FakeUInput(), FakeUInput(), use_lock=False)
ok, msg = svc.free_dsu_port(26923)
check("free_dsu_port: port with no owner -> does nothing", ok is False and "Nobody" in msg, msg)
b2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); b2.bind(("127.0.0.1", 26924))
ok, msg = svc.free_dsu_port(26924)
check("free_dsu_port: does not stop itself", ok is False and "WimotionControlDeck" in msg, msg)
b2.close()
import subprocess
code = "import socket,time,sys; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(('127.0.0.1', 26925)); time.sleep(30)"
pr = subprocess.Popen([sys.executable, "-c", code + "  # fake_gyro_dsu"]); time.sleep(0.6)
ok, msg = svc.free_dsu_port(26925)
time.sleep(0.4)
check("free_dsu_port stops a gyro/DSU server", ok is True and pr.poll() is not None, (ok, msg, pr.poll()))
code2 = "import socket,time,sys; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(('127.0.0.1', 26926)); time.sleep(30)"
pr2 = subprocess.Popen([sys.executable, "-c", code2 + "  # mail_server"]); time.sleep(0.6)
ok, msg = svc.free_dsu_port(26926)
check("...but does NOT stop an arbitrary process", ok is False and pr2.poll() is None and "not stopping it" in msg, (ok, msg))
pr2.kill(); pr2.wait()

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
