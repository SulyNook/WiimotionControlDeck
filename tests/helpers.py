import os, sys, struct
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "common"))
sys.path.insert(0, os.path.join(ROOT, "wiideck"))
sys.path.insert(0, os.path.join(ROOT, "wiisim"))
import wiilink as wl


def make_report(buttons=0, acc=(128, 128, 154), dots=(), ext=(0, 0, 0, 0, 0, 0)):
    """Construye un informe 0x37 (inverso de parse_data_report). acc en cuentas de 8 bits."""
    d = bytearray(22)
    d[0] = 0x37
    d[1] = buttons & 0x1F
    d[2] = (buttons >> 8) & 0x9F
    d[3], d[4], d[5] = acc
    pts = list(dots)[:4] + [(1023, 1023)] * (4 - len(list(dots)[:4]))
    for blk in range(2):
        (x1, y1), (x2, y2) = pts[blk * 2], pts[blk * 2 + 1]
        o = 6 + blk * 5
        d[o] = x1 & 0xFF
        d[o + 1] = y1 & 0xFF
        d[o + 2] = (((y1 >> 8) & 3) << 6) | (((x1 >> 8) & 3) << 4) | (((y2 >> 8) & 3) << 2) | ((x2 >> 8) & 3)
        d[o + 3] = x2 & 0xFF
        d[o + 4] = y2 & 0xFF
    d[16:22] = bytes(ext)
    return bytes(d)


class FakeUInput:
    def __init__(self):
        self.events = []
        self.opened = False

    def open(self):
        self.opened = True

    def emit(self, events):
        self.events.extend(events)

    def close(self):
        self.opened = False

    def where(self, typ, code):
        return [v for t, c, v in self.events if t == typ and c == code]


class FakeWm:
    def __init__(self, slot=0):
        self.slot = slot
        self.acc_zero = [128.0, 128.0, 128.0]
        self.acc_one = [154.0, 154.0, 154.0]
        self.battery = 80
        self.status_text = "Activo"
        self.leds = []
        self.rumbles = 0
        self.use_mp = False
        self.reinits = 0

    def request_reinit(self):
        self.reinits += 1

    def set_led(self, m):
        self.leds.append(m)

    def rumble(self, s=0.15):
        self.rumbles += 1
