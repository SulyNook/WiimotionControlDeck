"""End to end: fake sysfs + pty as the remote + Manager + DeckController + fake uinput."""
import os, sys, time, tty, threading, tempfile, select, math
from helpers import *
import deckcore as wd
wd.CONFIG_PATH = "/nonexistent/config.json"

root = tempfile.mkdtemp()
devs = os.path.join(root, "sys/devices/pci0000:00/usb1/1-2/1-2:1.0/0003:057E:0306.0001")
os.makedirs(devs); open(os.path.join(devs, "uevent"), "w").write("HID_ID=0003:0000057E:00000306\n")
cls = os.path.join(root, "sys/class/hidraw/hidraw0"); os.makedirs(cls); os.symlink(devs, os.path.join(cls, "device"))
master, slave = os.openpty(); tty.setraw(slave); tty.setraw(master)
devdir = os.path.join(root, "dev"); os.makedirs(devdir); os.symlink(os.ttyname(slave), os.path.join(devdir, "hidraw0"))
wl.SYS, wl.DEVDIR = os.path.join(root, "sys"), devdir

SIZES = {0x11: 2, 0x12: 3, 0x13: 2, 0x15: 2, 0x16: 22, 0x17: 7, 0x1A: 2}
stop = False
phase = {"i": 0}
def fake():
    buf = b""; streaming = False; i = 0; last = 0
    while not stop:
        r, _, _ = select.select([master], [], [], 0.003)
        if r: buf += os.read(master, 256)
        while buf and SIZES.get(buf[0]) and len(buf) >= SIZES[buf[0]]:
            n = SIZES[buf[0]]; msg, buf = buf[:n], buf[n:]
            if msg[0] == 0x15: os.write(master, bytes([0x20, 0, 0, 0x10, 0, 0, 0xC8]))
            elif msg[0] == 0x17: os.write(master, bytes([0x21, 0, 0, 0x90, 0x00, 0x16, 128, 127, 127, 0, 153, 151, 152, 0, 0, 0xAA]))
            elif msg[0] == 0x12: streaming = True
        if streaming and time.time() - last >= 0.006:
            last = time.time(); i += 1
            # the remote turns right 3 degrees/s... the dots shift left; A pressed between i=400 and 500
            shift = round(i * 0.1)
            btn = wl.BTN_A if 400 < i < 500 else 0
            os.write(master, make_report(buttons=btn, dots=[(432 - shift, 384), (592 - shift, 384)]))
th = threading.Thread(target=fake, daemon=True); th.start()

cfg = wd.load_config(); wd.save_config = lambda c: None
log = wl.EventLog(tempfile.mkdtemp(), "e2e")
pad, mouse = FakeUInput(), FakeUInput()
ctrl = wd.DeckController(cfg, log, pad, mouse, FakeUInput()); ctrl.open_devices()
mgr = wl.Manager(log=log, on_frame=ctrl.on_frame, use_mp=False)
mgr.start()
time.sleep(5.0)
mgr.stop(); stop = True
wms = len(ctrl.states)
dx = sum(mouse.where(wd.EV_REL, wd.REL_X)); dy = sum(mouse.where(wd.EV_REL, wd.REL_Y))
print("remotes with state:", wms, " mouse dx=%d dy=%d" % (dx, dy), " clicks:", mouse.where(wd.EV_KEY, 0x110))
print(log.get_tail(6))
ok = wms == 1 and dx > 20 and abs(dy) < 5 and mouse.where(wd.EV_KEY, 0x110)[:2] == [1, 0]
print("E2E", "OK" if ok else "FAIL")
sys.exit(0 if ok else 1)
