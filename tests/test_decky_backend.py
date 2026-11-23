"""Decky plugin backend with a fake 'decky' module: startup, API, full shutdown, restart and QAM."""
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
dc.LOCK_PATH = os.path.join(home, "wimotioncontroldeck.lock")
sys.path.insert(0, os.path.join(ROOT, "decky", "WimotionControlDeck"))
import main as plugin_main

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  ok   ", name)
    else: FAIL += 1; print("  FAIL ", name, extra)

loop = asyncio.new_event_loop()
def run(c): return loop.run_until_complete(c)

# the real virtual devices do not exist here: fakes are used
orig = dc.DeckService.__init__
dc.DeckService.__init__ = lambda self, *a, **k: orig(self, FakeUInput(), FakeUInput(), FakeUInput(), use_lock=True)

p = plugin_main.Plugin()
run(p._main())
check("the plugin starts", p.svc is not None and p.svc.started, p.error)
st = run(p.get_status())
check("get_status: running and serializable", st["running"] and st["active"] and json.dumps(st))
check("the config is stored in the Decky user folder", dc.CONFIG_DIR.startswith(home))
check("ir_enabled travels in the status", st["ir_enabled"] is True and "profiles" in st)
run(p.set_mode("horizontal")); check("set_mode", run(p.get_status())["mode"] == "horizontal")
run(p.set_profile("juego")); check("set_profile", run(p.get_status())["profile"] == "juego")
check("set_binding valid", run(p.set_binding("A", "pad:Y", "vertical", "juego")) is True)
check("set_binding invalid", run(p.set_binding("A", "pad:NOPE", "vertical", "juego")) is False)
run(p.reset_bindings("vertical", "juego"))
bv = run(p.get_bindings("vertical", "juego"))
check("reset_bindings", {i["input"]: i["value"] for i in bv["inputs"]}["A"] == "pad:A")
check("set_option (gyro sensitivity)", run(p.set_option("gyro_stick_gain", 2.0)) and run(p.get_status())["gyro_stick_gain"] == 2.0)
check("set_option rejects internal keys", run(p.set_option("profiles", {})) is False)
check("calibrate does not fail", run(p.calibrate()) is True)

print("IR, profiles and batch changes")
check("IR pointer switch", run(p.set_option("ir_enabled", False)) and run(p.get_status())["ir_enabled"] is False)
run(p.set_option("ir_enabled", True))
pid = run(p.create_profile("Zelda"))
st = run(p.get_status())
check("create a profile (blank) and list it", pid and any(x["id"] == pid and x["title"] == "Zelda" and x["custom"] for x in st["profiles"]))
check("empty name rejected", run(p.create_profile("  ")) is None)
ch = [["juego", "vertical", "A", "pad:Y"], ["juego", "vertical", "B", "key:ESC"], [pid, "horizontal", "Plus", "pad:A+pad:B"]]
check("apply_bindings applies the accumulated changes", run(p.apply_bindings(ch)) is True)
b1 = {i["input"]: i["value"] for i in run(p.get_bindings("vertical", "juego"))["inputs"]}
b2 = {i["input"]: i["value"] for i in run(p.get_bindings("horizontal", pid))["inputs"]}
check("...and they show up in the editor", b1["A"] == "pad:Y" and b1["B"] == "key:ESC" and b2["Plus"] == "pad:A+pad:B", (b1["A"], b2["Plus"]))
check("apply_bindings is all or nothing", run(p.apply_bindings([["juego", "vertical", "A", "pad:X"], ["juego", "vertical", "B", "pad:NOPE"]])) is False
      and {i["input"]: i["value"] for i in run(p.get_bindings("vertical", "juego"))["inputs"]}["A"] == "pad:Y")
check("delete a custom profile", run(p.delete_profile(pid)) is True and not any(x["id"] == pid for x in run(p.get_status())["profiles"]))
check("factory profiles cannot be deleted", run(p.delete_profile("menus")) is False)

print("... menu (QAM)")
EMITTED.clear()
p.svc.ctrl.on_open_qam()           # what Home + Plus held does (from the controller thread)
run(asyncio.sleep(0.05))
check("Home + Plus asks the UI to open the ... menu", EMITTED == ["open_qam"], EMITTED)
check("the callback survives a service restart", (run(p.restart()) or True) and p.svc.ctrl.on_open_qam is not None)


print("notifications and quick access (plugin)")
EMITTED.clear()
run(p.set_mode("nunchuk")); run(asyncio.sleep(0.05))
check("changing mode emits 'notify'", "notify" in EMITTED, EMITTED)
check("the plugin hooks the notification up to the service", p.svc.on_notify is not None and p.svc.ctrl.on_notify is not None)
check("set_quick_profiles", run(p.set_quick_profiles(["juego"])) is True and run(p.get_status())["quick_profiles"] == ["juego"])

print("profile copy (plugin)")
run(p.set_binding("A", "key:ENTER", "vertical", "juego"))
cid = run(p.create_profile("Copy plugin", "juego"))
check("create_profile(name, copy_from) copies the profile", dc.effective_bindings(p.svc.cfg, cid, "vertical")["A"] == "key:ENTER")
bid = run(p.create_profile("Blank plugin"))
check("without copy_from it stays blank", dc.effective_bindings(p.svc.cfg, bid, "vertical")["A"] == "none")
view = run(p.get_bindings("vertical", cid))
check("the plugin editor receives types and actions with their type", view["categories"] == ["Gamepad", "Keyboard", "Mouse", "Program"] and all("cat" in x for x in view["actions"]))
check("status includes the acceleration peak", "peak" in run(p.get_status())["motion"])
run(p.set_binding("A", "pad:Y", "vertical", "juego"))      # leaves the profile as the following tests expect it

print("synthetic shake (plugin)")
check("eden_shake triggers the pulse", run(p.eden_shake("left")) is True and p.svc.ctrl._eden_pulse is not None)
check("continuous test from the plugin", run(p.eden_shake("up", 5)) is True and p.svc.ctrl._eden_pulse[2] == 5.0)
check("the status lists the extra DSU ports", isinstance(run(p.get_status())["dsu_ports"], dict))
r_ = run(p.free_dsu_port(26999))
check("free_dsu_port from the plugin (port with no owner)", r_[0] is False and "Nobody" in r_[1], r_)
check("bad direction -> False", run(p.eden_shake("xx")) is False)
check("set_option for the strength", run(p.set_option("eden_shake_amp", 7.0)) is True and run(p.get_status())["eden_shake_amp"] == 7.0)
check("set_option for the notifications", run(p.set_option("notify_enabled", False)) is True and run(p.get_status())["notify_enabled"] is False)
run(p.set_option("notify_enabled", True)); run(p.set_option("eden_shake_amp", 5.0))

print("full shutdown and restart")
run(p.set_profile("juego")); run(p.set_option("px_per_deg", 77))
before = json.dumps(json.load(open(dc.CONFIG_PATH))["profiles"], sort_keys=True)
check("there are saved profiles before shutting down", "juego" in before)
pad_dev = p.svc.ctrl.pad
check("disabling returns False (off)", run(p.set_enabled(False)) is False)
check("...the service is really stopped and the virtual gamepad closed", p.svc.started is False and pad_dev.opened is False)
st = run(p.get_status())
check("...and the status says so (no error)", st["running"] is False and st["active"] is False and not st["error"], st)
check("...the DSU and the lock are released", p.svc.dsu.sock is None and p.svc._lock_fd is None)
cfg = json.load(open(dc.CONFIG_PATH))
check("...it remembers it is off and keeps EVERYTHING", cfg["enabled"] is False and json.dumps(cfg["profiles"], sort_keys=True) == before and cfg["px_per_deg"] == 77 and cfg["profile"] == "juego")
check("while off the API does not break", run(p.set_profile("menus")) is False and run(p.get_bindings()) is None and run(p.set_option("px_per_deg", 5)) is False)
# another instance can take the lock now that it is off
other = dc.DeckService(FakeUInput(), FakeUInput(), FakeUInput(), use_lock=True); other.start(); other.stop()
check("off: another instance (the AppImage) can start", True)
check("enabling again starts it", run(p.set_enabled(True)) is True and p.svc.started)
st = run(p.get_status())
check("...the virtual gamepad opens again", p.svc.ctrl.pad.opened is True)
check("...with the previous profiles and settings", st["profile"] == "juego" and st["px_per_deg"] == 77 and dc.effective_bindings(p.svc.cfg, "juego", "vertical")["A"] == "pad:Y")
check("...and enabled is True again on disk", json.load(open(dc.CONFIG_PATH))["enabled"] is True)
t0 = p.svc.mgr
check("restart: new remotes and state preserved", run(p.restart()) is True and p.svc.mgr is not t0 and run(p.get_status())["px_per_deg"] == 77)
run(p.set_enabled(False)); p3 = plugin_main.Plugin(); run(p3._main())
check("reloading the plugin while off keeps it off", p3.svc.started is False and run(p3.get_status())["running"] is False)
run(p3.set_enabled(True)); check("...and it starts up from scratch", p3.svc.started)

print("second instance")
p2 = plugin_main.Plugin(); run(p2._main())
check("second instance rejected with a message", p2.svc.started is False and "already running" in p2.error, p2.error)
st2 = run(p2.get_status())
check("...and get_status reports it without breaking", st2["running"] is False and st2["error"])
check("...and it can be retried once released", (run(p3._unload()) or True) and run(p2.restart()) is True)
run(p2._unload())
check("_unload stops the service", p2.svc.started is False and p3.svc.started is False)

print("\n%d passed, %d failed" % (PASS, FAIL)); sys.exit(1 if FAIL else 0)
