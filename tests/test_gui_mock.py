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
svc.started = True
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
assert "juego" not in svc.cfg["profiles"], "un cambio NO debe guardarse hasta APLICAR: %r" % svc.cfg["profiles"]
assert svc.bindings_view("vertical", "juego")["inputs"][1]["value"] == "pad:A", "...ni aplicarse"
n0 = len(ALL)
cmd([w for w in ALL if cmd(w) and getattr(cmd(w), "__defaults__", None) == ("B",)][-1])()
cmd([w for w in ALL[n0:] if w.k.get("text") == "Espacio"][-1])()           # un segundo cambio antes de aplicar
assert "juego" not in svc.cfg["profiles"]
cmd([w for w in ALL if w.k.get("text") == "APLICAR" and cmd(w)][-1])()
assert svc.cfg["profiles"]["juego"]["vertical"]["A"] == "key:ENTER", svc.cfg["profiles"]
assert svc.cfg["profiles"]["juego"]["vertical"]["B"] == "key:SPACE", svc.cfg["profiles"]
print("WiiDeck: editor de botones OK (varios cambios acumulados, se guardan juntos con APLICAR)")
# DESCARTAR tira los cambios pendientes
cmd([w for w in ALL if cmd(w) and getattr(cmd(w), "__defaults__", None) == ("Two",)][-1])()
cmd([w for w in ALL if w.k.get("text") == "Tab" and cmd(w)][-1])()
cmd([w for w in ALL if w.k.get("text") == "DESCARTAR" and cmd(w)][-1])()
cmd([w for w in ALL if w.k.get("text") == "APLICAR" and cmd(w)][-1])()
assert "Two" not in svc.cfg["profiles"]["juego"]["vertical"], svc.cfg["profiles"]["juego"]
print("WiiDeck: DESCARTAR OK")
# selector del puntero y del stick del Nunchuk usan sus propias opciones
n0 = len(ALL)
cmd(find(lambda w: cmd(w) and getattr(cmd(w), "__defaults__", None) == ("Pointer",))[0])()
opts = {w.k.get("text") for w in ALL[n0:] if w.k.get("text")}
assert "Desactivado" in opts and "Mueve el raton" in opts and "Intro" not in opts, opts
cmd(find(lambda w: w.k.get("text") == "Desactivado")[-1])()
assert "Pointer" not in svc.cfg["profiles"]["juego"]["vertical"], "pendiente hasta APLICAR"
cmd([w for w in ALL if w.k.get("text") == "APLICAR" and cmd(w)][-1])()
assert svc.cfg["profiles"]["juego"]["vertical"]["Pointer"] == "none"
# la sacudida del Nunchuk se puede asignar
assert find(lambda w: cmd(w) and getattr(cmd(w), "__defaults__", None) == ("NunShake",)), "falta Nunchuk: agitar en el editor"
# interruptor del puntero IR y boton de reinicio en la cabecera
ir = find(lambda w: cmd(w) and w.k.get("width") == 14 and w.k.get("height") == 2 and w.k.get("text") == "")
assert ir, "falta el boton del puntero IR"
cmd(ir[0])(); assert svc.cfg["ir_enabled"] is False
cmd(ir[0])(); assert svc.cfg["ir_enabled"] is True
assert find(lambda w: w.k.get("text") == "REINICIAR\nTODO" and cmd(w)), "falta el boton de reinicio"
print("WiiDeck: interruptor del IR OK")
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

# ---- WiiDeck 0.3: perfiles propios, huecos "+" y agitar
ROOT = [w for w in ALL if isinstance(w, FakeRoot)][-1]
def tick():
    assert ROOT.cb, "la ventana dejo de refrescarse"
    ROOT.cb.pop(0)()
def click(text):
    ws = [w for w in ALL if w.k.get("text") == text and cmd(w)]
    assert ws, "no hay boton %r" % text
    cmd(ws[-1])()
def labels_now(n0):
    return [w.k.get("text") for w in ALL[n0:] if w.k.get("text")]

tick()
assert any(w.k.get("text") == "+ Añadir perfil" for w in ALL), "falta '+ Añadir perfil'"
click("+ Añadir perfil")
for ch in "mi":
    click(ch)
click("ESPACIO")
for ch in "zelda":
    click(ch)
click("CREAR PERFIL")
assert list(svc.cfg["custom_profiles"].values()) == ["mi zelda"], svc.cfg["custom_profiles"]
pid = list(svc.cfg["custom_profiles"])[0]
blank = dc.effective_bindings(svc.cfg, pid, "vertical")
assert all(v == "none" for v in blank.values())
print("WiiDeck: '+ Añadir perfil' con teclado en pantalla OK (perfil en blanco)")
tick()
assert any(w.k.get("text") == "MI ZELDA" for w in ALL), "el perfil nuevo no sale en Inicio"
click("MI ZELDA")
assert svc.ctrl.profile == pid
click("Vertical")          # el editor se quedo en Horizontal mas arriba
# huecos "+": A, luego B, X, Y (maximo 4)
cmd([w for w in ALL if cmd(w) and getattr(cmd(w), "__defaults__", None) == ("A",)][-1])()
click("B")
n0 = len(ALL); labs = labels_now(n0)
click("+  añadir"); click("X")
click("+  añadir"); click("Y")
click("+  añadir"); click("L1")
n0 = len(ALL)
cmd([w for w in ALL if cmd(w) and getattr(cmd(w), "__defaults__", None) == ("A",)][-1])()
assert "+  añadir" not in labels_now(n0), "con 4 botones ya no debe ofrecer otro hueco"
click("Quitar este")
assert "A" not in svc.cfg.get("profiles", {}).get(pid, {}).get("vertical", {}), "nada se guarda hasta APLICAR"
click("APLICAR")
assert svc.cfg["profiles"][pid]["vertical"]["A"] == "pad:X+pad:Y+pad:TL", svc.cfg["profiles"][pid]   # se quito el 1.er hueco (B)
print("WiiDeck: huecos '+' (A + B + ... hasta 4) y 'Quitar este' OK")
# agitar: 4 direcciones asignables
cmd([w for w in ALL if cmd(w) and getattr(cmd(w), "__defaults__", None) == ("ShakeUp",)][-1])()
click("Esc"); click("APLICAR"); assert svc.cfg["profiles"][pid]["vertical"]["ShakeUp"] == "key:ESC"
labs_inputs = [i["input"] for i in svc.bindings_view("vertical", pid)["inputs"]]
assert all(k in labs_inputs for k in dc.SHAKE_INPUTS)
# los dos perfiles de fabrica no se pueden borrar y el propio si (con confirmacion)
tick()
click("Borrar perfil"); assert pid in svc.cfg["custom_profiles"], "debe pedir confirmacion"
click("Borrar perfil"); assert pid not in svc.cfg["custom_profiles"] and svc.ctrl.profile == "menus"
print("WiiDeck: agitar x4 y borrar perfil (con confirmacion) OK")
# pestaña de movimiento: puerto DSU
def port_btn(txt):
    return [w for w in ALL if w.k.get("text") == txt and cmd(w) and w.k.get("width") == 3][-1]
cmd(port_btn("-"))()
assert svc.cfg["dsu_port"] == dc.DEFAULT_CONFIG["dsu_port"] - 1
cmd(port_btn("+"))()
assert svc.cfg["dsu_port"] == dc.DEFAULT_CONFIG["dsu_port"]
tick()
assert not any("ERROR" in l for l in svc.log.tail), svc.log.tail
