#!/usr/bin/env python3
"""
wiilink - acceso hidraw y protocolo del Wii Remote (Plus) en Linux, con la Dolphin Bar en modo 4
(o con un mando Bluetooth que aparezca como hidraw). Solo libreria estandar de Python 3.

Incluye: deteccion de mandos, lectura/escritura de informes (con los tamanos EXACTOS que acepta la barra),
decodificacion del informe 0x37 (botones + acelerometro + IR basico + extension de 6 bytes),
puntero IR angular, filtro "1 euro", detector de sacudidas y registro (eventos + CSV).

  python3 wiilink.py --list      mandos / puertos hidraw encontrados
  python3 wiilink.py --diag      vuelca lo que llega de cada mando (Ctrl+C para salir)
"""
import errno
import glob
import json
import math
import os
import re
import select
import sys
import threading
import time

SYS = os.environ.get("WIILINK_SYSFS", "/sys")
DEVDIR = os.environ.get("WIILINK_DEVDIR", "/dev")
VID = 0x057E
PIDS = (0x0306, 0x0330)

BTN_LEFT, BTN_RIGHT, BTN_DOWN, BTN_UP, BTN_PLUS = 0x0001, 0x0002, 0x0004, 0x0008, 0x0010
BTN_TWO, BTN_ONE, BTN_B, BTN_A, BTN_MINUS, BTN_HOME = 0x0100, 0x0200, 0x0400, 0x0800, 0x1000, 0x8000
BUTTON_NAMES = {BTN_LEFT: "Left", BTN_RIGHT: "Right", BTN_DOWN: "Down", BTN_UP: "Up", BTN_PLUS: "Plus",
                BTN_TWO: "Two", BTN_ONE: "One", BTN_B: "B", BTN_A: "A", BTN_MINUS: "Minus", BTN_HOME: "Home"}
NAME_TO_BTN = {v: k for k, v in BUTTON_NAMES.items()}

IR_FOCAL_PX = 1369.0   # ~41 grados de campo horizontal sobre 1024 px
DEG = math.pi / 180.0


# ------------------------------------------------------------------ utilidades
def read_text(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def hexs(b):
    return "".join("%02X" % x for x in b)


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def wrap_angle(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def norm_line_angle(a):
    """Angulo de una recta (sin sentido) en (-90, 90] grados, en radianes."""
    if a > math.pi / 2:
        a -= math.pi
    if a < -math.pi / 2:
        a += math.pi
    return a


class EventLog:
    """Registro de eventos (texto) y de muestras (CSV). Seguro entre hilos."""

    def __init__(self, directory, prefix, csv_header=None):
        self.t0 = time.monotonic()
        self.lock = threading.Lock()
        self.tail = []
        self.events = None
        self.csv = None
        self.events_path = self.csv_path = None
        try:
            os.makedirs(directory, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            self.events_path = os.path.join(directory, "%s_eventos_%s.log" % (prefix, stamp))
            self.events = open(self.events_path, "w", encoding="utf-8")
            if csv_header:
                self.csv_path = os.path.join(directory, "%s_muestras_%s.csv" % (prefix, stamp))
                self.csv = open(self.csv_path, "w", encoding="utf-8")
                self.csv.write(csv_header + "\n")
        except OSError:
            self.events = self.csv = None

    def now(self):
        return time.monotonic() - self.t0

    def event(self, who, category, message):
        line = "[%9.3f] %-4s %-8s %s" % (self.now(), who, category, message)
        with self.lock:
            self.tail.append(line)
            if len(self.tail) > 12:
                self.tail.pop(0)
            if self.events:
                try:
                    self.events.write(line + "\n")
                    self.events.flush()
                except OSError:
                    pass

    def note(self, text):
        text = text.replace("\n", " ").replace("\r", " ").strip()
        if not text:
            return
        self.event("APP", "NOTA", text)
        if self.csv:
            with self.lock:
                try:
                    self.csv.write("#NOTA,%.3f,%s\n" % (self.now(), text))
                except OSError:
                    pass

    def sample(self, line):
        if self.csv:
            with self.lock:
                try:
                    self.csv.write(line + "\n")
                except OSError:
                    pass

    def get_tail(self, n=8):
        with self.lock:
            return "\n".join(self.tail[-n:])

    def close(self):
        for f in (self.events, self.csv):
            try:
                if f:
                    f.close()
            except OSError:
                pass


# ------------------------------------------------------------------ filtros y detectores
class OneEuro:
    """Filtro '1 euro': quita el temblor en reposo sin retrasar los movimientos rapidos."""

    def __init__(self, min_cut=1.0, beta=1.5, d_cut=1.0):
        self.min_cut, self.beta, self.d_cut = min_cut, beta, d_cut
        self.x = None
        self.dx = 0.0

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self):
        self.x = None
        self.dx = 0.0

    def filter(self, x, dt):
        if self.x is None:
            self.x = x
            self.dx = 0.0
            return x
        dt = max(dt, 0.001)
        d = (x - self.x) / dt
        self.dx += self._alpha(self.d_cut, dt) * (d - self.dx)
        cutoff = self.min_cut + self.beta * abs(self.dx)
        self.x += self._alpha(cutoff, dt) * (x - self.x)
        return self.x


class IRPointer:
    """
    Puntero angular a partir de los puntos IR de la barra (modo basico, hasta 4 puntos, 1024x768).
    Devuelve los angulos (rad) a los que apunta el eje de la camara respecto al centro de la barra, con el
    balanceo corregido: no depende de la distancia (como el puntero real de la Wii). Si solo se ve un LED
    se deduce el centro con la ultima separacion e inclinacion (hasta 1,5 s).
    El eje y crudo de la camara crece hacia ARRIBA (comprobado con la Dolphin Bar).
    """

    def __init__(self, bar_width=0.20):
        self.bar_width = bar_width
        self.last_sep = 0.0
        self.last_cx = self.last_cy = 0.0
        self.last_alpha = 0.0
        self.last_pair_t = -9.0

    def update(self, dots, now):
        """dots: lista de (x, y) validos. Devuelve dict o None."""
        best = 0.0
        pair = None
        for i in range(len(dots)):
            for j in range(i + 1, len(dots)):
                dx = dots[i][0] - dots[j][0]
                dy = dots[i][1] - dots[j][1]
                d = math.hypot(dx, dy)
                if d > best:
                    best = d
                    pair = (dots[i], dots[j])
        n = len(dots)
        if pair is not None and best >= 12:
            cx = (pair[0][0] + pair[1][0]) / 2.0
            cy = (pair[0][1] + pair[1][1]) / 2.0
            ddx = pair[1][0] - pair[0][0]
            ddy = pair[1][1] - pair[0][1]
            self.last_sep, self.last_cx, self.last_cy = best, cx, cy
            self.last_alpha = math.atan2(ddy, ddx)
            self.last_pair_t = now
            single = False
        elif n == 1 and now - self.last_pair_t < 1.5 and self.last_sep >= 20:
            hx = math.cos(self.last_alpha) * self.last_sep / 2
            hy = math.sin(self.last_alpha) * self.last_sep / 2
            x, y = dots[0]
            c1 = (x + hx, y + hy)
            c2 = (x - hx, y - hy)
            d1 = math.hypot(c1[0] - self.last_cx, c1[1] - self.last_cy)
            d2 = math.hypot(c2[0] - self.last_cx, c2[1] - self.last_cy)
            cx, cy = c1 if d1 <= d2 else c2
            best = self.last_sep
            ddx, ddy = math.cos(self.last_alpha) * best, math.sin(self.last_alpha) * best
            self.last_cx, self.last_cy = cx, cy
            single = True
        else:
            return None

        u = (cx - 512.0) / IR_FOCAL_PX      # derecha positivo
        v = (cy - 384.0) / IR_FOCAL_PX      # arriba positivo
        dist = self.bar_width * IR_FOCAL_PX / best
        if dist < 0.3 or dist > 8.0:
            return None
        alpha = norm_line_angle(math.atan2(ddy, ddx))
        wx, wz = -u, -v
        ca, sa = math.cos(alpha), math.sin(alpha)
        ex = math.atan(wx * ca + wz * sa)
        ez = math.atan(-wx * sa + wz * ca)
        return {"ex": ex, "ez": ez, "u": u, "v": v, "dist": dist, "sep": best, "alpha": alpha,
                "cx": cx, "cy": cy, "n": n, "single": single}


class ShakeDetector:
    """
    Detecta sacudidas del mando con el acelerometro (sin giroscopio): inversiones de signo repetidas de la
    aceleracion dinamica (acel - media lenta) en un eje.
      threshold: amplitud minima en g; reversals: inversiones necesarias; window: segundos
    Al completarse una sacudida deja en fired_axis (0, 1, 2) el eje dominante y en fired_sign (+1/-1) el sentido del
    PRIMER golpe (la aceleracion con la que arranca el gesto: hacia donde "lanzas" el mando).
    """

    def __init__(self, threshold=1.0, reversals=4, window=0.8, cooldown=1.0, gap=0.4):
        self.threshold, self.reversals, self.window, self.cooldown = threshold, reversals, window, cooldown
        self.gap = gap        # segundos maximos entre dos cambios de sentido seguidos
        self.lp = None
        self.last_t = None
        self.sign = [0, 0, 0]
        self.last_rev = [-9.0] * 3
        self.count = [0] * 3
        self.cool_until = -1.0
        self.activity_until = -1.0   # "hay movimiento brusco": el puntero se congela
        self.peak = 0.0
        self.first_sign = [0, 0, 0]
        self.amp = [0.0, 0.0, 0.0]
        self.fired_axis = None
        self.fired_sign = 0

    def update(self, t, acc):
        """acc: (x, y, z) en g. Devuelve True cuando se completa una sacudida."""
        if self.lp is None:
            self.lp = list(acc)
            self.last_t = t
            return False
        dt = clamp(t - self.last_t, 0.001, 0.1)
        self.last_t = t
        a = 1.0 - math.exp(-dt / (0.3 * max(1.0, self.gap / 0.4)))   # agitado lento: media mas lenta
        dyn = [acc[i] - self.lp[i] for i in range(3)]
        for i in range(3):
            self.lp[i] += (acc[i] - self.lp[i]) * a
        mag = math.sqrt(dyn[0] ** 2 + dyn[1] ** 2 + dyn[2] ** 2)
        if mag > 0.8:
            self.activity_until = t + 0.15
        fired = False
        for i in range(3):
            v = dyn[i]
            if abs(v) > self.threshold:
                s = 1 if v > 0 else -1
                if s != self.sign[i]:
                    if self.sign[i] != 0 and t - self.last_rev[i] < self.gap:
                        self.count[i] += 1
                    else:
                        self.count[i] = 1
                        self.first_sign[i] = s
                        self.amp[i] = 0.0
                    self.last_rev[i] = t
                    self.sign[i] = s
                self.amp[i] = max(self.amp[i], abs(v))
            if t - self.last_rev[i] > self.gap:
                self.count[i] = 0
                self.sign[i] = 0
        cand = [i for i in range(3) if self.count[i] >= self.reversals]
        if cand and t >= self.cool_until:
            i = max(cand, key=lambda k: self.amp[k])
            self.fired_axis, self.fired_sign = i, self.first_sign[i]
            fired = True
        if fired:
            self.cool_until = t + self.cooldown
            self.count = [0, 0, 0]
            self.sign = [0, 0, 0]
        return fired

    @property
    def moving(self):
        return self.last_t is not None and self.last_t < self.activity_until


# ------------------------------------------------------------------ descubrimiento
class HidInfo:
    def __init__(self, path, port, bus, vid, pid, syspath):
        self.path, self.port, self.bus, self.vid, self.pid, self.syspath = path, port, bus, vid, pid, syspath

    def __repr__(self):
        return "HidInfo(%s port=%s bus=%s %04X:%04X)" % (self.path, self.port, self.bus, self.vid, self.pid)


def list_wiimote_hidraws():
    """Nodos hidraw de mandos Wii: Dolphin Bar (USB, un puerto por interfaz) o mandos Bluetooth."""
    out = []
    for node in sorted(glob.glob(os.path.join(SYS, "class/hidraw/hidraw*")),
                       key=lambda p: int(re.sub(r"\D", "", os.path.basename(p)) or 0)):
        name = os.path.basename(node)
        uev = read_text(node + "/device/uevent") or ""
        m = re.search(r"HID_ID=([0-9A-Fa-f]+):([0-9A-Fa-f]+):([0-9A-Fa-f]+)", uev)
        if not m:
            continue
        bus, vid, pid = int(m.group(1), 16), int(m.group(2), 16), int(m.group(3), 16)
        if vid != VID or pid not in PIDS:
            continue
        real = os.path.realpath(node + "/device")
        pm = re.search(r":1\.(\d+)/", real + "/")
        port = int(pm.group(1)) + 1 if pm else None
        out.append(HidInfo(os.path.join(DEVDIR, name), port, bus, vid, pid, real))
    return out


def access_problems():
    """Lista de problemas de permisos (para ensenar al usuario como arreglarlos)."""
    problems = []
    infos = list_wiimote_hidraws()
    for i in infos:
        if not os.access(i.path, os.R_OK | os.W_OK):
            problems.append("sin permiso de lectura/escritura en %s" % i.path)
    return problems


# ------------------------------------------------------------------ dispositivo
class HidrawDevice:
    def __init__(self, path):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

    def read(self, timeout=0.2):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        return os.read(self.fd, 64)

    def write(self, data):
        return os.write(self.fd, bytes(data))

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


class Frame:
    """Informe 0x37 decodificado."""
    __slots__ = ("t", "raw", "buttons", "acc_raw", "ir", "ext", "cls", "is_mp", "mp", "nun", "ext_flag")

    def __init__(self):
        self.mp = None
        self.nun = None
        self.is_mp = False
        self.ext_flag = False


def parse_data_report(d, t=None):
    """Decodifica un informe 0x37 (22 bytes). Devuelve Frame o None."""
    if len(d) < 22 or d[0] != 0x37:
        return None
    f = Frame()
    f.t = time.monotonic() if t is None else t
    f.raw = bytes(d[:22])
    f.buttons = (d[1] & 0x1F) | ((d[2] & 0x9F) << 8)
    f.acc_raw = (((d[3] << 2) | ((d[1] >> 5) & 3)) / 4.0,
                 ((d[4] << 2) | ((d[2] >> 4) & 2)) / 4.0,
                 ((d[5] << 2) | ((d[2] >> 5) & 2)) / 4.0)
    dots = []
    for i in range(2):
        o = 6 + i * 5
        x1 = d[o] | (((d[o + 2] >> 4) & 3) << 8)
        y1 = d[o + 1] | (((d[o + 2] >> 6) & 3) << 8)
        x2 = d[o + 3] | ((d[o + 2] & 3) << 8)
        y2 = d[o + 4] | (((d[o + 2] >> 2) & 3) << 8)
        if not (x1 == 1023 and y1 == 1023):
            dots.append((x1, y1))
        if not (x2 == 1023 and y2 == 1023):
            dots.append((x2, y2))
    f.ir = dots
    f.ext = bytes(d[16:22])
    f.cls = d[21] & 3
    return f


def decode_mp(f):
    """Si el informe es una trama de MotionPlus: (yaw, roll, pitch, slow_yaw, slow_roll, slow_pitch, ext_flag)."""
    d = f.raw
    ext = f.ext
    if all(b == 0 for b in ext) or all(b == 0xFF for b in ext):
        return None
    if f.cls != 2:
        return None
    yaw = d[16] | ((d[19] >> 2) << 8)
    roll = d[17] | ((d[20] >> 2) << 8)
    pitch = d[18] | ((d[21] >> 2) << 8)
    return (yaw, roll, pitch, bool(d[19] & 0x02), bool(d[20] & 0x02), bool(d[19] & 0x01), bool(d[20] & 0x01))


def decode_nunchuk_plain(f):
    """Nunchuk como extension normal (sin MotionPlus). Devuelve dict o None."""
    d = f.raw
    ext = f.ext
    if all(b == 0 for b in ext) or all(b == 0xFF for b in ext):
        return None
    ax = (d[18] << 2) | ((d[21] >> 2) & 3)
    ay = (d[19] << 2) | ((d[21] >> 4) & 3)
    az = (d[20] << 2) | ((d[21] >> 6) & 3)
    return {"sx": d[16], "sy": d[17],
            "acc": ((ax - 512.0) / 200.0, (ay - 512.0) / 200.0, (az - 512.0) / 200.0),
            "z": (d[21] & 1) == 0, "c": (d[21] & 2) == 0}


# ------------------------------------------------------------------ mando
class Wiimote:
    """
    Un Wii Remote en un nodo hidraw. Hilo lector + hilo supervisor (conexion, configuracion, reconexion).
      use_mp          activa el MotionPlus (modo independiente 0x00); si no, el Nunchuk se lee como extension normal
      on_frame(wm,f)  se llama desde el hilo lector con cada informe 0x37
    """

    def __init__(self, info, slot, use_mp=False, log=None, on_frame=None, ir=True):
        self.info, self.slot = info, slot
        self.use_mp = use_mp
        self.log = log
        self.on_frame = on_frame
        self.want_ir = ir
        self.dev = None
        self.initialized = False
        self.connected = False
        self.failed = False
        self.battery = -1
        self.ext_flag = False
        self.status_text = "Iniciando..."
        self.acc_zero = [128.0, 128.0, 128.0]
        self.acc_one = [154.0, 154.0, 154.0]
        self.eep_sig = ""
        self.last_rx = 0.0
        self.rate = 0.0
        self._rate_n = 0
        self._rate_t = time.monotonic()
        self._stop = False
        self._status_evt = threading.Event()
        self._cal_evt = threading.Event()
        self._ext_init_req = False
        self._reinit_req = False
        self._led = 1 << (slot & 3)
        self._rumble_until = 0.0
        self._rumble_thread = None
        self._keepalive_t = 0.0
        self._threads = []
        self.frames_seen = 0

    # ---- registro
    def _log(self, cat, msg):
        if self.log:
            self.log.event("W%d" % (self.slot + 1), cat, msg)

    # ---- E/S
    def start(self):
        self.dev = HidrawDevice(self.info.path)
        self._log("HID", "Abierto %s (puerto %s)" % (self.info.path, self.info.port))
        t1 = threading.Thread(target=self._reader, name="wm-read-%d" % self.slot, daemon=True)
        t2 = threading.Thread(target=self._supervisor, name="wm-sup-%d" % self.slot, daemon=True)
        self._threads = [t1, t2]
        t1.start()
        t2.start()

    def stop(self):
        self._stop = True
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(1.5)
        if self.dev:
            try:
                self.dev.write([0x11, 0x00])          # vibracion y LEDs apagados: que no quede el mando vibrando al soltarlo
            except OSError:
                pass
            self.dev.close()

    def send(self, data):
        """Escribe un informe de salida con su tamano natural (la barra rechaza tamanos distintos)."""
        try:
            self.dev.write(data)
            return True
        except OSError as e:
            if e.errno not in (errno.EIO, errno.EPIPE, errno.ENODEV, errno.EAGAIN, errno.EPROTO, errno.ETIMEDOUT):
                self._log("ERROR", "escritura: %s" % e)
            if e.errno == errno.ENODEV:
                self.failed = True
            return False

    def write_reg(self, address, data):
        r = bytearray(22)
        r[0] = 0x16
        r[1] = 0x04
        r[2] = (address >> 16) & 0xFF
        r[3] = (address >> 8) & 0xFF
        r[4] = address & 0xFF
        r[5] = len(data)
        r[6:6 + len(data)] = bytes(data)
        return self.send(r)

    def set_report_mode(self):
        self.send([0x12, 0x04, 0x37])

    def set_led(self, mask):
        self._led = mask & 0x0F
        self.send([0x11, (self._led << 4) | (1 if time.monotonic() < self._rumble_until else 0)])

    def rumble(self, seconds=0.15):
        self._rumble_until = max(self._rumble_until, time.monotonic() + seconds)
        self.send([0x11, (self._led << 4) | 1])
        t = self._rumble_thread
        if t is None or not t.is_alive():
            self._rumble_thread = threading.Thread(target=self._rumble_off, name="wm-rumble-%d" % self.slot, daemon=True)
            self._rumble_thread.start()

    def _rumble_off(self):
        """Apaga la vibracion al vencer el plazo (que otra vibracion pueda ampliar). Si el informe de apagar se pierde
        (EAGAIN/EIO justo al reconectar) se REINTENTA: antes quedaba el mando vibrando para siempre."""
        while not self._stop:
            wait = self._rumble_until - time.monotonic()
            if wait > 0:
                time.sleep(min(wait, 0.2))
                continue
            for _ in range(10):
                if self.send([0x11, self._led << 4]):
                    return
                time.sleep(0.05)
            return

    def request_reinit(self):
        self._reinit_req = True

    # ---- hilos
    def _reader(self):
        while not self._stop:
            try:
                d = self.dev.read(0.2)
            except OSError as e:
                if e.errno in (errno.ENODEV, errno.EIO):
                    self.failed = True
                    self._log("HID", "Dispositivo desconectado: %s" % e)
                    return
                time.sleep(0.05)
                continue
            if not d:
                continue
            self.last_rx = time.monotonic()
            rid = d[0]
            if rid == 0x37:
                f = parse_data_report(d, self.last_rx)
                if f is not None:
                    self.frames_seen += 1
                    self._rate_n += 1
                    if self.last_rx - self._rate_t >= 1.0:
                        self.rate = self._rate_n / (self.last_rx - self._rate_t)
                        self._rate_n = 0
                        self._rate_t = self.last_rx
                    self.connected = True
                    if self.on_frame and self.initialized:      # mientras se reconfigura (p. ej. MotionPlus si/no) no se entregan tramas
                        try:
                            self.on_frame(self, f)
                        except Exception as ex:  # un error de procesado no debe matar la lectura
                            self._log("ERROR", "on_frame: %r" % ex)
            elif rid == 0x20:
                self._handle_status(d)
            elif rid == 0x21:
                self._handle_read(d)

    def _handle_status(self, d):
        if len(d) < 7:
            return
        ext = bool(d[3] & 0x02)
        self.battery = min(100, d[6] * 100 // 200)
        if ext != self.ext_flag or not self.initialized:
            self._log("STATUS", "extension=%s IR=%s LED=%d bateria=%d%%" % (ext, bool(d[3] & 0x08), d[3] >> 4, self.battery))
        if ext and not self.ext_flag and self.initialized and not self.use_mp:
            self._ext_init_req = True
        self.ext_flag = ext
        self._status_evt.set()
        if self.initialized:
            self.set_report_mode()

    def _handle_read(self, d):
        if len(d) < 16:
            return
        err = d[3] & 0x0F
        addr = (d[4] << 8) | d[5]
        if err == 0 and addr == 0x0016:
            self.eep_sig = hexs(d[6:16])
            for k in range(3):
                zero, one = float(d[6 + k]), float(d[10 + k])
                if one > zero + 20:
                    self.acc_zero[k], self.acc_one[k] = zero, one
        self._cal_evt.set()

    def _supervisor(self):
        while not self._stop and not self.failed:
            try:
                if self._reinit_req:
                    self._reinit_req = False
                    self.initialized = False
                if not self.initialized:
                    self._status_evt.clear()
                    self.send([0x15, 0x00])
                    if self._status_evt.wait(0.8):
                        self.status_text = "Configurando..."
                        self._setup()
                    else:
                        self.status_text = "Esperando mando (pulsa un boton)"
                        self.connected = False
                        time.sleep(0.3)
                else:
                    if self._ext_init_req:
                        self._ext_init_req = False
                        self._init_extension_plain()
                        self.set_report_mode()
                    idle = time.monotonic() - self.last_rx
                    if idle > 3.0:
                        self.initialized = False
                        self.connected = False
                        self.status_text = "Mando desconectado"
                        self._log("CONN", "Sin informes durante 3 s: mando desconectado")
                    else:
                        now = time.monotonic()
                        if now >= self._rumble_until and now - self._keepalive_t > 1.5:
                            self._keepalive_t = now      # seguro: si una vibracion se quedo encendida, esto la apaga
                            self.send([0x11, self._led << 4])
                        time.sleep(0.1)
            except Exception as ex:
                self.status_text = "Error: %s" % ex
                self._log("ERROR", repr(ex))
                time.sleep(1.0)

    def _init_extension_plain(self):
        self.write_reg(0xA400F0, [0x55])
        time.sleep(0.06)
        self.write_reg(0xA400FB, [0x00])
        time.sleep(0.15)
        self._log("INIT", "Extension inicializada como normal (Nunchuk directo)")

    def _setup(self):
        self.initialized = False
        self._log("INIT", "Configurando mando (extension segun estado: %s)" % self.ext_flag)
        if self.ext_flag or not self.use_mp:
            # desactiva un MotionPlus que quedara activo y deja la extension (Nunchuk) como normal
            self._init_extension_plain()
        self.set_led(self._led)
        time.sleep(0.03)
        self._cal_evt.clear()
        self.send([0x17, 0x00, 0x00, 0x00, 0x16, 0x00, 0x0A])
        got = self._cal_evt.wait(0.5)
        self._log("INIT", "Calibracion EEPROM %s: cero=%s 1g=%s" % ("recibida" if got else "NO recibida", self.acc_zero, self.acc_one))
        if self.want_ir:
            self.send([0x13, 0x04]); time.sleep(0.03)
            self.send([0x1A, 0x04]); time.sleep(0.03)
            self.write_reg(0xB00030, [0x01]); time.sleep(0.03)
            self.write_reg(0xB00000, [0x02, 0x00, 0x00, 0x71, 0x01, 0x00, 0xAA, 0x00, 0x64]); time.sleep(0.03)
            self.write_reg(0xB0001A, [0x63, 0x03]); time.sleep(0.03)
            self.write_reg(0xB00033, [0x01]); time.sleep(0.03)
            self.write_reg(0xB00030, [0x08]); time.sleep(0.05)
        if self.use_mp:
            self.write_reg(0xA600F0, [0x55]); time.sleep(0.06)
            self.write_reg(0xA600FE, [0x00]); time.sleep(0.3)
            self._log("INIT", "MotionPlus activado (modo independiente)")
        self.set_report_mode()
        self.last_rx = time.monotonic()
        self.initialized = True
        self.status_text = "Activo"
        self._log("INIT", "Configuracion terminada, informes 0x37 pedidos")


class Manager:
    """Busca mandos cada 1,5 s y crea un Wiimote por cada nodo hidraw (puerto de la barra = jugador)."""

    def __init__(self, log=None, on_frame=None, use_mp=False, ir=True):
        self.log, self.on_frame, self.use_mp, self.ir = log, on_frame, use_mp, ir
        self.devices = {}      # path -> Wiimote
        self.lock = threading.Lock()
        self._stop = False
        self.problems = []
        self._thread = None
        self.hid_seen = 0

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="wm-scan", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(2.0)
        with self.lock:
            for w in list(self.devices.values()):
                w.stop()
            self.devices.clear()

    def wiimotes(self):
        with self.lock:
            return sorted(self.devices.values(), key=lambda w: w.slot)

    def _free_slot(self):
        used = {w.slot for w in self.devices.values()}
        for s in range(4):
            if s not in used:
                return s
        return len(used) % 4

    def _loop(self):
        while not self._stop:
            try:
                self._scan()
            except Exception as ex:
                if self.log:
                    self.log.event("APP", "ERROR", "escaneo: %r" % ex)
            for _ in range(15):
                if self._stop:
                    return
                time.sleep(0.1)

    def _scan(self):
        infos = list_wiimote_hidraws()
        self.hid_seen = len(infos)
        self.problems = []
        with self.lock:
            for path, w in list(self.devices.items()):
                if w.failed:
                    if self.log:
                        self.log.event("APP", "HID", "Retirado mando de %s" % path)
                    w.stop()
                    del self.devices[path]
            known = set(self.devices)
        for info in infos:
            if info.path in known:
                continue
            if not os.access(info.path, os.R_OK | os.W_OK):
                self.problems.append("sin permiso en %s" % info.path)
                continue
            with self.lock:
                if info.port is not None and 1 <= info.port <= 4:
                    slot = info.port - 1
                    if any(w.slot == slot for w in self.devices.values()):
                        slot = self._free_slot()
                else:
                    slot = self._free_slot()
            wm = Wiimote(info, slot, use_mp=self.use_mp, log=self.log, on_frame=self.on_frame, ir=self.ir)
            try:
                wm.start()
            except OSError as e:
                self.problems.append("no se pudo abrir %s: %s" % (info.path, e))
                continue
            with self.lock:
                self.devices[info.path] = wm
            if self.log:
                self.log.event("APP", "HID", "Mando asignado al jugador %d (%s)" % (slot + 1, info.path))


# ------------------------------------------------------------------ CLI
def _main():
    if "--list" in sys.argv:
        infos = list_wiimote_hidraws()
        if not infos:
            print("No se encontro ningun nodo hidraw de Wii Remote / Dolphin Bar (057e:0306/0330).")
        for i in infos:
            ok = os.access(i.path, os.R_OK | os.W_OK)
            print("%s  puerto=%s  bus=%s  permisos=%s" % (i.path, i.port, i.bus, "OK" if ok else "FALTAN (ejecuta install-udev.sh)"))
        return
    if "--diag" in sys.argv:
        log = EventLog(os.path.expanduser("~/.local/share/wiilink"), "diag")

        def show(wm, f):
            if wm.frames_seen % 20 == 0:
                print("W%d btn=%04X acc=%s ir=%s ext=%s cls=%d" % (wm.slot + 1, f.buttons, tuple(round(x) for x in f.acc_raw), f.ir, hexs(f.ext), f.cls))
        mgr = Manager(log=log, on_frame=show)
        mgr.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            mgr.stop()
        return
    print(__doc__)


if __name__ == "__main__":
    _main()
