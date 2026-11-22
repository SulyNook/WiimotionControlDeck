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

print("\n%d correctas, %d fallos" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
