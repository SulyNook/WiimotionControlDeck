"""Runs the window code with a fake tkinter to catch Python errors (does not validate the real Tk API)."""
import sys, types, tempfile, math, time
from helpers import *

ALL = []
class FakeWidget:
    def __init__(self, *a, **k): self.a, self.k = a, k; self.calls = []; ALL.append(self)
    def __getattr__(self, name):
        if name.startswith("__"): raise AttributeError(name)
        def f(*a, **k):
            self.calls.append((name, a, k))
            if name in ("config", "configure"): self.k.update(k)
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
wm = W(); wm.slot = 0; wm.use_mp = True; wm.acc_zero = [128.0]*3; wm.acc_one = [154.0]*3; wm.battery = 70; wm.status_text = "Active"
for i in range(300):
    app.on_frame(wm, wl.parse_data_report(make_report(acc=(128,128,154), dots=[(400,380),(560,382)]), 10 + i*0.006))
class FakeMgr: hid_seen = 1; problems = []
app.mgr = FakeMgr()
orig_snap = app.snapshots
app.snapshots = lambda: [(sl, dict(s, t=time.monotonic(), trail=list(app.sims[sl].trail))) for sl, s in orig_snap_raw()] if False else orig_snap()
# the snapshot uses report time: force it to be "recent"
for sim in app.sims.values(): sim.snapshot["t"] = time.monotonic()
wiisim.run_gui(app, log, cfg)
print("WiiSim: simulated window OK (no exceptions; logged errors: %d)" % sum(1 for l in log.tail if "ERROR" in l))
assert not any("ERROR" in l for l in log.tail), log.tail

# ---- WimotionControlDeck 0.2 (window on top of DeckService)
import deckcore as dc
dc.save_config = lambda c: None
dc.CONFIG_PATH = "/nonexistent/config.json"
import wimotioncontroldeck as wd
class FWm:
    slot = 0; status_text = "Active"; battery = 80; connected = True; acc_zero=[128.0]*3; acc_one=[154.0]*3
    def set_led(self, m): pass
    def rumble(self, s=0.1): pass
    def request_reinit(self): pass
fw = FWm()
class Mgr2:
    hid_seen = 1; problems = ["test"]
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
print("WimotionControlDeck: simulated window OK")
assert not any("ERROR" in l for l in svc.log.tail), svc.log.tail

def find(pred):
    return [w for w in ALL if pred(w)]
def cmd(w): return w.k.get("command")

# tabs
tabs = find(lambda w: w.k.get("text") in ("HOME", "BUTTONS", "MOTION") and cmd(w))
assert len(tabs) == 3
for t in tabs: cmd(t)()
# editor: open the "A" picker, choose "Enter" and check it is saved in the edited profile/mode
a_btn = find(lambda w: cmd(w) and getattr(cmd(w), "__defaults__", None) == ("A",))
assert len(a_btn) == 1, "the A binding button was not found"
n0 = len(ALL)
cmd(a_btn[0])()
assert not [w for w in ALL[n0:] if w.k.get("text") == "Enter"], "keys must not be visible until the KEYBOARD type is chosen"
cats = [w.k.get("text") for w in ALL[n0:] if w.k.get("text") in ("GAMEPAD", "KEYBOARD", "MOUSE", "PROGRAM")]
assert cats == ["GAMEPAD", "KEYBOARD", "MOUSE", "PROGRAM"], cats
n0 = len(ALL)
cmd([w for w in ALL if w.k.get("text") == "KEYBOARD" and cmd(w)][-1])()
intro = [w for w in ALL[n0:] if w.k.get("text") == "Enter"]
assert len(intro) == 1, "the picker does not offer 'Enter'"
assert any(w.k.get("text") == "Q" for w in ALL[n0:]) and any(w.k.get("text") == "F12" for w in ALL[n0:]), "letters or F1-F12 are missing"
cmd(intro[0])()
assert "juego" not in svc.cfg["profiles"], "a change must NOT be saved until APPLY: %r" % svc.cfg["profiles"]
assert svc.bindings_view("vertical", "juego")["inputs"][1]["value"] == "pad:A", "...nor applied"
n0 = len(ALL)
cmd([w for w in ALL if cmd(w) and getattr(cmd(w), "__defaults__", None) == ("B",)][-1])()
cmd([w for w in ALL if w.k.get("text") == "KEYBOARD" and cmd(w)][-1])()
cmd([w for w in ALL[n0:] if w.k.get("text") == "Space"][-1])()           # a second change before applying
assert "juego" not in svc.cfg["profiles"]
cmd([w for w in ALL if w.k.get("text") == "APPLY" and cmd(w)][-1])()
assert svc.cfg["profiles"]["juego"]["vertical"]["A"] == "key:ENTER", svc.cfg["profiles"]
assert svc.cfg["profiles"]["juego"]["vertical"]["B"] == "key:SPACE", svc.cfg["profiles"]
print("WimotionControlDeck: button editor OK (several accumulated changes, saved together with APPLY)")
# DISCARD throws away the pending changes
cmd([w for w in ALL if cmd(w) and getattr(cmd(w), "__defaults__", None) == ("Two",)][-1])()
cmd([w for w in ALL if w.k.get("text") == "KEYBOARD" and cmd(w)][-1])()
cmd([w for w in ALL if w.k.get("text") == "Tab" and cmd(w)][-1])()
cmd([w for w in ALL if w.k.get("text") == "DISCARD" and cmd(w)][-1])()
cmd([w for w in ALL if w.k.get("text") == "APPLY" and cmd(w)][-1])()
assert "Two" not in svc.cfg["profiles"]["juego"]["vertical"], svc.cfg["profiles"]["juego"]
print("WimotionControlDeck: DISCARD OK")
# the pointer and Nunchuk stick pickers use their own options
n0 = len(ALL)
cmd(find(lambda w: cmd(w) and getattr(cmd(w), "__defaults__", None) == ("Pointer",))[0])()
opts = {w.k.get("text") for w in ALL[n0:] if w.k.get("text")}
assert "Disabled" in opts and "Moves the mouse" in opts and "Enter" not in opts, opts
cmd(find(lambda w: w.k.get("text") == "Disabled")[-1])()
assert "Pointer" not in svc.cfg["profiles"]["juego"]["vertical"], "pending until APPLY"
cmd([w for w in ALL if w.k.get("text") == "APPLY" and cmd(w)][-1])()
assert svc.cfg["profiles"]["juego"]["vertical"]["Pointer"] == "none"
# the Nunchuk shake can be assigned
assert find(lambda w: cmd(w) and getattr(cmd(w), "__defaults__", None) == ("NunShake",)), "Nunchuk shake is missing from the editor"
# IR pointer switch and restart button in the header
ir = find(lambda w: cmd(w) and w.k.get("width") == 14 and w.k.get("height") == 2 and str(w.k.get("text", "")).startswith(("", "IR POINTER")) and "RESTART" not in str(w.k.get("text")) and "SURE" not in str(w.k.get("text")))
assert ir, "the IR pointer button is missing"
cmd(ir[0])(); assert svc.cfg["ir_enabled"] is False
cmd(ir[0])(); assert svc.cfg["ir_enabled"] is True
assert find(lambda w: w.k.get("text") == "RESTART\nALL" and cmd(w)), "the restart button is missing"
print("WimotionControlDeck: IR switch OK")
# editing ANOTHER mode does not change the active mode
cmd(find(lambda w: w.k.get("text") == "Horizontal" and cmd(w))[0])()
assert svc.ctrl.mode == "vertical"
# master switch
m = find(lambda w: cmd(w) and w.k.get("width") == 18 and w.k.get("height") == 2)
assert m, "the master switch was not found"
cmd(m[0]())  if False else cmd(m[0])()
assert svc.cfg["enabled"] is False
cmd(m[0])()
assert svc.cfg["enabled"] is True
print("WimotionControlDeck: master switch OK")

# ---- WimotionControlDeck 0.3: custom profiles, "+" slots and shake
ROOT = [w for w in ALL if isinstance(w, FakeRoot)][-1]
def tick():
    assert ROOT.cb, "the window stopped refreshing"
    ROOT.cb.pop(0)()
def click(text):
    ws = [w for w in ALL if w.k.get("text") == text and cmd(w)]
    assert ws, "no button %r" % text
    cmd(ws[-1])()
def labels_now(n0):
    return [w.k.get("text") for w in ALL[n0:] if w.k.get("text")]

tick()
assert any(w.k.get("text") == "+ Add profile" for w in ALL), "'+ Add profile' is missing"
click("+ Add profile")
for ch in "my":
    click(ch)
click("SPACE")
for ch in "zelda":
    click(ch)
click("CREATE PROFILE")
assert list(svc.cfg["custom_profiles"].values()) == ["my zelda"], svc.cfg["custom_profiles"]
pid = list(svc.cfg["custom_profiles"])[0]
for m in dc.MODES:
    assert dc.effective_bindings(svc.cfg, pid, m) == dc.effective_bindings(svc.cfg, "juego", m), "the new profile must be a copy of the one being edited (Games)"
assert dc.effective_bindings(svc.cfg, pid, "vertical")["A"] == "key:ENTER", "...including the changes already applied"
print("WimotionControlDeck: '+ Add profile' with on-screen keyboard OK (copy of the profile being edited)")
tick()
assert any(w.k.get("text") == "MY ZELDA" for w in ALL), "the new profile does not show up in Home"
click("MY ZELDA")
assert svc.ctrl.profile == pid
click("Vertical")          # the editor stayed on Horizontal further up
# "+" slots: A, then B, X, Y (maximum 4)
cmd([w for w in ALL if cmd(w) and getattr(cmd(w), "__defaults__", None) == ("A",)][-1])()
click("GAMEPAD")
click("B")
n0 = len(ALL); labs = labels_now(n0)
click("+  add"); click("X")
click("+  add"); click("Y")
click("+  add"); click("L1")
n0 = len(ALL)
cmd([w for w in ALL if cmd(w) and getattr(cmd(w), "__defaults__", None) == ("A",)][-1])()
assert "+  add" not in labels_now(n0), "with 4 buttons it must not offer another slot"
click("Remove this")
assert svc.cfg["profiles"][pid]["vertical"]["A"] == "key:ENTER", "nothing is saved until APPLY (the copy remains)"
click("APPLY")
assert svc.cfg["profiles"][pid]["vertical"]["A"] == "pad:X+pad:Y+pad:TL", svc.cfg["profiles"][pid]   # the 1st slot (B) was removed
print("WimotionControlDeck: '+' slots (A + B + ... up to 4) and 'Remove this' OK")
# shake: 4 assignable directions
cmd([w for w in ALL if cmd(w) and getattr(cmd(w), "__defaults__", None) == ("ShakeUp",)][-1])()
click("KEYBOARD"); click("Esc"); click("APPLY"); assert svc.cfg["profiles"][pid]["vertical"]["ShakeUp"] == "key:ESC"
labs_inputs = [i["input"] for i in svc.bindings_view("vertical", pid)["inputs"]]
assert all(k in labs_inputs for k in dc.SHAKE_INPUTS)
# the two factory profiles cannot be deleted but a custom one can (with confirmation)
tick()
click("Delete profile"); assert pid in svc.cfg["custom_profiles"], "it must ask for confirmation"
click("SURE? AGAIN"); assert pid in svc.cfg["custom_profiles"], "and a second one (double confirmation)"
click("LAST TIME: DELETE"); assert pid not in svc.cfg["custom_profiles"] and svc.ctrl.profile == "menus"
# restart-all and restore also ask for confirmation; if time passes it is cancelled
n_restart = []
svc.restart = lambda: n_restart.append(1)
click("RESTART\nALL"); time.sleep(0.05); assert not n_restart, "the first tap only asks for confirmation"
click("SURE?\nAGAIN"); time.sleep(0.1); assert n_restart == [1], "the second one restarts"
click("Restore this mode")
assert [w for w in ALL if w.k.get("text") == "SURE? AGAIN" and cmd(w)], "Restore asks for confirmation before doing anything"
print("WimotionControlDeck: shake x4 and delete profile (with confirmation) OK")
# motion tab: DSU port
def port_btn(txt):
    return [w for w in ALL if w.k.get("text") == txt and cmd(w) and w.k.get("width") == 3][-1]
cmd(port_btn("-"))()
assert svc.cfg["dsu_port"] == dc.DEFAULT_CONFIG["dsu_port"] - 1
cmd(port_btn("+"))()
assert svc.cfg["dsu_port"] == dc.DEFAULT_CONFIG["dsu_port"]
tick()
assert not any("ERROR" in l for l in svc.log.tail), svc.log.tail
