"""Reliability: the remote never gets stuck rumbling (retry, overlaps, on release, periodic safety) and the service restarts by itself on wake-up."""
import errno, json, os, sys, tempfile, threading, time, types
from helpers import *
import deckcore as dc

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  ok   ", name)
    else: FAIL += 1; print("  FAIL ", name, extra)


class Dev:
    """Fake hidraw: stores every write with its timestamp; can fail when writing "rumble off"."""
    def __init__(self, fail_off=0):
        self.log = []; self.fail_off = fail_off; self.closed = False
    def write(self, data):
        rumble_on = bool(data[0] == 0x11 and data[1] & 1)
        if data[0] == 0x11 and not rumble_on and self.fail_off > 0:
            self.fail_off -= 1
            raise OSError(errno.EAGAIN, "Resource temporarily unavailable")
        self.log.append((time.monotonic(), bytes(data)))
    def close(self): self.closed = True

def last_rumble(dev):
    r = [(t, d) for t, d in dev.log if d[0] == 0x11]
    return r[-1][1][1] & 1 if r else None

info = types.SimpleNamespace(path="/dev/null", port=1)

print("rumble")
w = wl.Wiimote(info, 0); w.dev = Dev(fail_off=3)
w.rumble(0.1)
time.sleep(0.12 + 0.5)
check("if the 'turn off' report fails (EAGAIN) it is retried until it gets through", last_rumble(w.dev) == 0 and w.dev.fail_off == 0, (w.dev.fail_off, w.dev.log[-2:]))
w._stop = True

w = wl.Wiimote(info, 0); w.dev = Dev()
t0 = time.monotonic(); w.rumble(0.1); time.sleep(0.05); w.rumble(0.4)
time.sleep(0.2)
check("a short rumble does not cut off a longer one (the deadline is extended)", last_rumble(w.dev) == 1, w.dev.log[-1])
time.sleep(0.4)
offs = [t - t0 for t, d in w.dev.log if d[0] == 0x11 and not d[1] & 1]
check("...and it turns off at the end of the extended deadline, not before", offs and 0.4 <= offs[0] <= 0.7 and last_rumble(w.dev) == 0, offs)
w._stop = True

w = wl.Wiimote(info, 0); dev = w.dev = Dev()
w._led = 0b0011
w.stop()
check("on releasing the remote, 'rumble and LEDs off' is sent and it closes", dev.closed and dev.log[-1][1] == bytes([0x11, 0x00]), dev.log[-1:])

# periodic safety: even if everything were lost, the supervisor sends "rumble off" again
w = wl.Wiimote(info, 0); w.dev = Dev(); w.initialized = True; w.connected = True
w._led = 0b0001; w.last_rx = time.monotonic()
th = threading.Thread(target=w._supervisor, daemon=True); th.start()
w.dev.log.append((time.monotonic(), bytes([0x11, 0x01])))               # "got stuck rumbling"
end = time.monotonic() + 2.4
while time.monotonic() < end:
    w.last_rx = time.monotonic(); time.sleep(0.05)
w._stop = True; th.join(1.0)
check("the supervisor resends 'no rumble' every ~1.5 s while connected", last_rumble(w.dev) == 0 and any(d == bytes([0x11, 0x10]) for _, d in w.dev.log), w.dev.log[-3:])

print("service: full shutdown and wake from suspend")
home = tempfile.mkdtemp(); dc.configure_paths(home); dc.LOCK_PATH = os.path.join(home, "lock")
dc.save_config(dict(dc.load_config(), profile="juego", px_per_deg=61))
svc = dc.DeckService(FakeUInput(), FakeUInput(), FakeUInput(), use_lock=True)
svc.start()
check("starts", svc.started and svc.cfg["px_per_deg"] == 61)
pad = svc.ctrl.pad
svc.ctrl.set_binding("A", "pad:Y", "vertical", "juego")
m0 = svc.mgr
svc.restart()
check("restart(): new remotes and controller, config recovered from disk", svc.started and svc.mgr is not m0 and svc.cfg["px_per_deg"] == 61
      and dc.effective_bindings(svc.cfg, "juego", "vertical")["A"] == "pad:Y")
check("restart() keeps the lock (nobody sneaks in between)", svc._lock_fd is not None)
svc.stop()
check("stop(): everything closed, lock released, idempotent", not svc.started and pad.opened is False and svc._lock_fd is None and (svc.stop() or True))

# wake from suspend: CLOCK_BOOTTIME advances and CLOCK_MONOTONIC does not
gap = {"v": 0.0}
dc.DeckService._boot_gap = staticmethod(lambda: gap["v"])
dc.DeckService.WATCH_PERIOD = 0.1
svc = dc.DeckService(FakeUInput(), FakeUInput(), FakeUInput(), use_lock=True); svc.start()
m0 = svc.mgr; time.sleep(0.35)
check("without suspend it does not restart", svc.mgr is m0)
gap["v"] = 1.0; time.sleep(0.3)
check("a small jump (1 s) is not a suspend", svc.mgr is m0)
gap["v"] = 400.0
for _ in range(40):
    if svc.mgr is not m0 and svc.started:
        break
    time.sleep(0.1)
check("on waking after ~7 min of suspend EVERYTHING restarts by itself", svc.mgr is not m0 and svc.started)
m1 = svc.mgr
gap["v"] = 900.0                                   # another suspend: the restarted service's watchdog must act too
for _ in range(40):
    if svc.mgr is not m1 and svc.started:
        break
    time.sleep(0.1)
check("...and the restarted service's watchdog stays active (a 2nd suspend too)", svc.mgr is not m1 and svc.started)
m2 = svc.mgr
svc.stop()
gap["v"] = 5000.0
time.sleep(0.6)
check("after stop() the watchdog no longer restarts anything", not svc.started and svc.mgr is m2)

print("\n%d passed, %d failed" % (PASS, FAIL)); sys.exit(1 if FAIL else 0)
