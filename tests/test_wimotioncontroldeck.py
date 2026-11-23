import math, os, sys, tempfile, struct
from helpers import *
import deckcore as wd

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ok   ", name)
    else:
        FAIL += 1; print("  FAIL ", name, extra)

def new_ctrl(mode="vertical"):
    wd.CONFIG_PATH = "/nonexistent/config.json"
    cfg = wd.load_config(); cfg["mode"] = mode
    wd.save_config = lambda c: None
    log = wl.EventLog(tempfile.mkdtemp(), "t")
    pad, mouse = FakeUInput(), FakeUInput()
    c = wd.DeckController(cfg, log, pad, mouse, FakeUInput()); c.open_devices()
    return c, pad, mouse

def feed(c, wm, frames, t0=100.0, dt=0.006):
    t = t0
    for rep in frames:
        f = wl.parse_data_report(rep, t); c.on_frame(wm, f); t += dt
    return t

# ---- uinput structs
print("uinput")
size = struct.calcsize("80s4HI" + "64i" * 4)
check("uinput_user_dev = 1116 bytes", size == 1116, size)
check("input_event = 24 bytes (64 bit)", struct.calcsize(wd.EVENT_FMT) == 24)

# ---- buttons per mode
print("buttons")
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_A)] * 3 + [make_report(0)] * 3)
check("vertical: A = left click", mouse.where(wd.EV_KEY, 0x110) == [1, 0], mouse.where(wd.EV_KEY, 0x110))
t = feed(c, wm, [make_report(wl.BTN_B)] * 3 + [make_report(0)] * 3, t)
check("vertical: B = gamepad B button", pad.where(wd.EV_KEY, 0x131) == [1, 0])
t = feed(c, wm, [make_report(wl.BTN_UP)] * 3 + [make_report(0)] * 3, t)
check("vertical: Up = hat up (-1)", -1 in pad.where(wd.EV_ABS, wd.ABS_HAT0Y))
t = feed(c, wm, [make_report(wl.BTN_HOME)] * 3 + [make_report(0)] * 15, t)      # Home waits 120 ms in case it is Home + Plus
check("Home = Guide button", pad.where(wd.EV_KEY, 0x13C) == [1, 0])

c, pad, mouse = new_ctrl("horizontal"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_UP)] * 3 + [make_report(0)] * 3)
check("horizontal: Up -> stick left (negative X), not D-pad", min(pad.where(wd.EV_ABS, wd.ABS_X)) < -30000 and not pad.where(wd.EV_ABS, wd.ABS_HAT0X))
t = feed(c, wm, [make_report(wl.BTN_RIGHT)] * 3 + [make_report(0)] * 3, t)
check("horizontal: Right -> stick up (negative Y), not D-pad", min(pad.where(wd.EV_ABS, wd.ABS_Y)) < -30000 and not pad.where(wd.EV_ABS, wd.ABS_HAT0Y))
t = feed(c, wm, [make_report(wl.BTN_TWO)] * 40 + [make_report(0)] * 3, t)
check("horizontal: 2 held = A", pad.where(wd.EV_KEY, 0x130) == [1, 0], pad.where(wd.EV_KEY, 0x130))
t = feed(c, wm, [make_report(wl.BTN_ONE)] * 40 + [make_report(0)] * 3, t)
check("horizontal: 1 held = B", pad.where(wd.EV_KEY, 0x131) == [1, 0])
check("horizontal: no mouse", not mouse.events)

# ---- quick tap of 1 and the 1+2 chord
print("chord")
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_ONE)] * 5 + [make_report(0)] * 25)   # 30 ms tap
check("quick tap of 1 = X pressed and released", pad.where(wd.EV_KEY, 0x133) == [1, 0], pad.where(wd.EV_KEY, 0x133))
t = feed(c, wm, [make_report(wl.BTN_ONE)] * 2 + [make_report(wl.BTN_ONE | wl.BTN_TWO)] * 30 + [make_report(0)] * 5, t)
check("1+2 switches to horizontal", c.mode == "horizontal", c.mode)
check("1+2 does not press X or Y", pad.where(wd.EV_KEY, 0x133) == [1, 0] and not pad.where(wd.EV_KEY, 0x134))
check("1+2 sets the LED and rumbles", wm.leds[-1] == wd.MODE_LEDS["horizontal"] and wm.rumbles == 1, (wm.leds, wm.rumbles))
t = feed(c, wm, [make_report(wl.BTN_ONE | wl.BTN_TWO)] * 30 + [make_report(0)] * 5, t)
check("1+2 again -> nunchuk", c.mode == "nunchuk", c.mode)
t = feed(c, wm, [make_report(wl.BTN_ONE | wl.BTN_TWO)] * 30 + [make_report(0)] * 5, t)
check("1+2 again -> vertical", c.mode == "vertical", c.mode)

# ---- pointer
print("pointer")
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
def dots_at(dx=0, dy=0, sep=160):
    return [(512 + dx - sep // 2, 384 + dy), (512 + dx + sep // 2, 384 + dy)]
t = feed(c, wm, [make_report(dots=dots_at(0, 0))] * 200)
mouse.events.clear()
# the remote turns 1 degree to the right -> the dots shift left by ~ 1369*tan(1 degree) px
shift = round(1369 * math.tan(math.radians(1.0)))
t = feed(c, wm, [make_report(dots=dots_at(-shift, 0))] * 300, t)
sx = sum(mouse.where(wd.EV_REL, wd.REL_X)); sy = sum(mouse.where(wd.EV_REL, wd.REL_Y))
check("1 degree right -> ~45 px right", 38 <= sx <= 50 and abs(sy) <= 2, (sx, sy))
mouse.events.clear()
# aim higher: the dots move down in the image (y grows upward -> y decreases)
t = feed(c, wm, [make_report(dots=dots_at(-shift, -shift))] * 300, t)
sy = sum(mouse.where(wd.EV_REL, wd.REL_Y))
check("1 degree up -> ~45 px up (negative Y)", -50 <= sy <= -38, sy)
# losing the bar and finding it again produces no jumps
mouse.events.clear()
t = feed(c, wm, [make_report(dots=[])] * 100, t)
t = feed(c, wm, [make_report(dots=dots_at(200, 100))] * 50, t)
check("finding the bar again elsewhere does not move the cursor", abs(sum(mouse.where(wd.EV_REL, wd.REL_X))) <= 3 and abs(sum(mouse.where(wd.EV_REL, wd.REL_Y))) <= 3,
      (sum(mouse.where(wd.EV_REL, wd.REL_X)), sum(mouse.where(wd.EV_REL, wd.REL_Y))))
# roll: remote rotated 30 degrees, a dot moving along its horizontal axis moves the cursor in X
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
def rolled(dx_along, sep=160, ang=30.0):
    a = math.radians(ang); ca, sa = math.cos(a), math.sin(a)
    cx, cy = 512 + dx_along * ca, 384 + dx_along * sa
    return [(round(cx - sep / 2 * ca), round(cy - sep / 2 * sa)), (round(cx + sep / 2 * ca), round(cy + sep / 2 * sa))]
t = feed(c, wm, [make_report(dots=rolled(0))] * 200)
mouse.events.clear()
t = feed(c, wm, [make_report(dots=rolled(-shift))] * 300, t)
sx = sum(mouse.where(wd.EV_REL, wd.REL_X)); sy = sum(mouse.where(wd.EV_REL, wd.REL_Y))
check("with the remote rotated 30 degrees the movement follows the bar (X ~45, Y ~0)", 36 <= sx <= 52 and abs(sy) <= 6, (sx, sy))
# horizontal mode: the pointer moves nothing
c, pad, mouse = new_ctrl("horizontal"); wm = FakeWm()
t = feed(c, wm, [make_report(dots=dots_at(0, 0))] * 50 + [make_report(dots=dots_at(-80, 0))] * 50)
check("horizontal: IR does not move the cursor", not mouse.where(wd.EV_REL, wd.REL_X))

# ---- shake
print("shake")
def shake_frames(freq=5.0, amp=1.6, secs=1.2, dt=0.006):
    out = []
    n = int(secs / dt)
    for i in range(n):
        a = amp * math.sin(2 * math.pi * freq * i * dt)
        z = int(round(128 + 26 * (0.0 + a)))      # X axis oscillates
        out.append(make_report(acc=(max(0, min(255, z)), 128, 154)))
    return out
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 300)
t = feed(c, wm, shake_frames(amp=-1.6), t)     # the remote starts moving right (the raw accelerometer drops)
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 30, t)
check("shake right -> R1 (next collection)", pad.where(wd.EV_KEY, 0x137)[:2] == [1, 0] and not pad.where(wd.EV_KEY, 0x136), pad.where(wd.EV_KEY, 0x137))
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 300)
t = feed(c, wm, shake_frames(amp=1.6), t)
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 30, t)
check("shake left -> L1 (previous collection)", pad.where(wd.EV_KEY, 0x136)[:2] == [1, 0] and not pad.where(wd.EV_KEY, 0x137), (pad.where(wd.EV_KEY, 0x136), pad.where(wd.EV_KEY, 0x137)))
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 300)
t = feed(c, wm, [make_report(acc=(int(128 + 26 * 0.3 * math.sin(i / 20.0)), 128, 154)) for i in range(600)], t)
check("smooth movement does not count as a shake", not pad.where(wd.EV_KEY, 0x137))
c, pad, mouse = new_ctrl("vertical"); c.cfg["enabled"] = False; wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_A)] * 5)
check("control disabled: nothing comes out", not mouse.events and not pad.events)

# ---- Nunchuk
print("nunchuk")
def nun_ext(sx=131, sy=125, z=False, c_=False):
    b5 = 0xFC | (0 if z else 1) | (0 if c_ else 2)
    return (sx, sy, 128, 128, 154, b5)
c, pad, mouse = new_ctrl("nunchuk"); wm = FakeWm()
t = feed(c, wm, [make_report(ext=nun_ext())] * 40)
t = feed(c, wm, [make_report(ext=nun_ext(sx=131 + 95))] * 5, t)
check("stick right -> positive ABS_X", pad.where(wd.EV_ABS, wd.ABS_X) and pad.where(wd.EV_ABS, wd.ABS_X)[-1] > 30000, pad.where(wd.EV_ABS, wd.ABS_X)[-3:])
t = feed(c, wm, [make_report(ext=nun_ext(sy=125 + 95))] * 5, t)
check("stick up -> negative ABS_Y", pad.where(wd.EV_ABS, wd.ABS_Y) and pad.where(wd.EV_ABS, wd.ABS_Y)[-1] < -30000, pad.where(wd.EV_ABS, wd.ABS_Y)[-3:])
t = feed(c, wm, [make_report(ext=nun_ext())] * 5, t)
check("stick centered -> axes at 0", pad.where(wd.EV_ABS, wd.ABS_X)[-1] == 0 and pad.where(wd.EV_ABS, wd.ABS_Y)[-1] == 0)
t = feed(c, wm, [make_report(ext=nun_ext(c_=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
check("C = L1", pad.where(wd.EV_KEY, 0x136) == [1, 0])
t = feed(c, wm, [make_report(ext=nun_ext(z=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
check("Z = L2 (distinct from C)", pad.where(wd.EV_ABS, wd.ABS_Z)[:2] == [255, 0])
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(ext=nun_ext())] * 40 + [make_report(ext=nun_ext(sx=226))] * 5)
check("in vertical mode the Nunchuk is ignored", not pad.where(wd.EV_ABS, wd.ABS_X))

print("\n%d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
