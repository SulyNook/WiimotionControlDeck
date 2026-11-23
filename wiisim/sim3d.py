"""
sim3d - software 3D viewer (no OpenGL): orbital camera, remote/Nunchuk/scene models, painter's algorithm.
Draws onto a "surface" (Tk Canvas in the app, PIL in the tests). World coordinates: X right,
Y forward (toward the bar/screen), Z up; origin = center of the Dolphin Bar.
"""
import math

import simcore as sc
from simcore import vadd, vsub, vmul, vdot, vcross, vnorm, vlen, qrot

SLOT_COLORS = ((63, 169, 245), (245, 90, 63), (76, 217, 100), (255, 204, 0))
FLOOR_Z = -1.2
LIGHT = vnorm((0.35, -0.55, 0.85))   # toward the light source
TV_CENTER = (0.0, 0.0, 0.32)
TV_HALF = (0.5, 0.29)


def hexcolor(c, k=1.0):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(v * k))) for v in c)


# ----------------------------------------------------------------- meshes
def box(cx, cy, cz, sx, sy, sz, color):
    """Box as a list of faces (4 vertices, normal, color)."""
    x, y, z = sx / 2, sy / 2, sz / 2
    P = lambda dx, dy, dz: (cx + dx, cy + dy, cz + dz)
    return [
        ([P(-x, -y, z), P(x, -y, z), P(x, y, z), P(-x, y, z)], (0, 0, 1), color),
        ([P(-x, -y, -z), P(-x, y, -z), P(x, y, -z), P(x, -y, -z)], (0, 0, -1), color),
        ([P(x, -y, -z), P(x, y, -z), P(x, y, z), P(x, -y, z)], (1, 0, 0), color),
        ([P(-x, -y, -z), P(-x, -y, z), P(-x, y, z), P(-x, y, -z)], (-1, 0, 0), color),
        ([P(-x, y, -z), P(-x, y, z), P(x, y, z), P(x, y, -z)], (0, 1, 0), color),
        ([P(-x, -y, -z), P(x, -y, -z), P(x, -y, z), P(-x, -y, z)], (0, -1, 0), color),
    ]


def qmat(q):
    w, x, y, z = q
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)))


def mmul(R, v):
    return (R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2],
            R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2],
            R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2])


def place(faces, R, t):
    """Moves faces from local coordinates to world coordinates."""
    out = []
    for verts, n, col in faces:
        out.append(([vadd(mmul(R, v), t) for v in verts], mmul(R, n), col))
    return out


def remote_faces(buttons, slot, show_axes=True):
    """Wii Remote centered on its body (X right, Y forward, Z up)."""
    W, L, H = 0.036, 0.148, 0.031
    top = H / 2
    PRESSED = (255, 214, 10)
    white, dark, gray, silver = (236, 237, 242), (52, 54, 62), (120, 122, 130), (206, 209, 216)
    col = SLOT_COLORS[slot & 3]

    def pr(mask, normal):
        return PRESSED if buttons & mask else normal
    f = []
    f += box(0, 0, 0, W, L, H, white)
    f += box(0, L / 2 + 0.0006, 0, 0.025, 0.0016, 0.013, (30, 10, 16))          # IR window
    f += box(0, 0.056, top + 0.001, 0.008, 0.008, 0.002, silver)                  # power
    dp = PRESSED if buttons & (wl_btn("Left") | wl_btn("Right") | wl_btn("Up") | wl_btn("Down")) else dark
    f += box(0, 0.040, top + 0.001, 0.0215, 0.0072, 0.0024, dp)                   # D-pad
    f += box(0, 0.040, top + 0.001, 0.0072, 0.0215, 0.0024, dp)
    f += box(0, 0.019, top + 0.002, 0.016, 0.016, 0.0036, pr(wl_btn("A"), (226, 230, 238)))   # A
    f += box(-0.0115, -0.002, top + 0.001, 0.008, 0.008, 0.002, pr(wl_btn("Minus"), silver))
    f += box(0, -0.002, top + 0.001, 0.010, 0.010, 0.0024, pr(wl_btn("Home"), silver))
    f += box(0.0115, -0.002, top + 0.001, 0.008, 0.008, 0.002, pr(wl_btn("Plus"), silver))
    f += box(0, -0.031, top + 0.0015, 0.010, 0.010, 0.003, pr(wl_btn("One"), silver))
    f += box(0, -0.0445, top + 0.0015, 0.010, 0.010, 0.003, pr(wl_btn("Two"), silver))
    f += box(0, 0.020, -top - 0.0016, 0.017, 0.032, 0.0075, pr(wl_btn("B"), gray))          # B trigger
    f += box(0, -0.0535, 0, W + 0.001, 0.003, H + 0.001, col)                              # player band
    for i in range(4):
        f += box(-0.0105 + i * 0.007, -0.0645, top + 0.0005, 0.004, 0.004, 0.001, col if i == (slot & 3) else gray)
    if show_axes:
        f += box(W / 2 + 0.05, 0, 0, 0.10, 0.0016, 0.0016, (235, 70, 70))
        f += box(0, L / 2 + 0.06, 0, 0.0016, 0.12, 0.0016, (70, 220, 100))
        f += box(0, 0, H / 2 + 0.05, 0.0016, 0.0016, 0.10, (80, 150, 255))
    return f


def wl_btn(name):
    import wiilink as wl
    return wl.NAME_TO_BTN[name]


def nunchuk_faces(slot, stick, c, z):
    W, L, H = 0.036, 0.100, 0.040
    top = H / 2
    PRESSED = (255, 214, 10)
    f = []
    f += box(0, 0, 0, W, L, H, (236, 237, 242))
    f += box(0, -0.030, 0, W + 0.001, 0.003, H + 0.001, SLOT_COLORS[slot & 3])
    f += box(0, 0.020, top + 0.0015, 0.026, 0.026, 0.003, (60, 62, 70))
    # stick: base and cap offset according to the tilt
    sx, sy = stick
    tx, ty = sx * 0.012, sy * 0.012
    f += box(tx * 0.5, 0.020 + ty * 0.5, top + 0.009, 0.010, 0.010, 0.012, (70, 72, 80))
    f += box(tx, 0.020 + ty, top + 0.016, 0.020, 0.020, 0.004, (70, 72, 80))
    f += box(0, -0.012, top + 0.0015, 0.014, 0.014, 0.003, PRESSED if c else (235, 238, 245))
    f += box(0, 0.026, -top - 0.0012, 0.020, 0.030, 0.007, PRESSED if z else (120, 122, 130))
    f += box(0, -L / 2 - 0.006, 0, 0.007, 0.012, 0.007, (60, 62, 70))
    return f


# ----------------------------------------------------------------- camera
class Camera:
    def __init__(self):
        self.reset()

    def reset(self):
        self.az, self.el, self.dist = 0.0, 0.25, 2.7
        self.target = (0.0, -0.5, -0.1)
        self.fov = 50.0

    def position(self):
        ce = math.cos(self.el)
        return (self.target[0] + self.dist * ce * math.sin(self.az),
                self.target[1] - self.dist * ce * math.cos(self.az),
                self.target[2] + self.dist * math.sin(self.el))

    def basis(self):
        pos = self.position()
        f = vnorm(vsub(self.target, pos))
        r = vnorm(vcross(f, (0.0, 0.0, 1.0)))
        u = vcross(r, f)
        return pos, f, r, u

    def projector(self, w, h):
        pos, f, r, u = self.basis()
        k = (w / 2.0) / math.tan(math.radians(self.fov) / 2)

        def proj(p):
            v = vsub(p, pos)
            z = vdot(v, f)
            if z < 0.05:
                return None
            return (w / 2.0 + vdot(v, r) / z * k, h / 2.0 - vdot(v, u) / z * k, z)
        return proj, pos


# ----------------------------------------------------------------- surfaces
class TkSurface:
    def __init__(self, canvas):
        self.c = canvas
        self.w = self.h = 0

    def begin(self, w, h, bg):
        self.w, self.h = w, h
        self.c.delete("all")
        self.c.configure(bg=bg)

    def poly(self, pts, fill, outline=""):
        flat = []
        for p in pts:
            flat.extend((p[0], p[1]))
        self.c.create_polygon(*flat, fill=fill, outline=outline)

    def line(self, a, b, color, width=1):
        self.c.create_line(a[0], a[1], b[0], b[1], fill=color, width=width)

    def text(self, x, y, s, color, size=10, anchor="center", bold=False):
        self.c.create_text(x, y, text=s, fill=color, anchor=anchor, font=("DejaVu Sans", size, "bold" if bold else "normal"))

    def end(self):
        pass


class PILSurface:
    def __init__(self):
        self.img = None

    def begin(self, w, h, bg):
        from PIL import Image, ImageDraw
        self.w, self.h = w, h
        self.img = Image.new("RGB", (w, h), bg)
        self.d = ImageDraw.Draw(self.img)

    def poly(self, pts, fill, outline=""):
        self.d.polygon([(p[0], p[1]) for p in pts], fill=fill, outline=outline or None)

    def line(self, a, b, color, width=1):
        self.d.line([(a[0], a[1]), (b[0], b[1])], fill=color, width=width)

    def text(self, x, y, s, color, size=10, anchor="center", bold=False):
        w = len(s) * size * 0.55
        ax = x - w / 2 if anchor == "center" else x
        self.d.text((ax, y - size / 2 - 2), s, fill=color)

    def end(self):
        pass


# ----------------------------------------------------------------- scene
class Scene:
    def __init__(self):
        self.static = self._build_static()

    def _build_static(self):
        f = []
        # table and television
        f += box(0, 0.18, -0.045, 1.5, 0.55, 0.04, (92, 70, 54))
        for lx in (-0.68, 0.68):
            for ly in (-0.04, 0.40):
                f += box(lx, ly, FLOOR_Z / 2 - 0.03, 0.045, 0.045, -FLOOR_Z - 0.06, (80, 60, 46))
        f += box(0, 0.032, 0.32, 1.06, 0.036, 0.62, (16, 18, 22))       # frame
        f += box(0, 0.09, 0.0, 0.18, 0.08, 0.05, (16, 18, 22))          # stand
        f += box(0, 0.0125, 0.32, 1.0, 0.002, 0.58, (24, 40, 74))       # screen
        # Dolphin Bar
        f += box(0, -0.024, -0.020, 0.26, 0.030, 0.022, (26, 27, 32))
        f += box(-0.105, -0.0405, -0.020, 0.020, 0.003, 0.010, (255, 80, 80))
        f += box(0.105, -0.0405, -0.020, 0.020, 0.003, 0.010, (255, 80, 80))
        f += box(0, -0.0405, -0.020, 0.006, 0.002, 0.004, (70, 230, 120))
        return f

    @staticmethod
    def shade(n, col, emissive=False):
        if emissive:
            return hexcolor(col)
        k = 0.38 + 0.62 * max(0.0, vdot(n, LIGHT))
        return hexcolor(col, k)

    def render(self, surf, w, h, cam, remotes, cfg, hud=None):
        """remotes: list of (slot, snapshot) of connected remotes."""
        proj, cam_pos = cam.projector(w, h)
        surf.begin(w, h, "#0e1521")

        def P(p):
            return proj(p)

        # floor: grid and play area
        for i in range(-8, 9):
            x = i * 0.5
            a, b = P((x, -5.0, FLOOR_Z)), P((x, 2.0, FLOOR_Z))
            if a and b:
                surf.line(a, b, "#24385a" if i % 2 == 0 else "#1a2740", 1)
        for j in range(-10, 3):
            y = j * 0.5
            a, b = P((-4.0, y, FLOOR_Z)), P((4.0, y, FLOOR_Z))
            if a and b:
                surf.line(a, b, "#24385a" if j % 2 == 0 else "#1a2740", 1)
        zone = [(-1.5, -3.0), (1.5, -3.0), (1.5, -0.25), (-1.5, -0.25), (-1.5, -3.0)]
        for (x0, y0), (x1, y1) in zip(zone, zone[1:]):
            a, b = P((x0, y0, FLOOR_Z + 0.003)), P((x1, y1, FLOOR_Z + 0.003))
            if a and b:
                surf.line(a, b, "#3c6496", 2)

        faces = list(self.static)
        labels = []
        overlays = []
        for slot, s in remotes:
            q = s["q"]
            R = qmat(q)
            tip = s["pos"]
            center = vsub(tip, mmul(R, (0.0, 0.074, 0.0)))
            faces += place(remote_faces(s["buttons"], slot, cfg.get("show_axes", True)), R, center)
            if s["nun_connected"]:
                f = qrot(q, (0.0, 1.0, 0.0))
                psi = math.atan2(f[0], f[1]) if f[0] ** 2 + f[1] ** 2 > 0.04 else 0.0
                qyaw = sc.qaxis((0, 0, 1), -psi)
                nacc = s["nun"]["acc"]
                nm = vlen(nacc)
                qtilt = sc.q_from_to(vmul(nacc, 1 / nm), (0.0, 0.0, 1.0)) if nm > 0.3 else sc.QI
                qn = sc.qnorm(sc.qmul(qyaw, qtilt))
                off = qrot(qyaw, (-0.26, -0.02, -0.06))
                faces += place(nunchuk_faces(slot, (s["nun"]["x"], s["nun"]["y"]), s["nun"]["c"], s["nun"]["z"]), qmat(qn), vadd(vadd(center, off), (0, 0, 0)))
            col = SLOT_COLORS[slot & 3]
            # shadow and height rod
            sh = []
            for k in range(14):
                a = k / 14 * 2 * math.pi
                pt = P((tip[0] + 0.075 * math.cos(a), tip[1] + 0.075 * math.sin(a), FLOOR_Z + 0.003))
                if pt:
                    sh.append(pt)
            overlays.append(("shadow", sh))
            overlays.append(("stem", P(tip), P((tip[0], tip[1], FLOOR_Z)), col))
            if cfg.get("show_trail", True) and len(s.get("trail", [])) > 1:
                overlays.append(("trail", [(P(p), ir) for p, ir in s["trail"]], col))
            # pointer on the screen and beam
            if s["ptr_valid"] and abs(s["nx"]) < 1.5 and abs(s["ny"]) < 1.5:
                hit = (TV_CENTER[0] + s["nx"] * TV_HALF[0], 0.011, TV_CENTER[2] + s["ny"] * TV_HALF[1])
                overlays.append(("pointer", hit, col, s["ptr_est"]))
                if not s["ptr_est"]:
                    overlays.append(("laser", P(tip), P(hit), col))
            if cfg.get("show_frustum", True):
                far = 0.9
                hx, hz = far * math.tan(math.radians(20.5)), far * math.tan(math.radians(15.5))
                for sx_, sz_ in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                    corner = vadd(center, mmul(R, (sx_ * hx, 0.074 + far, sz_ * hz)))
                    overlays.append(("ray", P(tip), P(corner), col))
            lp = P(vadd(center, (0, 0, 0.13)))
            if lp:
                txt = "Remote %d  %s" % (slot + 1, "IR" if s["ir_visible"] else ("EST" if s["ir_ever"] else "--"))
                if s["nun_connected"]:
                    txt += " +Nunchuk"
                if s["gesture"] and s["gesture_age"] < 1.5:
                    txt += "\n" + s["gesture"]
                labels.append((lp, txt, col))

        for kind, *rest in overlays:
            if kind == "shadow" and len(rest[0]) > 2:
                surf.poly(rest[0], "#070b12")
            elif kind == "stem" and rest[0] and rest[1]:
                surf.line(rest[0], rest[1], hexcolor(rest[2], 0.5), 1)

        # sorted polygons (painter's algorithm) with back-face culling
        todraw = []
        for verts, n, col in faces:
            cen = vmul(vadd(vadd(verts[0], verts[1]), vadd(verts[2], verts[3])), 0.25)
            if vdot(n, vsub(cam_pos, cen)) <= 0:
                continue
            pts = [P(v) for v in verts]
            if any(p is None for p in pts):
                continue
            todraw.append((vlen(vsub(cam_pos, cen)), pts, n, col))
        todraw.sort(key=lambda t: -t[0])
        for _, pts, n, col in todraw:
            emissive = col in ((255, 80, 80), (70, 230, 120), (255, 214, 10), (24, 40, 74), (235, 70, 70), (70, 220, 100), (80, 150, 255))
            surf.poly(pts, self.shade(n, col, emissive), "")

        for ov in overlays:
            kind = ov[0]
            if kind == "trail":
                pts, col = ov[1], ov[2]
                for i in range(1, len(pts)):
                    (a, _), (b, ir) = pts[i - 1], pts[i]
                    if a and b:
                        age = i / len(pts)
                        surf.line(a, b, hexcolor(col if ir else (235, 235, 245), 0.35 + 0.65 * age), 1 + int(2 * age))
            elif kind == "ray":
                if ov[1] and ov[2]:
                    surf.line(ov[1], ov[2], hexcolor(ov[3], 0.35), 1)
            elif kind == "laser":
                if ov[1] and ov[2]:
                    surf.line(ov[1], ov[2], hexcolor(ov[3]), 2)
            elif kind == "pointer":
                hit, col, est = ov[1], ov[2], ov[3]
                ring = []
                for k in range(14):
                    a = k / 14 * 2 * math.pi
                    pt = P((hit[0] + 0.03 * math.cos(a), hit[1], hit[2] + 0.03 * math.sin(a)))
                    if pt:
                        ring.append(pt)
                if len(ring) > 2:
                    surf.poly(ring, "" if est else hexcolor(col), hexcolor(col))
        for (lp, txt, col) in labels:
            lines = txt.split("\n")
            for i, ln in enumerate(lines):
                surf.text(lp[0], lp[1] - 16 + i * 15, ln, hexcolor(col), 10 if i == 0 else 9, bold=(i == 0))
        if hud:
            surf.text(12, h - 12, hud, "#6b7f94", 9, anchor="w")
        surf.end()
