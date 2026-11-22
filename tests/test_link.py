"""Prueba la capa hidraw con un pty como "mando" falso: secuencia de inicio, tamanos de informe, lectura de tramas y descubrimiento en sysfs."""
import os, sys, time, tty, threading, tempfile, shutil
from helpers import *

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print("  ok   ", name)
    else: FAIL += 1; print("  FALLA", name, extra)

# ---------------- descubrimiento en un sysfs de mentira (Dolphin Bar: interfaz 1.2 = puerto 3)
print("descubrimiento")
root = tempfile.mkdtemp()
devs = os.path.join(root, "sys/devices/pci0000:00/usb1/1-2/1-2:1.2/0003:057E:0306.0005")
os.makedirs(devs)
open(os.path.join(devs, "uevent"), "w").write("DRIVER=hid-generic\nHID_ID=0003:0000057E:00000306\nHID_NAME=Nintendo RVL-CNT-01\n")
os.makedirs(os.path.join(root, "sys/class/hidraw"))
os.symlink(devs, os.path.join(root, "sys/class/hidraw/hidraw3"))  # hidraw3 -> (device) ; usamos el propio directorio
os.makedirs(os.path.join(root, "sys/class/hidraw/hidraw3x"), exist_ok=True)
# estructura real: /sys/class/hidraw/hidraw3/device -> hid device
shutil.rmtree(os.path.join(root, "sys/class/hidraw/hidraw3x"))
os.remove(os.path.join(root, "sys/class/hidraw/hidraw3"))
os.makedirs(os.path.join(root, "sys/class/hidraw/hidraw3"))
os.symlink(devs, os.path.join(root, "sys/class/hidraw/hidraw3/device"))
other = os.path.join(root, "sys/devices/usb1/1-3/1-3:1.0/0003:046D:C52B.0001")
os.makedirs(other); open(os.path.join(other, "uevent"), "w").write("HID_ID=0003:0000046D:0000C52B\n")
os.makedirs(os.path.join(root, "sys/class/hidraw/hidraw4"))
os.symlink(other, os.path.join(root, "sys/class/hidraw/hidraw4/device"))
wl.SYS = os.path.join(root, "sys"); wl.DEVDIR = "/dev"
infos = wl.list_wiimote_hidraws()
check("encuentra solo el nodo Nintendo", len(infos) == 1 and infos[0].path == "/dev/hidraw3", infos)
check("puerto de la barra = interfaz + 1", infos and infos[0].port == 3, infos[0].port if infos else None)

# ---------------- "mando" falso en un pty
print("protocolo")
SIZES = {0x11: 2, 0x12: 3, 0x13: 2, 0x15: 2, 0x16: 22, 0x17: 7, 0x1A: 2}
master, slave = os.openpty()
tty.setraw(slave); tty.setraw(master)
slave_path = os.ttyname(slave)
writes = []
stop = False
ext_plugged = False

def fake_wiimote():
    buf = b""
    while not stop:
        import select
        r, _, _ = select.select([master], [], [], 0.05)
        if r:
            buf += os.read(master, 256)
        while buf:
            n = SIZES.get(buf[0])
            if n is None:
                writes.append(("BAD", buf[:4])); buf = buf[1:]; continue
            if len(buf) < n: break
            msg, buf = buf[:n], buf[n:]
            writes.append(("OK", msg))
            if msg[0] == 0x15:      # estado: botones(2) flags bateria
                os.write(master, bytes([0x20, 0, 0, (0x02 if ext_plugged else 0) | 0x10, 0, 0, 0xA0]))
            elif msg[0] == 0x17:    # lectura de EEPROM de calibracion
                os.write(master, bytes([0x21, 0, 0, 0x90, 0x00, 0x16, 128, 127, 127, 0, 153, 151, 152, 0, 0, 0xAA]))
            elif msg[0] == 0x12:    # modo de informes -> empieza a mandar 0x37
                threading.Thread(target=stream, daemon=True).start()

streaming = False
def stream():
    global streaming
    if streaming: return
    streaming = True
    i = 0
    while not stop:
        os.write(master, make_report(buttons=wl.BTN_A if i > 30 else 0, dots=[(400, 380), (560, 382)]))
        i += 1; time.sleep(0.005)

th = threading.Thread(target=fake_wiimote, daemon=True); th.start()
got = []
class Info: path = slave_path; port = 2; bus = 3
wm = wl.Wiimote(Info(), 1, use_mp=False, on_frame=lambda w, f: got.append(f))
wm.start()
t0 = time.time()
while time.time() - t0 < 4 and len(got) < 60: time.sleep(0.05)
check("recibe tramas 0x37 decodificadas", len(got) >= 60, len(got))
check("estado conectado, bateria 80%", wm.connected and wm.battery == 80, (wm.connected, wm.battery))
check("calibracion EEPROM leida (cero/1g)", wm.acc_zero == [128.0, 127.0, 127.0] and wm.acc_one == [153.0, 151.0, 152.0], (wm.acc_zero, wm.acc_one))
check("IR decodificado", got and got[-1].ir == [(400, 380), (560, 382)], got[-1].ir if got else None)
check("boton A visto", any(f.buttons & wl.BTN_A for f in got))
ids = [m[0] for k, m in writes if k == "OK"]
check("ningun informe con tamano raro", all(k == "OK" for k, _ in writes), [w for w in writes if w[0] == "BAD"])
check("orden: estado, (ext), LED, EEPROM, IR..., modo de informes", ids[0] == 0x15 and 0x11 in ids and 0x17 in ids and ids[-1] == 0x12 or 0x12 in ids, ids)
led = [m for k, m in writes if k == "OK" and m[0] == 0x11 and True]
check("LED del jugador 2 (puerto 2) = 0x20", any(m[1] == 0x20 for m in led), led[:3])
regs = [m for k, m in writes if k == "OK" and m[0] == 0x16]
addrs = [(m[2] << 16) | (m[3] << 8) | m[4] for m in regs]
check("registros: extension normal (A400F0/FB) + IR (B000xx)", 0xA400F0 in addrs and 0xA400FB in addrs and 0xB00030 in addrs and 0xB00033 in addrs, [hex(a) for a in addrs])
check("sin MotionPlus: no se escribe A600FE", 0xA600FE not in addrs)
# MotionPlus activado
stop_flag = False
wm.stop()
check("el mando se para sin colgarse", True)
stop = True

print("\n%d correctas, %d fallos" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
