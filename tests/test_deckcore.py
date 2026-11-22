"""Pruebas del nucleo de WiiDeck v0.2 (deckcore): perfiles, asignaciones, modos, Nunchuk, giroscopio y servidor DSU."""
import socket, struct, sys, tempfile, time, zlib
from helpers import *
import deckcore as dc

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print("  ok   ", name)
    else:
        FAIL += 1; print("  FALLA", name, extra)


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
    """Trama de MotionPlus (modo independiente) con los tres ejes en 'lento'."""
    return (yaw & 0xFF, roll & 0xFF, pitch & 0xFF,
            ((yaw >> 8) << 2) | 0x02 | 0x01, ((roll >> 8) << 2) | 0x02 | 0x01, ((pitch >> 8) << 2) | 0x02)


# ----------------------------------------------------------------- 3 puntos del usuario: modo horizontal
print("horizontal: la cruceta es el stick izquierdo")
c, pad, mouse, kbd = new("horizontal"); wm = FakeWm()
t = tap(c, wm, wl.BTN_UP, 100.0)
xs = pad.where(dc.EV_ABS, dc.ABS_X)
check("Up (mando de lado) -> stick izquierdo a la izquierda", xs and min(xs) <= -32000, xs)
check("...y NO toca la cruceta digital", not pad.where(dc.EV_ABS, dc.ABS_HAT0X) and not pad.where(dc.EV_ABS, dc.ABS_HAT0Y))
check("...y vuelve a 0 al soltar", xs[-1] == 0, xs)
pad.events.clear()
t = tap(c, wm, wl.BTN_RIGHT, t)
ys = pad.where(dc.EV_ABS, dc.ABS_Y)
check("Right -> stick arriba (Y negativo en el gamepad)", ys and min(ys) <= -32000, ys)
pad.events.clear()
t = tap(c, wm, wl.BTN_DOWN, t)
check("Down -> stick a la derecha", max(pad.where(dc.EV_ABS, dc.ABS_X)) >= 32000)
pad.events.clear()
t = tap(c, wm, wl.BTN_LEFT, t)
check("Left -> stick abajo", max(pad.where(dc.EV_ABS, dc.ABS_Y)) >= 32000)
pad.events.clear()
t = feed(c, wm, [make_report(wl.BTN_UP | wl.BTN_RIGHT)] * 5, t)
xs, ys = pad.where(dc.EV_ABS, dc.ABS_X), pad.where(dc.EV_ABS, dc.ABS_Y)
check("diagonal normalizada (modulo <= 1)", xs and ys and (xs[-1] ** 2 + ys[-1] ** 2) ** 0.5 <= 32768 * 1.001, (xs[-1], ys[-1]))

# ----------------------------------------------------------------- asignaciones y perfiles
print("asignaciones")
c, pad, mouse, kbd = new("vertical", "menus"); wm = FakeWm()
t = tap(c, wm, wl.BTN_A, 100.0)
check("perfil Menus: A = clic izquierdo", mouse.where(dc.EV_KEY, 0x110) == [1, 0])
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
t = tap(c, wm, wl.BTN_A, 100.0)
check("perfil Juegos: A = boton A del gamepad", pad.where(dc.EV_KEY, 0x130) == [1, 0] and not mouse.where(dc.EV_KEY, 0x110))
t = tap(c, wm, wl.BTN_B, t)
check("perfil Juegos: B = gatillo R2", 255 in pad.where(dc.EV_ABS, dc.ABS_RZ) and pad.where(dc.EV_ABS, dc.ABS_RZ)[-1] == 0)

c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
check("set_binding acepta una accion valida", c.set_binding("A", "pad:Y") is True)
check("set_binding rechaza una accion inventada", c.set_binding("A", "pad:NOEXISTE") is False)
check("set_binding rechaza una entrada inventada", c.set_binding("Zzz", "pad:A") is False)
t = tap(c, wm, wl.BTN_A, 100.0)
check("A reasignado a Y funciona", pad.where(dc.EV_KEY, 0x134) == [1, 0] and not pad.where(dc.EV_KEY, 0x130))
c.set_binding("A", "key:ENTER")
t = tap(c, wm, wl.BTN_A, t)
check("A reasignado a una tecla (Intro) funciona", kbd.where(dc.EV_KEY, 28) == [1, 0])
c.set_binding("A", "mouse:RIGHT")
t = tap(c, wm, wl.BTN_A, t)
check("A reasignado a clic derecho funciona", mouse.where(dc.EV_KEY, 0x111) == [1, 0])
check("la asignacion es solo del modo/perfil editado", dc.effective_bindings(c.cfg, "menus", "vertical")["A"] == "mouse:LEFT"
      and dc.effective_bindings(c.cfg, "juego", "horizontal")["A"] == "pad:X")
c.reset_bindings()
check("reset_bindings devuelve lo de fabrica", c.bindings()["A"] == "pad:A")
check("Pointer solo admite mouse/none", c.set_binding("Pointer", "none") and not c.set_binding("Pointer", "pad:A"))
check("NunStick solo admite stick/cruceta/nada", c.set_binding("NunStick", "rstick") and not c.set_binding("NunStick", "mouse:LEFT"))

# asignaciones guardadas por el usuario se cargan
c, pad, mouse, kbd = new("vertical", "juego", {"juego": {"vertical": {"Plus": "pad:Y"}}}); wm = FakeWm()
t = tap(c, wm, wl.BTN_PLUS, 100.0)
check("config del usuario: + = Y", pad.where(dc.EV_KEY, 0x134) == [1, 0])

# puntero desactivable por asignacion
c, pad, mouse, kbd = new("vertical", "menus", {"menus": {"vertical": {"Pointer": "none"}}}); wm = FakeWm()
dots = [(450, 384), (570, 384)]
t = feed(c, wm, [make_report(dots=dots)] * 100)
t = feed(c, wm, [make_report(dots=[(380, 384), (500, 384)])] * 100, t)
check("Pointer = none: el IR no mueve el cursor", not mouse.where(dc.EV_REL, dc.REL_X))

# ----------------------------------------------------------------- Nunchuk: C y Z distintos
print("nunchuk")
c, pad, mouse, kbd = new("nunchuk", "menus"); wm = FakeWm()
t = feed(c, wm, [make_report(ext=nun_ext())] * 40)
t = feed(c, wm, [make_report(ext=nun_ext(c_=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
check("C por defecto = L1", pad.where(dc.EV_KEY, 0x136) == [1, 0])
t = feed(c, wm, [make_report(ext=nun_ext(z=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
check("Z por defecto = L2 (distinto de C)", pad.where(dc.EV_ABS, dc.ABS_Z)[:2] == [255, 0] and pad.where(dc.EV_KEY, 0x136) == [1, 0])
c.set_binding("NunC", "pad:X"); c.set_binding("NunZ", "pad:Y")
t = feed(c, wm, [make_report(ext=nun_ext(c_=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
t = feed(c, wm, [make_report(ext=nun_ext(z=True))] * 3 + [make_report(ext=nun_ext())] * 3, t)
check("C y Z reasignables (C=X, Z=Y)", pad.where(dc.EV_KEY, 0x133) == [1, 0] and pad.where(dc.EV_KEY, 0x134) == [1, 0])
c.set_binding("NunStick", "rstick")
t = feed(c, wm, [make_report(ext=nun_ext(sx=131 + 95))] * 5, t)
check("palanca del Nunchuk -> stick derecho si se asigna", pad.where(dc.EV_ABS, dc.ABS_RX) and pad.where(dc.EV_ABS, dc.ABS_RX)[-1] > 30000)

# ----------------------------------------------------------------- interruptor general y perfiles
print("interruptor y perfiles")
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_A)] * 3, 100.0)
c.set_enabled(False)
check("desactivar suelta lo pulsado", pad.where(dc.EV_KEY, 0x130) == [1, 0], pad.where(dc.EV_KEY, 0x130))
n = len(pad.events)
t = feed(c, wm, [make_report(0)] * 3 + [make_report(wl.BTN_A)] * 10 + [make_report(0)] * 3, t)
check("desactivado: el mando no genera nada", len(pad.events) == n and not mouse.events)
c.set_enabled(True)
t = tap(c, wm, wl.BTN_A, t)
check("reactivado: vuelve a funcionar", pad.where(dc.EV_KEY, 0x130)[-2:] == [1, 0] and len(pad.where(dc.EV_KEY, 0x130)) == 4)
c, pad, mouse, kbd = new("vertical", "menus"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_PLUS | wl.BTN_MINUS)] * 30 + [make_report(0)] * 5, 100.0)
check("+ y - a la vez cambian de perfil", c.profile == "juego", c.profile)
check("el acorde no pulsa Start/Select", not pad.where(dc.EV_KEY, 0x13B) and not pad.where(dc.EV_KEY, 0x13A))
check("LED4 indica perfil Juegos", wm.leds[-1] & 0b1000, wm.leds)

# ----------------------------------------------------------------- giroscopio
print("giroscopio")
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm(); wm.use_mp = True
c.cfg["gyro_stick"] = True
t = feed(c, wm, [make_report(ext=mp_ext())] * 20)
check("MotionPlus quieto: stick derecho a 0", not pad.where(dc.EV_ABS, dc.ABS_RY) or pad.where(dc.EV_ABS, dc.ABS_RY)[-1] == 0)
t = feed(c, wm, [make_report(ext=mp_ext(pitch=8192 + 2000))] * 5, t)
ry = pad.where(dc.EV_ABS, dc.ABS_RY)
check("subir la punta (pitch+) -> stick derecho hacia arriba (Y negativo)", ry and ry[-1] < -20000, ry[-3:])
c.cfg["gyro_stick"] = False
c.stick_ana["rstick"] = (0.0, 0.0); c._emit_sticks()
pad.events.clear()
t = feed(c, wm, [make_report(ext=mp_ext(pitch=8192 + 2000))] * 5, t)
check("gyro_stick apagado: el stick derecho no se mueve", not pad.where(dc.EV_ABS, dc.ABS_RY))
check("want_mp: vertical si, nunchuk no", c.want_mp() and (c.set_mode("nunchuk") or True) and not c.want_mp())

# ----------------------------------------------------------------- DSU
print("DSU (movimiento para emuladores)")
PORT = 26791
srv = dc.DSUServer(PORT, None)
check("el servidor DSU arranca", srv.start())
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
check("responde a la peticion de version con CRC correcto", valid(r) and struct.unpack("<I", r[16:20])[0] == dc.MSG_VERSION)
srv.connected = True
cli.sendto(creq(dc.MSG_INFO, struct.pack("<i", 1) + bytes([0, 0, 0, 0])), ("127.0.0.1", PORT))
r = cli.recv(256)
check("informa del mando 0 como conectado", valid(r) and r[21] == 2, r[16:32].hex())
cli.sendto(creq(dc.MSG_DATA, bytes([0, 0]) + bytes(6)), ("127.0.0.1", PORT))
time.sleep(0.2)
check("registra al cliente", srv.client_count == 1)
srv.push((0.0, 0.0, 1.0), (10.0, 20.0, 30.0), {"a": True}, 5_000_000)
r = cli.recv(256)
vals = struct.unpack("<Q6f", r[-32:])
check("paquete de datos valido con acel+giro", valid(r) and len(r) == 100 and abs(vals[4] - 10.0) < 1e-4 and abs(vals[6] - 30.0) < 1e-4 and abs(vals[3] - 1.0) < 1e-4, (len(r), vals))
check("el boton A llega en el byte de botones", r[37] & 0x20, r[37])
srv.stop(); cli.close()

# integracion: el mando en vertical con MotionPlus alimenta al servidor DSU
srv = dc.DSUServer(PORT + 1, None); srv.start()
c, pad, mouse, kbd = new("vertical", "juego"); c.dsu = srv
wm = FakeWm(); wm.use_mp = True
cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); cli.settimeout(1.0)
cli.sendto(creq(dc.MSG_DATA, bytes([0, 0]) + bytes(6)), ("127.0.0.1", PORT + 1)); time.sleep(0.2)
t = feed(c, wm, [make_report(ext=mp_ext())] * 20)
pk = None
for i in range(30):                      # el servidor limita a ~250 paquetes/s: se alimenta a ritmo real
    t = feed(c, wm, [make_report(ext=mp_ext(yaw=8192 + 1000))], t)
    time.sleep(0.006)
try:
    while True:
        pk = cli.recv(256)
        cli.settimeout(0.05)
except socket.timeout:
    pass
g = struct.unpack("<Q6f", pk[-32:])[4:] if pk else None
check("DeckController -> DSU: el giro llega al emulador", g is not None and max(abs(x) for x in g) > 20.0, g)
srv.stop(); cli.close()

# ----------------------------------------------------------------- combinaciones de botones (A + B ...)
print("combinaciones")
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
check("A + B es una asignacion valida", c.set_binding("A", "pad:A+pad:B") is True)
check("tres y cuatro botones tambien", c.set_binding("B", "pad:A+pad:B+pad:X") and c.set_binding("B", "pad:A+pad:B+pad:X+pad:Y"))
check("cinco botones no (maximo 4)", c.set_binding("B", "pad:A+pad:B+pad:X+pad:Y+pad:TL") is False)
check("'Nada' no se mezcla con otros", c.set_binding("B", "pad:A+none") is False and c.set_binding("B", "none"))
check("una pieza inventada invalida toda la combinacion", c.set_binding("B", "pad:A+pad:NOPE") is False)
check("el puntero no admite combinaciones", c.set_binding("Pointer", "mouse+none") is False)
c.set_binding("A", "pad:A+pad:B+key:ENTER")
t = tap(c, wm, wl.BTN_A, 100.0)
check("A -> A+B+Intro: se pulsan los tres", pad.where(dc.EV_KEY, 0x130)[:1] == [1] and pad.where(dc.EV_KEY, 0x131)[:1] == [1] and kbd.where(dc.EV_KEY, 28)[:1] == [1])
check("...y se sueltan los tres", pad.where(dc.EV_KEY, 0x130) == [1, 0] and pad.where(dc.EV_KEY, 0x131) == [1, 0] and kbd.where(dc.EV_KEY, 28) == [1, 0])
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
c.set_binding("A", "pad:X"); c.set_binding("One", "pad:X"); c.set_binding("Two", "none")
t = feed(c, wm, [make_report(wl.BTN_A)] * 3, 100.0)
t = feed(c, wm, [make_report(wl.BTN_A | wl.BTN_ONE)] * 40, t)
t = feed(c, wm, [make_report(wl.BTN_ONE)] * 3, t)
check("dos entradas con el mismo boton: soltar una no lo suelta", pad.where(dc.EV_KEY, 0x133) == [1], pad.where(dc.EV_KEY, 0x133))
t = feed(c, wm, [make_report(0)] * 3, t)
check("...se suelta al soltar la ultima", pad.where(dc.EV_KEY, 0x133) == [1, 0], pad.where(dc.EV_KEY, 0x133))
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
c.set_binding("A", "app:toggle_gyro+pad:A"); g0 = c.cfg["gyro_enabled"]
t = tap(c, wm, wl.BTN_A, 100.0)
check("una combinacion puede incluir acciones del programa", c.cfg["gyro_enabled"] != g0 and pad.where(dc.EV_KEY, 0x130) == [1, 0])
check("split/join de acciones", dc.split_action("pad:A+pad:B") == ["pad:A", "pad:B"] and dc.join_actions(["pad:A", "none", "pad:B"]) == "pad:A+pad:B" and dc.join_actions([]) == "none")

# ----------------------------------------------------------------- perfiles propios
print("perfiles propios")
c, pad, mouse, kbd = new("vertical", "menus"); wm = FakeWm()
pid = c.create_profile("  Mi   perfil  ")
check("crear perfil devuelve un id y guarda el nombre limpio", pid and c.cfg["custom_profiles"][pid] == "Mi perfil", c.cfg["custom_profiles"])
check("aparece detras de los dos de fabrica", dc.profile_ids(c.cfg) == ["menus", "juego", pid])
check("nombre vacio rechazado", c.create_profile("   ") is None and c.create_profile("") is None)
pid2 = c.create_profile("mi PERFIL")
check("nombre repetido se renombra con numero", c.cfg["custom_profiles"][pid2] == "mi PERFIL 2", c.cfg["custom_profiles"])
blank = dc.effective_bindings(c.cfg, pid, "vertical")
check("el perfil nuevo empieza EN BLANCO (todo en Nada)", all(v == "none" for v in blank.values()) and set(blank) == set(dict(dc.INPUTS)), blank)
c.set_profile(pid)
check("se puede activar", c.profile == pid)
pad.events.clear(); mouse.events.clear(); kbd.events.clear()    # al cambiar de perfil se sueltan los ejes a 0
t = tap(c, wm, wl.BTN_A, 100.0); t = tap(c, wm, wl.BTN_B, t); t = tap(c, wm, wl.BTN_HOME, t)
check("en blanco: ningun boton hace nada", not pad.events and not mouse.events and not kbd.events)
dots = [(450, 384), (570, 384)]
t = feed(c, wm, [make_report(dots=dots)] * 100, t); t = feed(c, wm, [make_report(dots=[(380, 384), (500, 384)])] * 100, t)
check("en blanco: el puntero tampoco mueve el cursor", not mouse.events)
c.set_binding("A", "pad:Y")
t = tap(c, wm, wl.BTN_A, t)
check("se le pueden asignar botones", pad.where(dc.EV_KEY, 0x134) == [1, 0])
check("las asignaciones de un perfil propio no tocan las de fabrica", dc.effective_bindings(c.cfg, "juego", "vertical")["A"] == "pad:A")
check("set_binding en un perfil inexistente se rechaza", c.set_binding("A", "pad:A", "vertical", "p99") is False)
check("set_profile a uno inexistente se ignora", (c.set_profile("p99") or True) and c.profile == pid)
c.set_quick_profiles(["menus", pid, pid2])      # por defecto los perfiles propios NO rotan: se incluyen a mano
t = feed(c, wm, [make_report(wl.BTN_PLUS | wl.BTN_MINUS)] * 30 + [make_report(0)] * 5, t)
check("+ y - recorren los perfiles propios incluidos en acceso rapido (siguiente: el segundo)", c.profile == pid2, c.profile)
t = feed(c, wm, [make_report(wl.BTN_PLUS | wl.BTN_MINUS)] * 30 + [make_report(0)] * 5, t)
check("...y despues vuelve a Menus", c.profile == "menus", c.profile)
check("LED 4 en perfiles propios", (c.set_profile(pid) or True) and wm.leds[-1] & 0b1000, wm.leds)
check("borrar un perfil de fabrica se rechaza", c.delete_profile("menus") is False and c.delete_profile("juego") is False)
check("borrar el perfil activo vuelve a Menus", c.delete_profile(pid) and c.profile == "menus" and pid not in c.cfg["custom_profiles"] and pid not in c.cfg["profiles"])
for k in range(20):
    c.create_profile("x%d" % k)
check("hay un maximo de perfiles", len(c.cfg["custom_profiles"]) <= dc.MAX_CUSTOM_PROFILES, len(c.cfg["custom_profiles"]))
# se guardan y se recargan
import json, os
cfgfile = os.path.join(tempfile.mkdtemp(), "config.json")
json.dump({"custom_profiles": {"p1": "Zelda"}, "profile": "p1", "profiles": {"p1": {"vertical": {"A": "pad:X+pad:Y"}}}}, open(cfgfile, "w"))
dc.CONFIG_PATH = cfgfile
cfg = dc.load_config()
check("config con perfil propio se carga", cfg["profile"] == "p1" and dc.profile_title(cfg, "p1") == "Zelda" and dc.effective_bindings(cfg)["A"] == "pad:X+pad:Y")
json.dump({"custom_profiles": {"p1": "Zelda"}, "profile": "p7"}, open(cfgfile, "w"))
check("perfil activo desaparecido -> Menus", dc.load_config()["profile"] == "menus")
json.dump({"dsu_port": 26760}, open(cfgfile, "w"))
check("migracion: el puerto DSU 26760 antiguo pasa a 26761", dc.load_config()["dsu_port"] == 26761)
json.dump({"dsu_port": 26770, "config_version": 3}, open(cfgfile, "w"))
check("un puerto elegido a mano se respeta", dc.load_config()["dsu_port"] == 26770)
dc.CONFIG_PATH = "/nonexistent/config.json"

# ----------------------------------------------------------------- agitar con direccion
print("agitar direccional")
import math


def shake(mode, axis, sign, profile="menus", prep=None):
    """Mando en reposo, y 1,2 s de agitado en el eje CRUDO 'axis' (0=x,1=y,2=z) empezando hacia 'sign'."""
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
check("vertical: agitar a la DERECHA -> R1 (lista a la izquierda)", pressed(pad, 0x137) and not pad.where(dc.EV_KEY, 0x136))
c, pad, kbd = shake("vertical", 0, +1)
check("vertical: agitar a la IZQUIERDA -> L1", pressed(pad, 0x136) and not pad.where(dc.EV_KEY, 0x137))
c, pad, kbd = shake("vertical", 2, +1, prep=lambda c: c.set_binding("ShakeUp", "pad:A"))
check("vertical: agitar hacia ARRIBA -> lo asignado a Arriba", pressed(pad, 0x130) and not pad.where(dc.EV_KEY, 0x136) and not pad.where(dc.EV_KEY, 0x137), pad.events[:6])
c, pad, kbd = shake("vertical", 2, -1, prep=lambda c: c.set_binding("ShakeDown", "key:ESC"))
check("vertical: agitar hacia ABAJO -> lo asignado a Abajo", kbd.where(dc.EV_KEY, 1)[:2] == [1, 0])
c, pad, kbd = shake("vertical", 2, +1)
check("arriba/abajo vienen sin accion de fabrica (no hacen nada)", not pad.events and not kbd.events)
c, pad, kbd = shake("vertical", 1, +1, prep=lambda c: c.set_binding("ShakeUp", "pad:A"))
check("agitar hacia delante/atras no dispara ninguna direccion", not pad.where(dc.EV_KEY, 0x130) and not pad.where(dc.EV_KEY, 0x136))
c, pad, kbd = shake("horizontal", 1, +1)       # de lado: la derecha es el eje y crudo (+)
check("horizontal: agitar a la derecha -> R1", pressed(pad, 0x137) and not pad.where(dc.EV_KEY, 0x136), pad.events[:4])
c, pad, kbd = shake("horizontal", 1, -1)
check("horizontal: agitar a la izquierda -> L1", pressed(pad, 0x136))
c, pad, kbd = shake("horizontal", 0, -1, prep=lambda c: c.set_binding("ShakeUp", "pad:A"))
check("horizontal: agitar hacia arriba", pressed(pad, 0x130))
c, pad, kbd = shake("vertical", 0, -1, prep=lambda c: c.cfg.update(shake_flip_x=True))
check("shake_flip_x invierte izquierda/derecha", pressed(pad, 0x136) and not pad.where(dc.EV_KEY, 0x137))
c, pad, kbd = shake("vertical", 2, +1, prep=lambda c: (c.cfg.update(shake_flip_y=True), c.set_binding("ShakeDown", "pad:B")))
check("shake_flip_y invierte arriba/abajo", pressed(pad, 0x131))
c, pad, kbd = shake("vertical", 0, -1, prep=lambda c: c.set_binding("ShakeRight", "pad:A+pad:B"))
check("una direccion de agitado puede ser una combinacion", pressed(pad, 0x130) and pressed(pad, 0x131))

print("agitar 'de verdad' (todo en Nada)")


def none_all(c):
    for k in dc.SHAKE_INPUTS:
        c.set_binding(k, "none")


c, pad, kbd = shake("vertical", 0, -1, prep=none_all)
check("con las 4 direcciones en Nada no sale ningun boton", not pad.where(dc.EV_KEY, 0x136) and not pad.where(dc.EV_KEY, 0x137))
rs = c.states[0]
check("...y el detector queda apagado", rs.shake_on is False)
# el cursor NO se congela mientras agitas
c, pad, mouse, kbd = new("vertical", "menus"); none_all(c); wm = FakeWm()
dots = lambda dx: [(450 - dx, 384), (570 - dx, 384)]
t = feed(c, wm, [make_report(dots=dots(0), acc=(128, 128, 154))] * 200)
mouse.events.clear()
t = feed(c, wm, [make_report(dots=dots(i // 3), acc=(int(128 + 26 * 2 * math.sin(i / 3.0)), 128, 154)) for i in range(150)], t)
check("sin agitado asignado el cursor sigue moviendose aunque agites", abs(sum(mouse.where(dc.EV_REL, dc.REL_X))) > 20, sum(mouse.where(dc.EV_REL, dc.REL_X)))
c, pad, mouse, kbd = new("vertical", "menus"); wm = FakeWm()
t = feed(c, wm, [make_report(dots=dots(0), acc=(128, 128, 154))] * 200)
mouse.events.clear()
t = feed(c, wm, [make_report(dots=dots(i // 3), acc=(int(128 + 26 * 2 * math.sin(i / 3.0)), 128, 154)) for i in range(150)], t)
check("(con agitado asignado, el cursor se congela como antes)", abs(sum(mouse.where(dc.EV_REL, dc.REL_X))) < 20, sum(mouse.where(dc.EV_REL, dc.REL_X)))
c, pad, kbd = shake("vertical", 0, -1, prep=lambda c: c.cfg.update(shake_enabled=False))
check("shake_enabled=False tambien lo apaga", not pad.where(dc.EV_KEY, 0x137))

# ----------------------------------------------------------------- DSU: puerto ocupado, conexion y acelerometro sin MotionPlus
print("DSU: puerto y conexion")
blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); blocker.bind(("127.0.0.1", 26830))
srv = dc.DSUServer(26830, None)
check("con el puerto ocupado por otro programa se usa el siguiente", srv.start() and srv.port == 26831 and srv.requested_port == 26830, srv.port)
srv.stop()
blocker2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
blocker2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); blocker2.bind(("127.0.0.1", 26840))
srv = dc.DSUServer(26840, None)
check("aunque el otro programa use SO_REUSEADDR no se comparte el puerto", srv.start() and srv.port == 26841, srv.port)
srv.stop(); blocker.close(); blocker2.close()
srv = dc.DSUServer(26850, None); srv.start()
check("DSUServer.set_port cambia de puerto en caliente", (srv.set_port(26860) or True) and srv.sock and srv.port == 26860)
srv.stop()
srv = dc.DSUServer(26870, None); srv.start()
check("sin datos del mando el servidor no se anuncia conectado", srv.alive is False)
cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); cli.settimeout(1.0)
cli.sendto(creq(dc.MSG_INFO, struct.pack("<i", 1) + bytes([0, 0, 0, 0])), ("127.0.0.1", 26870))
r = cli.recv(256); check("...y lo dice al emulador (estado 0)", r[21] == 0, r[21])
srv.mark_alive()
cli.sendto(creq(dc.MSG_INFO, struct.pack("<i", 1) + bytes([0, 0, 0, 0])), ("127.0.0.1", 26870))
r = cli.recv(256); check("con un mando activo si (estado 2)", r[21] == 2, r[21])
srv.stop(); cli.close()

# solo acelerometro: sin MotionPlus (modo Nunchuk) el movimiento sigue llegando y el mando figura conectado
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
check("sin MotionPlus el acelerometro llega al DSU (z ~ 1 g)", vals is not None and abs(vals[2] - -1.0) < 0.2 or (vals is not None and abs(abs(vals[2]) - 1.0) < 0.2), vals)
check("...con el giro a cero", vals is not None and max(abs(x) for x in vals[4:]) < 0.01, vals)
check("...y el servidor cuenta los paquetes enviados", srv.sent > 0 and srv.alive)
srv.stop(); cli.close()

# ----------------------------------------------------------------- acordes de mantener: IR y menu QAM
print("acordes de mantener")
def held(c, wm, mask, secs, t, dt=0.01):
    return feed(c, wm, [make_report(mask)] * int(secs / dt), t, dt=dt)

c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
check("el IR esta activo de fabrica", c.cfg["ir_enabled"] is True)
t = held(c, wm, wl.BTN_DOWN | wl.BTN_PLUS, 1.0, 100.0)
check("Abajo + Plus mantenidos 1 s: todavia no hace nada", c.cfg["ir_enabled"] is True)
t = held(c, wm, wl.BTN_DOWN | wl.BTN_PLUS, 1.3, t)
check("Abajo + Plus mantenidos 2 s -> puntero IR desactivado", c.cfg["ir_enabled"] is False)
check("...sin pulsar Menu (Plus) ni dejar la cruceta apretada", not pad.where(dc.EV_KEY, 0x13B) and pad.where(dc.EV_ABS, dc.ABS_HAT0Y)[-1:] != [1], (pad.where(dc.EV_KEY, 0x13B), pad.where(dc.EV_ABS, dc.ABS_HAT0Y)))
check("...y avisa vibrando", wm.rumbles >= 1)
t = feed(c, wm, [make_report(0)] * 10, t)
t = held(c, wm, wl.BTN_DOWN | wl.BTN_PLUS, 2.2, t)
check("repetirlo lo vuelve a activar", c.cfg["ir_enabled"] is True)
t = feed(c, wm, [make_report(0)] * 10, t)
# soltar antes de los 2 s: nada, y Plus no se cuela como Menu
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
t = held(c, wm, wl.BTN_DOWN | wl.BTN_PLUS, 0.8, 100.0)
t = feed(c, wm, [make_report(0)] * 30, t)
check("soltar antes de tiempo no cambia el IR", c.cfg["ir_enabled"] is True)
check("...ni deja el boton Menu pulsado", pad.where(dc.EV_KEY, 0x13B)[-1:] != [1])
# la cruceta sola sigue sin retraso
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
feed(c, wm, [make_report(wl.BTN_DOWN)] * 2, 100.0)
check("la cruceta sola se pulsa al instante (sin esperar acordes)", 1 in pad.where(dc.EV_ABS, dc.ABS_HAT0Y))
# con el IR apagado el cursor no se mueve, pero A sigue haciendo clic
c, pad, mouse, kbd = new("vertical", "menus"); wm = FakeWm(); c.cfg["ir_enabled"] = False
dots = lambda dx: [(450 - dx, 384), (570 - dx, 384)]
t = feed(c, wm, [make_report(dots=dots(0))] * 200)
t = feed(c, wm, [make_report(dots=dots(i // 3)) for i in range(150)], t)
check("IR apagado: el cursor no se mueve", not mouse.where(dc.EV_REL, dc.REL_X))
t = tap(c, wm, wl.BTN_A, t)
check("...pero A sigue haciendo clic", mouse.where(dc.EV_KEY, 0x110) == [1, 0])
c.cfg["ir_enabled"] = True
t = feed(c, wm, [make_report(dots=dots(0))] * 100, t)
t = feed(c, wm, [make_report(dots=dots(i // 3)) for i in range(150)], t)
check("IR reactivado: el cursor se mueve otra vez", abs(sum(mouse.where(dc.EV_REL, dc.REL_X))) > 20)
# Home + Plus -> QAM
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
calls = []; c.on_open_qam = lambda: calls.append(1)
t = held(c, wm, wl.BTN_HOME | wl.BTN_PLUS, 1.0, 100.0)
check("Home + Plus 1 s: aun no abre el menu", not calls)
t = held(c, wm, wl.BTN_HOME | wl.BTN_PLUS, 1.3, t)
check("Home + Plus 2 s -> abre el menu ... (callback del plugin)", calls == [1], calls)
check("...sin pulsar el boton Steam ni Menu", not pad.where(dc.EV_KEY, 0x13C) and not pad.where(dc.EV_KEY, 0x13B))
t = held(c, wm, wl.BTN_HOME | wl.BTN_PLUS, 3.0, t)
check("mantener mas tiempo no lo repite", calls == [1], calls)
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()          # sin plugin: Steam + A
t = held(c, wm, wl.BTN_HOME | wl.BTN_PLUS, 2.3, 100.0)
time.sleep(0.4)
check("sin plugin de Decky envia Steam + A", pad.where(dc.EV_KEY, 0x13C)[:1] == [1] and pad.where(dc.EV_KEY, 0x130)[:1] == [1], (pad.where(dc.EV_KEY, 0x13C), pad.where(dc.EV_KEY, 0x130)))
check("...y los suelta", pad.where(dc.EV_KEY, 0x13C)[-1:] == [0] and pad.where(dc.EV_KEY, 0x130)[-1:] == [0])
# Home solo sigue siendo Guia, + y - siguen cambiando de perfil, Plus solo sigue siendo Menu
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
t = feed(c, wm, [make_report(wl.BTN_PLUS)] * 15 + [make_report(0)] * 15, 100.0)
check("Plus solo = Menu (Start)", pad.where(dc.EV_KEY, 0x13B) == [1, 0])
t = feed(c, wm, [make_report(wl.BTN_PLUS | wl.BTN_MINUS)] * 30 + [make_report(0)] * 5, t)
check("+ y - siguen cambiando de perfil", c.profile != "juego")
# asignable a un boton cualquiera
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
c.set_binding("A", "app:toggle_pointer"); t = tap(c, wm, wl.BTN_A, 100.0)
check("'Puntero IR si/no' se puede asignar a un boton", c.cfg["ir_enabled"] is False)
check("'Abrir menu QAM' existe como accion asignable", c.set_binding("B", "app:open_qam"))

# ----------------------------------------------------------------- agitar el Nunchuk
print("nunchuk agitado")
def nun_acc_ext(ax):
    """ext del Nunchuk con la aceleracion X (10 bits, cero 512, 1 g = 200) y la palanca centrada."""
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
check("de fabrica agitar el Nunchuk no hace nada (no cambia el comportamiento)", not pad.where(dc.EV_KEY, 0x130) and not kbd.events)
c, pad, kbd = nun_shake("pad:A")
check("agitar el Nunchuk -> boton asignado", pad.where(dc.EV_KEY, 0x130)[:2] == [1, 0], pad.events[:6])
c, pad, kbd = nun_shake("key:ESC")
check("...o una tecla / accion cualquiera", kbd.where(dc.EV_KEY, 1)[:2] == [1, 0])
c, pad, kbd = nun_shake("pad:A", amp=0.05)
check("un movimiento suave del Nunchuk no dispara nada", not pad.where(dc.EV_KEY, 0x130))
c, pad, kbd = nun_shake("pad:A", secs=0.0)
check("reposo: nada", not pad.where(dc.EV_KEY, 0x130))
check("Nunchuk: agitar es una entrada del editor", "NunShake" in dict(dc.INPUTS))

# ----------------------------------------------------------------- aplicar en lote
print("aplicar cambios en lote")
c, pad, mouse, kbd = new("vertical", "juego"); wm = FakeWm()
pid = c.create_profile("Lote")
saves = []; dc.save_config = lambda cfg: saves.append(1)
ok = c.apply_bindings([("juego", "vertical", "A", "pad:Y"), ("juego", "horizontal", "Plus", "key:ESC"), (pid, "vertical", "B", "pad:A+pad:X")])
check("apply_bindings aplica varios cambios de golpe", ok and dc.effective_bindings(c.cfg, "juego", "vertical")["A"] == "pad:Y"
      and dc.effective_bindings(c.cfg, "juego", "horizontal")["Plus"] == "key:ESC" and dc.effective_bindings(c.cfg, pid, "vertical")["B"] == "pad:A+pad:X")
check("...y guarda UNA sola vez", len(saves) == 1, len(saves))
saves.clear()
before = json.dumps(c.cfg["profiles"], sort_keys=True)
ok = c.apply_bindings([("juego", "vertical", "B", "pad:X"), ("juego", "vertical", "A", "pad:NOPE")])
check("todo o nada: un cambio invalido no deja aplicar ninguno", ok is False and json.dumps(c.cfg["profiles"], sort_keys=True) == before and not saves)
check("perfil o modo inexistente -> rechazado", c.apply_bindings([("p99", "vertical", "A", "pad:A")]) is False and c.apply_bindings([("juego", "raro", "A", "pad:A")]) is False)
check("basura -> rechazado, lista vacia -> vale", c.apply_bindings([("a", "b")]) is False and c.apply_bindings([]) is True)
dc.save_config = lambda c: None

# ----------------------------------------------------------------- servicio / API que usa la ventana y Decky
print("API de servicio")
svc = dc.DeckService(*[FakeUInput() for _ in range(3)], use_lock=False)
svc.cfg = dc.load_config(); svc.log = wl.EventLog(tempfile.mkdtemp(), "t")
svc.dsu = dc.DSUServer(PORT + 2, svc.log)
svc.ctrl = dc.DeckController(svc.cfg, svc.log, *svc._fakes, dsu=svc.dsu); svc.ctrl.open_devices()
svc.mgr = wl.Manager(log=svc.log, on_frame=svc.ctrl.on_frame)
view = svc.bindings_view("horizontal", "juego")
names = {i["input"]: i for i in view["inputs"]}
check("bindings_view lista todas las entradas", set(names) == set(dict(dc.INPUTS)))
check("la cruceta horizontal aparece como stick", names["Up"]["value"] == "lstick:left", names["Up"]["value"])
check("Pointer/NunStick traen sus propias opciones", names["Pointer"]["options"] and names["NunStick"]["options"] and names["A"]["options"] is None)
check("hay acciones para botones, sticks, raton, teclado y programa", {a["group"] for a in view["actions"]} >= {"Botones", "Stick izquierdo", "Raton", "Teclado", "Programa"})
st = svc.status()
check("status() es serializable a JSON", __import__("json").dumps(st) and st["profile"] in dc.PROFILES)


print("acceso rapido de perfiles y notificaciones")
c, pad, mouse, kbd = new("vertical", "menus")
notes = []
c.on_notify = lambda t, b: notes.append(b)
c.set_mode("horizontal"); c.set_mode("horizontal")
check("cambiar de modo avisa una vez (y no si no cambia)", notes == ["Modo: Horizontal"], notes)
c.set_profile("juego")
check("cambiar de perfil avisa con su nombre", notes[-1] == "Perfil: Juegos", notes)
pid = c.create_profile("Mi perfil")
check("un perfil nuevo NO entra en el acceso rapido", pid not in c.cfg["quick_profiles"] and pid not in c.quick_profile_ids())
c.set_profile("menus")
c._app("toggle_profile")
check("+ y - rotan solo por los de acceso rapido", c.profile == "juego", c.profile)
c._app("toggle_profile")
check("...y vuelven al primero sin pasar por el nuevo", c.profile == "menus", c.profile)
c.set_quick_profiles(["menus", pid, "nope"])
check("se ignoran ids que no existen", c.cfg["quick_profiles"] == ["menus", pid], c.cfg["quick_profiles"])
c._app("toggle_profile")
check("ahora rota por el perfil nuevo", c.profile == pid, c.profile)
c.set_quick_profiles([])
c._app("toggle_profile")
check("lista vacia: + y - no hacen nada", c.profile == pid, c.profile)
c.set_quick_profiles(["menus", pid])
c.delete_profile(pid)
check("borrar un perfil lo quita del acceso rapido", c.cfg["quick_profiles"] == ["menus"], c.cfg["quick_profiles"])
c.on_notify = lambda t, b: 1 / 0
c.set_mode("vertical")
check("un fallo en la notificacion no rompe el cambio", c.mode == "vertical")
check("set_option no toca quick_profiles", c.set_option("quick_profiles", ["x"]) is False)

print("\n%d correctas, %d fallos" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
