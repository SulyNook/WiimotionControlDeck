"""Backend del plugin de Decky con un modulo 'decky' falso: arranque, API y apagado."""
import asyncio, os, sys, types, tempfile, logging
from helpers import *
import deckcore as dc

home = tempfile.mkdtemp()
fake = types.ModuleType("decky")
fake.DECKY_USER_HOME = home
fake.logger = logging.getLogger("decky-fake")
sys.modules["decky"] = fake
dc.LOCK_PATH = os.path.join(home, "wiideck.lock")
sys.path.insert(0, os.path.join(ROOT, "decky", "WiiDeck"))
import main as plugin_main

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  ok   ", name)
    else: FAIL += 1; print("  FALLA", name, extra)

def run(c): return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(c)

p = plugin_main.Plugin()
# los dispositivos virtuales reales no existen aqui: se usan falsos
orig = dc.DeckService.__init__
dc.DeckService.__init__ = lambda self, *a, **k: orig(self, FakeUInput(), FakeUInput(), FakeUInput(), use_lock=True)
run(p._main())
check("el plugin arranca", p.svc is not None and p.svc.started, p.error)
st = run(p.get_status())
check("get_status: en marcha y serializable", st["running"] and __import__("json").dumps(st))
check("la config se guarda en la carpeta del usuario de Decky", dc.CONFIG_DIR.startswith(home))
run(p.set_mode("horizontal")); check("set_mode", run(p.get_status())["mode"] == "horizontal")
run(p.set_profile("juego")); check("set_profile", run(p.get_status())["profile"] == "juego")
run(p.set_enabled(False)); check("set_enabled(False) -> interruptor principal", run(p.get_status())["enabled"] is False)
run(p.set_enabled(True)); check("set_enabled(True)", run(p.get_status())["enabled"] is True)
check("set_binding valido", run(p.set_binding("A", "pad:Y", "vertical", "juego")) is True)
check("set_binding invalido", run(p.set_binding("A", "pad:NOPE", "vertical", "juego")) is False)
bv = run(p.get_bindings("vertical", "juego"))
check("get_bindings refleja el cambio", {i["input"]: i["value"] for i in bv["inputs"]}["A"] == "pad:Y")
run(p.reset_bindings("vertical", "juego"))
bv = run(p.get_bindings("vertical", "juego"))
check("reset_bindings", {i["input"]: i["value"] for i in bv["inputs"]}["A"] == "pad:A")
check("set_option (sensibilidad del giroscopio)", run(p.set_option("gyro_stick_gain", 2.0)) and run(p.get_status())["gyro_stick_gain"] == 2.0)
check("set_option rechaza claves internas", run(p.set_option("profiles", {})) is False)
check("calibrate no falla", run(p.calibrate()) is True)
# segunda instancia (p. ej. la AppImage abierta a la vez): se rechaza con un mensaje claro
p2 = plugin_main.Plugin(); run(p2._main())
check("segunda instancia rechazada con mensaje", p2.svc is None and "otra instancia" in p2.error, p2.error)
st2 = run(p2.get_status())
check("...y get_status lo cuenta sin romperse", st2["running"] is False and st2["error"])
run(p._unload())
check("_unload detiene el servicio", p.svc is None)
print("\n%d correctas, %d fallos" % (PASS, FAIL)); sys.exit(1 if FAIL else 0)
