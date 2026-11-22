"""Ejecuta el codigo de las ventanas con un tkinter falso para cazar errores de Python (no valida la API real de Tk)."""
import sys, types, tempfile, math, time
from helpers import *

ALL = []
class FakeWidget:
    def __init__(self, *a, **k): self.a, self.k = a, k; self.calls = []; ALL.append(self)
    def __getattr__(self, name):
        if name.startswith("__"): raise AttributeError(name)
        def f(*a, **k):
            self.calls.append((name, a, k))
            if name == "winfo_width": return 1000
            if name == "winfo_height": return 700
            if name == "focus_get": return None
            if name == "get": return ""
            return None
        return f

class FakeRoot(FakeWidget):
    def __init__(self, *a, **k):
        super().__init__(); self.cb = []; self.runs = 0
    def after(self, ms, fn): self.cb.append(fn)
    def mainloop(self):
        while self.cb and self.runs < 6:
            self.runs += 1; self.cb.pop(0)()

class FakeVar:
    def __init__(self, value=None): self.v = value
    def get(self): return self.v
    def set(self, v): self.v = v

tk = types.ModuleType("tkinter")
for n in ("Frame", "Label", "Button", "Canvas", "Entry", "Checkbutton", "Scale", "Text", "Toplevel"):
    setattr(tk, n, FakeWidget)
tk.Tk = FakeRoot; tk.BooleanVar = FakeVar; tk.DoubleVar = FakeVar
sys.modules["tkinter"] = tk

# ---- WiiSim
import wiisim, simcore as sc, wiilink as wl
log = wl.EventLog(tempfile.mkdtemp(), "t", sc.CSV_HEADER)
cfg = wiisim.load_config()
app = wiisim.SimApp(cfg, log)
class W: pass
wm = W(); wm.slot = 0; wm.use_mp = True; wm.acc_zero = [128.0]*3; wm.acc_one = [154.0]*3; wm.battery = 70; wm.status_text = "Activo"
for i in range(300):
    app.on_frame(wm, wl.parse_data_report(make_report(acc=(128,128,154), dots=[(400,380),(560,382)]), 10 + i*0.006))
class FakeMgr: hid_seen = 1; problems = []
app.mgr = FakeMgr()
orig_snap = app.snapshots
app.snapshots = lambda: [(sl, dict(s, t=time.monotonic(), trail=list(app.sims[sl].trail))) for sl, s in orig_snap_raw()] if False else orig_snap()
# el snapshot usa tiempo de los informes: se fuerza "reciente"
for sim in app.sims.values(): sim.snapshot["t"] = time.monotonic()
wiisim.run_gui(app, log, cfg)
print("WiiSim: ventana simulada OK (sin excepciones; errores registrados: %d)" % sum(1 for l in log.tail if "ERROR" in l))
assert not any("ERROR" in l for l in log.tail), log.tail

# ---- WiiDeck 0.2 (ventana sobre DeckService)
import deckcore as dc
dc.save_config = lambda c: None
dc.CONFIG_PATH = "/nonexistent/config.json"
import wiideck as wd
class FWm:
    slot = 0; status_text = "Activo"; battery = 80; connected = True; acc_zero=[128.0]*3; acc_one=[154.0]*3
    def set_led(self, m): pass
    def rumble(self, s=0.1): pass
    def request_reinit(self): pass
fw = FWm()
class Mgr2:
    hid_seen = 1; problems = ["prueba"]
    def wiimotes(self): return [fw]
svc = dc.DeckService(FakeUInput(), FakeUInput(), FakeUInput(), use_lock=False)
svc.cfg = dc.load_config(); svc.cfg["profile"] = "juego"
svc.log = wl.EventLog(tempfile.mkdtemp(), "t2")
svc.dsu = dc.DSUServer(26795, svc.log)
svc.ctrl = dc.DeckController(svc.cfg, svc.log, *svc._fakes, dsu=svc.dsu); svc.ctrl.open_devices()
svc.mgr = Mgr2()
for i in range(50):
    svc.ctrl.on_frame(fw, wl.parse_data_report(make_report(dots=[(450,384),(570,384)]), 5+i*0.006))
wd.run_gui(svc)
print("WiiDeck: ventana simulada OK")
assert not any("ERROR" in l for l in svc.log.tail), svc.log.tail

def find(pred):
    return [w for w in ALL if pred(w)]
def cmd(w): return w.k.get("command")

# pestanas
tabs = find(lambda w: w.k.get("text") in ("INICIO", "BOTONES", "MOVIMIENTO") and cmd(w))
assert len(tabs) == 3
for t in tabs: cmd(t)()
# editor: abrir el selector de "A", elegir "Intro" y comprobar que se guarda en el perfil/modo editado
a_btn = find(lambda w: cmd(w) and getattr(cmd(w), "__defaults__", None) == ("A",))
assert len(a_btn) == 1, "no se encuentra el boton de asignacion de A"
n0 = len(ALL)
cmd(a_btn[0])()
intro = [w for w in ALL[n0:] if w.k.get("text") == "Intro"]
assert len(intro) == 1, "el selector no ofrece 'Intro'"
cmd(intro[0])()
assert svc.cfg["profiles"]["juego"]["vertical"]["A"] == "key:ENTER", svc.cfg["profiles"]
print("WiiDeck: editor de botones OK (A -> Intro guardado en Juegos/Vertical)")
# selector del puntero y del stick del Nunchuk usan sus propias opciones
n0 = len(ALL)
cmd(find(lambda w: cmd(w) and getattr(cmd(w), "__defaults__", None) == ("Pointer",))[0])()
opts = {w.k.get("text") for w in ALL[n0:] if w.k.get("text")}
assert "Desactivado" in opts and "Mueve el raton" in opts and "Intro" not in opts, opts
cmd(find(lambda w: w.k.get("text") == "Desactivado")[-1])()
assert svc.cfg["profiles"]["juego"]["vertical"]["Pointer"] == "none"
# editar OTRO modo no cambia el modo activo
cmd(find(lambda w: w.k.get("text") == "Horizontal" and cmd(w))[0])()
assert svc.ctrl.mode == "vertical"
# interruptor principal
m = find(lambda w: cmd(w) and w.k.get("width") == 18 and w.k.get("height") == 2)
assert m, "no se encuentra el interruptor general"
cmd(m[0]())  if False else cmd(m[0])()
assert svc.cfg["enabled"] is False
cmd(m[0])()
assert svc.cfg["enabled"] is True
print("WiiDeck: interruptor general OK")
assert not any("ERROR" in l for l in svc.log.tail), svc.log.tail
