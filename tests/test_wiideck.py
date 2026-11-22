import math, os, sys, tempfile, struct
from helpers import *
import deckcore as wd

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ok   ", name)
    else:
        FAIL += 1; print("  FALLA", name, extra)

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

# ---- struct de uinput
print("uinput")
size = struct.calcsize("80s4HI" + "64i" * 4)
check("uinput_user_dev = 1116 bytes", size == 1116, size)
check("input_event = 24 bytes (64 bit)", struct.calcsize(wd.EVENT_FMT) == 24)

# ---- botones por modo
print("botones")
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_A)] * 3 + [make_report(0)] * 3)
check("vertical: A = clic izquierdo", mouse.where(wd.EV_KEY, 0x110) == [1, 0], mouse.where(wd.EV_KEY, 0x110))
t = feed(c, wm, [make_report(wl.BTN_B)] * 3 + [make_report(0)] * 3, t)
check("vertical: B = boton B del gamepad", pad.where(wd.EV_KEY, 0x131) == [1, 0])
t = feed(c, wm, [make_report(wl.BTN_UP)] * 3 + [make_report(0)] * 3, t)
check("vertical: Up = hat arriba (-1)", -1 in pad.where(wd.EV_ABS, wd.ABS_HAT0Y))
t = feed(c, wm, [make_report(wl.BTN_HOME)] * 3 + [make_report(0)] * 15, t)      # Home espera 120 ms por si es Home + Plus
check("Home = boton Guia", pad.where(wd.EV_KEY, 0x13C) == [1, 0])

c, pad, mouse = new_ctrl("horizontal"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_UP)] * 3 + [make_report(0)] * 3)
check("horizontal: Up -> stick izquierda (X negativo), no cruceta", min(pad.where(wd.EV_ABS, wd.ABS_X)) < -30000 and not pad.where(wd.EV_ABS, wd.ABS_HAT0X))
t = feed(c, wm, [make_report(wl.BTN_RIGHT)] * 3 + [make_report(0)] * 3, t)
check("horizontal: Right -> stick arriba (Y negativo), no cruceta", min(pad.where(wd.EV_ABS, wd.ABS_Y)) < -30000 and not pad.where(wd.EV_ABS, wd.ABS_HAT0Y))
t = feed(c, wm, [make_report(wl.BTN_TWO)] * 40 + [make_report(0)] * 3, t)
check("horizontal: 2 mantenido = A", pad.where(wd.EV_KEY, 0x130) == [1, 0], pad.where(wd.EV_KEY, 0x130))
t = feed(c, wm, [make_report(wl.BTN_ONE)] * 40 + [make_report(0)] * 3, t)
check("horizontal: 1 mantenido = B", pad.where(wd.EV_KEY, 0x131) == [1, 0])
check("horizontal: sin raton", not mouse.events)

# ---- toque rapido de 1 y acorde 1+2
print("acorde")
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_ONE)] * 5 + [make_report(0)] * 25)   # toque de 30 ms
check("toque rapido de 1 = X pulsada y soltada", pad.where(wd.EV_KEY, 0x133) == [1, 0], pad.where(wd.EV_KEY, 0x133))
t = feed(c, wm, [make_report(wl.BTN_ONE)] * 2 + [make_report(wl.BTN_ONE | wl.BTN_TWO)] * 30 + [make_report(0)] * 5, t)
check("1+2 cambia a horizontal", c.mode == "horizontal", c.mode)
check("1+2 no pulsa X ni Y", pad.where(wd.EV_KEY, 0x133) == [1, 0] and not pad.where(wd.EV_KEY, 0x134))
check("1+2 pone LED y vibra", wm.leds[-1] == wd.MODE_LEDS["horizontal"] and wm.rumbles == 1, (wm.leds, wm.rumbles))
t = feed(c, wm, [make_report(wl.BTN_ONE | wl.BTN_TWO)] * 30 + [make_report(0)] * 5, t)
check("1+2 otra vez -> nunchuk", c.mode == "nunchuk", c.mode)
t = feed(c, wm, [make_report(wl.BTN_ONE | wl.BTN_TWO)] * 30 + [make_report(0)] * 5, t)
check("1+2 otra vez -> vertical", c.mode == "vertical", c.mode)

# ---- puntero
print("puntero")
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
def dots_at(dx=0, dy=0, sep=160):
    return [(512 + dx - sep // 2, 384 + dy), (512 + dx + sep // 2, 384 + dy)]
t = feed(c, wm, [make_report(dots=dots_at(0, 0))] * 200)
mouse.events.clear()
# el mando gira 1 grado a la derecha -> los puntos se desplazan a la izquierda ~ 1369*tan(1 grado) px
shift = round(1369 * math.tan(math.radians(1.0)))
t = feed(c, wm, [make_report(dots=dots_at(-shift, 0))] * 300, t)
sx = sum(mouse.where(wd.EV_REL, wd.REL_X)); sy = sum(mouse.where(wd.EV_REL, wd.REL_Y))
check("1 grado a la derecha -> ~45 px a la derecha", 38 <= sx <= 50 and abs(sy) <= 2, (sx, sy))
mouse.events.clear()
# apuntar mas arriba: los puntos bajan en la imagen (y crece hacia arriba -> y disminuye)
t = feed(c, wm, [make_report(dots=dots_at(-shift, -shift))] * 300, t)
sy = sum(mouse.where(wd.EV_REL, wd.REL_Y))
check("1 grado hacia arriba -> ~45 px hacia arriba (Y negativo)", -50 <= sy <= -38, sy)
# perder la barra y recuperarla no produce saltos
mouse.events.clear()
t = feed(c, wm, [make_report(dots=[])] * 100, t)
t = feed(c, wm, [make_report(dots=dots_at(200, 100))] * 50, t)
check("reencontrar la barra en otro sitio no mueve el cursor", abs(sum(mouse.where(wd.EV_REL, wd.REL_X))) <= 3 and abs(sum(mouse.where(wd.EV_REL, wd.REL_Y))) <= 3,
      (sum(mouse.where(wd.EV_REL, wd.REL_X)), sum(mouse.where(wd.EV_REL, wd.REL_Y))))
# roll: mando girado 30 grados, un punto que se mueve a lo largo de su eje horizontal mueve el cursor en X
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
def rolled(dx_along, sep=160, ang=30.0):
    a = math.radians(ang); ca, sa = math.cos(a), math.sin(a)
    cx, cy = 512 + dx_along * ca, 384 + dx_along * sa
    return [(round(cx - sep / 2 * ca), round(cy - sep / 2 * sa)), (round(cx + sep / 2 * ca), round(cy + sep / 2 * sa))]
t = feed(c, wm, [make_report(dots=rolled(0))] * 200)
mouse.events.clear()
t = feed(c, wm, [make_report(dots=rolled(-shift))] * 300, t)
sx = sum(mouse.where(wd.EV_REL, wd.REL_X)); sy = sum(mouse.where(wd.EV_REL, wd.REL_Y))
check("con el mando girado 30 grados el movimiento sigue la barra (X ~45, Y ~0)", 36 <= sx <= 52 and abs(sy) <= 6, (sx, sy))
# modo horizontal: el puntero no mueve nada
c, pad, mouse = new_ctrl("horizontal"); wm = FakeWm()
t = feed(c, wm, [make_report(dots=dots_at(0, 0))] * 50 + [make_report(dots=dots_at(-80, 0))] * 50)
check("horizontal: el IR no mueve el cursor", not mouse.where(wd.EV_REL, wd.REL_X))

# ---- sacudida
print("sacudida")
def shake_frames(freq=5.0, amp=1.6, secs=1.2, dt=0.006):
    out = []
    n = int(secs / dt)
    for i in range(n):
        a = amp * math.sin(2 * math.pi * freq * i * dt)
        z = int(round(128 + 26 * (0.0 + a)))      # eje X oscila
        out.append(make_report(acc=(max(0, min(255, z)), 128, 154)))
    return out
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 300)
t = feed(c, wm, shake_frames(amp=-1.6), t)     # el mando arranca hacia la derecha (el acelerometro crudo baja)
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 30, t)
check("agitar a la derecha -> R1 (siguiente coleccion)", pad.where(wd.EV_KEY, 0x137)[:2] == [1, 0] and not pad.where(wd.EV_KEY, 0x136), pad.where(wd.EV_KEY, 0x137))
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 300)
t = feed(c, wm, shake_frames(amp=1.6), t)
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 30, t)
check("agitar a la izquierda -> L1 (coleccion anterior)", pad.where(wd.EV_KEY, 0x136)[:2] == [1, 0] and not pad.where(wd.EV_KEY, 0x137), (pad.where(wd.EV_KEY, 0x136), pad.where(wd.EV_KEY, 0x137)))
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(acc=(128, 128, 154))] * 300)
t = feed(c, wm, [make_report(acc=(int(128 + 26 * 0.3 * math.sin(i / 20.0)), 128, 154)) for i in range(600)], t)
check("movimiento suave no cuenta como sacudida", not pad.where(wd.EV_KEY, 0x137))
c, pad, mouse = new_ctrl("vertical"); c.cfg["enabled"] = False; wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_A)] * 5)
check("control desactivado: no sale nada", not mouse.events and not pad.events)

# ---- Nunchuk
print("nunchuk")
def nun_ext(sx=131, sy=125, z=False, c_=False):
    b5 = 0xFC | (0 if z else 1) | (0 if c_ else 2)
    return (sx, sy, 128, 128, 154, b5)
c, pad, mouse = new_ctrl("nunchuk"); wm = FakeWm()
t = feed(c, wm, [make_report(ext=nun_ext())] * 40)
t = feed(c, wm, [make_report(ext=nun_ext(sx=131 + 95))] * 5, t)
check("palanca a la derecha -> ABS_X positivo", pad.where(wd.EV_ABS, wd.ABS_X) and pad.where(wd.EV_ABS, wd.ABS_X)[-1] > 30000, pad.where(wd.EV_ABS, wd.ABS_X)[-3:])
t = feed(c, wm, [make_report(ext=nun_ext(sy=125 + 95))] * 5, t)
check("palanca arriba -> ABS_Y negativo", pad.where(wd.EV_ABS, wd.ABS_Y) and pad.where(wd.EV_ABS, wd.ABS_Y)[-1] < -30000, pad.where(wd.EV_ABS, wd.ABS_Y)[-3:])
t = feed(c, wm, [make_report(ext=nun_ext())] * 5, t)
check("palanca al centro -> ejes a 0", pad.where(wd.EV_ABS, wd.ABS_X)[-1] == 0 and pad.where(wd.EV_ABS, wd.ABS_Y)[-1] == 0)
t = feed(c, wm, [make_report(ext=nun_ext(c_=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
check("C = L1", pad.where(wd.EV_KEY, 0x136) == [1, 0])
t = feed(c, wm, [make_report(ext=nun_ext(z=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
check("Z = L2 (distinto de C)", pad.where(wd.EV_ABS, wd.ABS_Z)[:2] == [255, 0])
c, pad, mouse = new_ctrl("vertical"); wm = FakeWm()
t = feed(c, wm, [make_report(ext=nun_ext())] * 40 + [make_report(ext=nun_ext(sx=226))] * 5)
check("en modo vertical el Nunchuk se ignora", not pad.where(wd.EV_ABS, wd.ABS_X))

print("\n%d correctas, %d fallos" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
