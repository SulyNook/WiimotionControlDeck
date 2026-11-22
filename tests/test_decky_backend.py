"""Backend del plugin de Decky con un modulo 'decky' falso: arranque, API, apagado completo, reinicio y QAM."""
import asyncio, json, os, sys, types, tempfile, logging, time
from helpers import *
import deckcore as dc

home = tempfile.mkdtemp()
EMITTED = []
fake = types.ModuleType("decky")
fake.DECKY_USER_HOME = home
fake.logger = logging.getLogger("decky-fake")
async def _emit(event, *a): EMITTED.append(event)
fake.emit = _emit
sys.modules["decky"] = fake
dc.LOCK_PATH = os.path.join(home, "wiideck.lock")
sys.path.insert(0, os.path.join(ROOT, "decky", "WiiDeck"))
import main as plugin_main

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  ok   ", name)
    else: FAIL += 1; print("  FALLA", name, extra)

loop = asyncio.new_event_loop()
def run(c): return loop.run_until_complete(c)

# los dispositivos virtuales reales no existen aqui: se usan falsos
orig = dc.DeckService.__init__
dc.DeckService.__init__ = lambda self, *a, **k: orig(self, FakeUInput(), FakeUInput(), FakeUInput(), use_lock=True)

p = plugin_main.Plugin()
run(p._main())
check("el plugin arranca", p.svc is not None and p.svc.started, p.error)
st = run(p.get_status())
check("get_status: en marcha y serializable", st["running"] and st["active"] and json.dumps(st))
check("la config se guarda en la carpeta del usuario de Decky", dc.CONFIG_DIR.startswith(home))
check("ir_enabled viaja en el estado", st["ir_enabled"] is True and "profiles" in st)
run(p.set_mode("horizontal")); check("set_mode", run(p.get_status())["mode"] == "horizontal")
run(p.set_profile("juego")); check("set_profile", run(p.get_status())["profile"] == "juego")
check("set_binding valido", run(p.set_binding("A", "pad:Y", "vertical", "juego")) is True)
check("set_binding invalido", run(p.set_binding("A", "pad:NOPE", "vertical", "juego")) is False)
run(p.reset_bindings("vertical", "juego"))
bv = run(p.get_bindings("vertical", "juego"))
check("reset_bindings", {i["input"]: i["value"] for i in bv["inputs"]}["A"] == "pad:A")
check("set_option (sensibilidad del giroscopio)", run(p.set_option("gyro_stick_gain", 2.0)) and run(p.get_status())["gyro_stick_gain"] == 2.0)
check("set_option rechaza claves internas", run(p.set_option("profiles", {})) is False)
check("calibrate no falla", run(p.calibrate()) is True)

print("IR, perfiles y cambios en lote")
check("interruptor del puntero IR", run(p.set_option("ir_enabled", False)) and run(p.get_status())["ir_enabled"] is False)
run(p.set_option("ir_enabled", True))
pid = run(p.create_profile("Zelda"))
st = run(p.get_status())
check("crear perfil (en blanco) y listarlo", pid and any(x["id"] == pid and x["title"] == "Zelda" and x["custom"] for x in st["profiles"]))
check("nombre vacio rechazado", run(p.create_profile("  ")) is None)
ch = [["juego", "vertical", "A", "pad:Y"], ["juego", "vertical", "B", "key:ESC"], [pid, "horizontal", "Plus", "pad:A+pad:B"]]
check("apply_bindings aplica los cambios acumulados", run(p.apply_bindings(ch)) is True)
b1 = {i["input"]: i["value"] for i in run(p.get_bindings("vertical", "juego"))["inputs"]}
b2 = {i["input"]: i["value"] for i in run(p.get_bindings("horizontal", pid))["inputs"]}
check("...y se ven en el editor", b1["A"] == "pad:Y" and b1["B"] == "key:ESC" and b2["Plus"] == "pad:A+pad:B", (b1["A"], b2["Plus"]))
check("apply_bindings es todo o nada", run(p.apply_bindings([["juego", "vertical", "A", "pad:X"], ["juego", "vertical", "B", "pad:NOPE"]])) is False
      and {i["input"]: i["value"] for i in run(p.get_bindings("vertical", "juego"))["inputs"]}["A"] == "pad:Y")
check("borrar perfil propio", run(p.delete_profile(pid)) is True and not any(x["id"] == pid for x in run(p.get_status())["profiles"]))
check("no se borran los de fabrica", run(p.delete_profile("menus")) is False)

print("menu ... (QAM)")
EMITTED.clear()
p.svc.ctrl.on_open_qam()           # lo que hace Home + Plus mantenidos (desde el hilo del controlador)
run(asyncio.sleep(0.05))
check("Home + Plus pide a la interfaz abrir el menu ...", EMITTED == ["open_qam"], EMITTED)
check("el callback sobrevive a un reinicio del servicio", (run(p.restart()) or True) and p.svc.ctrl.on_open_qam is not None)


print("notificaciones y acceso rapido (plugin)")
EMITTED.clear()
run(p.set_mode("nunchuk")); run(asyncio.sleep(0.05))
check("cambiar de modo emite 'notify'", "notify" in EMITTED, EMITTED)
check("el plugin conecta el aviso al servicio", p.svc.on_notify is not None and p.svc.ctrl.on_notify is not None)
check("set_quick_profiles", run(p.set_quick_profiles(["juego"])) is True and run(p.get_status())["quick_profiles"] == ["juego"])

print("perfil copia (plugin)")
run(p.set_binding("A", "key:ENTER", "vertical", "juego"))
cid = run(p.create_profile("Copia plugin", "juego"))
check("create_profile(nombre, copy_from) copia el perfil", dc.effective_bindings(p.svc.cfg, cid, "vertical")["A"] == "key:ENTER")
bid = run(p.create_profile("En blanco plugin"))
check("sin copy_from sigue en blanco", dc.effective_bindings(p.svc.cfg, bid, "vertical")["A"] == "none")
view = run(p.get_bindings("vertical", cid))
check("el editor del plugin recibe tipos y acciones con su tipo", view["categories"] == ["Mando", "Teclado", "Raton", "Programa"] and all("cat" in x for x in view["actions"]))
check("status incluye el pico de aceleracion", "peak" in run(p.get_status())["motion"])
run(p.set_binding("A", "pad:Y", "vertical", "juego"))      # deja el perfil como lo esperan las pruebas siguientes

print("sacudida sintetica (plugin)")
check("eden_shake lanza el pulso", run(p.eden_shake("left")) is True and p.svc.ctrl._eden_pulse is not None)
check("prueba continua desde el plugin", run(p.eden_shake("up", 5)) is True and p.svc.ctrl._eden_pulse[2] == 5.0)
check("direccion mala -> False", run(p.eden_shake("xx")) is False)
check("set_option de la fuerza", run(p.set_option("eden_shake_amp", 7.0)) is True and run(p.get_status())["eden_shake_amp"] == 7.0)
check("set_option de los avisos", run(p.set_option("notify_enabled", False)) is True and run(p.get_status())["notify_enabled"] is False)
run(p.set_option("notify_enabled", True)); run(p.set_option("eden_shake_amp", 5.0))

print("apagado completo y reinicio")
run(p.set_profile("juego")); run(p.set_option("px_per_deg", 77))
before = json.dumps(json.load(open(dc.CONFIG_PATH))["profiles"], sort_keys=True)
check("hay perfiles guardados antes de apagar", "juego" in before)
pad_dev = p.svc.ctrl.pad
check("desactivar devuelve False (apagado)", run(p.set_enabled(False)) is False)
check("...el servicio esta parado de verdad y el gamepad virtual cerrado", p.svc.started is False and pad_dev.opened is False)
st = run(p.get_status())
check("...y el estado lo dice (sin error)", st["running"] is False and st["active"] is False and not st["error"], st)
check("...el DSU y el candado se liberan", p.svc.dsu.sock is None and p.svc._lock_fd is None)
cfg = json.load(open(dc.CONFIG_PATH))
check("...se recuerda que esta apagado y se conserva TODO", cfg["enabled"] is False and json.dumps(cfg["profiles"], sort_keys=True) == before and cfg["px_per_deg"] == 77 and cfg["profile"] == "juego")
check("estando apagado la API no rompe", run(p.set_profile("menus")) is False and run(p.get_bindings()) is None and run(p.set_option("px_per_deg", 5)) is False)
# otra instancia puede tomar el candado ahora que esta apagado
other = dc.DeckService(FakeUInput(), FakeUInput(), FakeUInput(), use_lock=True); other.start(); other.stop()
check("apagado: otra instancia (la AppImage) puede arrancar", True)
check("activar de nuevo arranca", run(p.set_enabled(True)) is True and p.svc.started)
st = run(p.get_status())
check("...el gamepad virtual se abre de nuevo", p.svc.ctrl.pad.opened is True)
check("...con los perfiles y ajustes de antes", st["profile"] == "juego" and st["px_per_deg"] == 77 and dc.effective_bindings(p.svc.cfg, "juego", "vertical")["A"] == "pad:Y")
check("...y enabled vuelve a True en el disco", json.load(open(dc.CONFIG_PATH))["enabled"] is True)
t0 = p.svc.mgr
check("reiniciar: mandos nuevos y estado conservado", run(p.restart()) is True and p.svc.mgr is not t0 and run(p.get_status())["px_per_deg"] == 77)
run(p.set_enabled(False)); p3 = plugin_main.Plugin(); run(p3._main())
check("al volver a cargar el plugin apagado se queda apagado", p3.svc.started is False and run(p3.get_status())["running"] is False)
run(p3.set_enabled(True)); check("...y se enciende desde cero", p3.svc.started)

print("segunda instancia")
p2 = plugin_main.Plugin(); run(p2._main())
check("segunda instancia rechazada con mensaje", p2.svc.started is False and "otra instancia" in p2.error, p2.error)
st2 = run(p2.get_status())
check("...y get_status lo cuenta sin romperse", st2["running"] is False and st2["error"])
check("...y se puede reintentar al liberarse", (run(p3._unload()) or True) and run(p2.restart()) is True)
run(p2._unload())
check("_unload detiene el servicio", p2.svc.started is False and p3.svc.started is False)

print("\n%d correctas, %d fallos" % (PASS, FAIL)); sys.exit(1 if FAIL else 0)
