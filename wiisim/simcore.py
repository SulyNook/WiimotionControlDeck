"""
simcore - procesado de un Wii Remote para el simulador: orientacion (giroscopio MotionPlus + acelerometro),
posicion (IR + arco de brazo), puntero, gestos y Nunchuk directo. Portado de la version v0.5 de Windows.
Ejes del cuerpo y del mundo: X = derecha, Y = adelante (hacia la barra), Z = arriba. La barra esta en el origen.
"""
import math
import time

import wiilink as wl

DEG = wl.DEG
G = 9.80665
SLOW_SCALE = 440.0 / 8192.0
FAST_SCALE = 2000.0 / 8192.0

CSV_HEADER = ("t,slot,frame,slow,raw_yaw,raw_roll,raw_pitch,gyro_y,gyro_r,gyro_p,ax,ay,az,amag,qw,qx,qy,qz,yaw,pitch,roll,"
              "px,py,pz,pos_src,ptr_src,ptr_nx,ptr_ny,ir_n,ir1x,ir1y,ir2x,ir2y,ir3x,ir3y,ir4x,ir4y,buttons,"
              "nun_sx,nun_sy,nun_ax,nun_ay,nun_az,nun_c,nun_z,raw_hex")

DEFAULT_SIM_CONFIG = {
    "invert_yaw": False, "invert_roll": False, "invert_pitch": False, "invert_accel_xy": False,
    "accel_gain": 1.5, "arm_length": 0.55, "use_accel_position": True, "yaw_ir_assist": True,
    "pointer_half_deg": 11.0, "bar_width": 0.20, "rest_fix": False, "nunchuk_direct": False,
    "show_trail": True, "show_frustum": True, "show_axes": True,
}


# ---------------------------------------------------------------- vectores y cuaterniones (tuplas)
def vadd(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def vsub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def vmul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def vdot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def vcross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def vlen(a): return math.sqrt(vdot(a, a))
def vnorm(a):
    n = vlen(a)
    return (a[0] / n, a[1] / n, a[2] / n) if n > 1e-12 else (0.0, 0.0, 0.0)
def vlerp(a, b, t): return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)

QI = (1.0, 0.0, 0.0, 0.0)


def qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def qconj(q): return (q[0], -q[1], -q[2], -q[3])


def qnorm(q):
    n = math.sqrt(sum(c * c for c in q))
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n) if n > 1e-12 else QI


def qaxis(axis, angle):
    s = math.sin(angle / 2)
    return (math.cos(angle / 2), axis[0] * s, axis[1] * s, axis[2] * s)


def qrot(q, v):
    """Rota el vector v por el cuaternion q (cuerpo -> mundo)."""
    w, x, y, z = q
    # v' = v + 2w(u x v) + 2 u x (u x v)
    u = (x, y, z)
    t = vmul(vcross(u, v), 2.0)
    return vadd(vadd(v, vmul(t, w)), vcross(u, t))


def q_from_to(a, b):
    d = vdot(a, b)
    if d > 0.99999:
        return QI
    if d < -0.99999:
        return qaxis((1.0, 0.0, 0.0), math.pi)
    ax = vnorm(vcross(a, b))
    return qaxis(ax, math.acos(max(-1.0, min(1.0, d))))


def euler(q):
    f = qrot(q, (0.0, 1.0, 0.0))
    r = qrot(q, (1.0, 0.0, 0.0))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, f[2]))))
    yaw = math.degrees(math.atan2(f[0], f[1]))
    roll = math.degrees(math.asin(max(-1.0, min(1.0, r[2]))))
    return yaw, pitch, roll


def smooth(x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    return x * x * (3 - 2 * x)


# ---------------------------------------------------------------- gestos
class Gestures:
    """Golpe/tajo, agitar, sacudida seca / empuje y tiron lento. Ejes del cuerpo: X derecha, Y adelante, Z arriba."""

    def __init__(self, who):
        self.who = who
        self.sign = [0, 0, 0]
        self.last_rev = [-9.0] * 3
        self.streak_t0 = [0.0] * 3
        self.rev = [0, 0, 0]
        self.peak = [0.0, 0.0, 0.0]
        self.shaking = False
        self.shake_t0 = self.shake_last = 0.0
        self.shake_max = 0
        self.shake_axis = 0
        self.shake_peak = 0.0
        self.swing = False
        self.swing_t0 = 0.0
        self.swing_low = 0.0
        self.swing_peak = 0.0
        self.swing_angle = [0.0, 0.0, 0.0]
        self.jerk = False
        self.jerk_t0 = 0.0
        self.last_jerk = -10.0
        self.last_swing_end = -10.0
        self.jerk_peak = 0.0
        self.jerk_dir = (0.0, 0.0, 0.0)
        self.pull = False
        self.pull_t0 = self.pull_low = 0.0
        self.last_pull = -10.0
        self.pull_peak = 0.0
        self.pull_sign = 0
        self.pull_dv = 0.0

    @staticmethod
    def _axis(k):
        return ("lateral", "adelante-atras", "vertical")[k]

    def _shake(self, t, dyn, thr):
        for k in range(3):
            a = abs(dyn[k])
            if a > thr:
                s = 1 if dyn[k] > 0 else -1
                if s != self.sign[k]:
                    if self.sign[k] != 0 and t - self.last_rev[k] < 0.4:
                        self.rev[k] += 1
                    else:
                        self.rev[k] = 1
                        self.streak_t0[k] = t
                        self.peak[k] = 0.0
                    self.last_rev[k] = t
                    self.sign[k] = s
                self.peak[k] = max(self.peak[k], a)
            if t - self.last_rev[k] > 0.5:
                self.rev[k] = 0
                self.sign[k] = 0
            if not self.shaking and self.rev[k] >= 4:
                self.shaking = True
                self.shake_axis = k
                self.shake_t0 = self.streak_t0[k]
                self.shake_last = t
                self.shake_max = self.rev[k]
                self.shake_peak = self.peak[k]
            if self.shaking and k == self.shake_axis:
                self.shake_max = max(self.shake_max, self.rev[k])
                self.shake_peak = max(self.shake_peak, self.peak[k])
                self.shake_last = max(self.shake_last, self.last_rev[k])
        if self.shaking and t - self.shake_last > 0.5:
            self.shaking = False
            dur = max(0.2, self.shake_last - self.shake_t0)
            n = self.shake_max
            self.rev = [0, 0, 0]
            self.sign = [0, 0, 0]
            return ("AGITAR x%d" % (n // 2),
                    "%s AGITAR: %d inversiones, %.1f Hz, eje %s, pico %.1f g, %.2f s" % (
                        self.who, n, (n / 2.0) / dur, self._axis(self.shake_axis), self.shake_peak, dur))
        return None

    def _jerk(self, t, dyn, thr, quiet, allowed):
        m = vlen(dyn)
        if not self.jerk:
            if allowed and m > thr and t - self.last_jerk > 0.25 and t - self.last_swing_end > 0.25:
                self.jerk, self.jerk_t0, self.jerk_peak, self.jerk_dir = True, t, m, dyn
            return None
        if m > self.jerk_peak:
            self.jerk_peak, self.jerk_dir = m, dyn
        if m < quiet or t - self.jerk_t0 > 0.4:
            self.jerk = False
            dur = t - self.jerk_t0
            self.last_jerk = t
            if dur > 0.30:
                return None
            ax, ay, az = abs(self.jerk_dir[0]), abs(self.jerk_dir[1]), abs(self.jerk_dir[2])
            d = self.jerk_dir
            if ay >= ax and ay >= az:
                what = "EMPUJE hacia delante" if d[1] > 0 else "TIRON hacia atras"
            elif ax >= az:
                what = "SACUDIDA seca a la derecha" if d[0] > 0 else "SACUDIDA seca a la izquierda"
            else:
                what = "SACUDIDA seca hacia arriba" if d[2] > 0 else "SACUDIDA seca hacia abajo"
            return (what, "%s %s: pico %.1f g, %.2f s" % (self.who, what, self.jerk_peak, dur))
        return None

    def _pull(self, t, dt, dyn, gm):
        y = dyn[1]
        if not self.pull:
            if gm < 150 and not self.swing and not self.shaking and not self.jerk and abs(y) > 0.8 \
                    and t - self.last_pull > 0.4 and t - self.last_jerk > 0.4:
                self.pull, self.pull_t0, self.pull_peak = True, t, abs(y)
                self.pull_sign, self.pull_dv, self.pull_low = (1 if y > 0 else -1), 0.0, 0.0
            return None
        same = (1 if y > 0 else -1) == self.pull_sign and abs(y) > 0.35 and gm < 200
        if same:
            self.pull_low = 0.0
            self.pull_peak = max(self.pull_peak, abs(y))
            self.pull_dv += abs(y) * G * dt
            if t - self.pull_t0 < 1.2:
                return None
        else:
            if self.pull_low == 0.0:
                self.pull_low = t
            if t - self.pull_low < 0.06:
                return None
        self.pull = False
        self.last_pull = t
        dur = (t if self.pull_low == 0.0 else self.pull_low) - self.pull_t0
        if dur < 0.30:
            return None
        what = "EMPUJE lento hacia delante" if self.pull_sign > 0 else "TIRON lento hacia atras"
        return (what, "%s %s: pico %.1f g, %.2f s, dv ~%.1f m/s" % (self.who, what, self.pull_peak, dur, self.pull_dv))

    def update_remote(self, t, dt, dyn_body, gyro_dps):
        """dyn_body: aceleracion lineal (g) en ejes del mando; gyro_dps: (pitch+arriba, roll+derecha, yaw+izquierda)."""
        ev = None
        gm = vlen(gyro_dps)
        if not self.swing:
            if gm > 250:
                self.swing, self.swing_t0, self.swing_peak, self.swing_angle, self.swing_low = True, t, gm, [0.0, 0.0, 0.0], 0.0
        if self.swing:
            for i in range(3):
                self.swing_angle[i] += gyro_dps[i] * dt
            self.swing_peak = max(self.swing_peak, gm)
            end = False
            if gm < 120:
                if self.swing_low == 0.0:
                    self.swing_low = t
                if t - self.swing_low > 0.05:
                    end = True
            else:
                self.swing_low = 0.0
            if t - self.swing_t0 > 1.0:
                self.swing = False
                self.last_swing_end = t
                end = False
            if end:
                self.swing = False
                self.last_swing_end = t
                dur = t - self.swing_t0
                A = self.swing_angle
                ax, ay, az = abs(A[0]), abs(A[1]), abs(A[2])
                dom = max(ax, ay, az)
                if self.swing_peak >= 300 and dur >= 0.05 and dom > 25:
                    if az >= ax and az >= ay:
                        what = "hacia la izquierda" if A[2] > 0 else "hacia la derecha"
                        if ax > 0.6 * az:
                            what = ("izquierda" if A[2] > 0 else "derecha") + ("-arriba (diagonal)" if A[0] > 0 else "-abajo (diagonal)")
                    elif ax >= ay:
                        what = "hacia arriba" if A[0] > 0 else "hacia abajo"
                        if az > 0.6 * ax:
                            what = ("arriba" if A[0] > 0 else "abajo") + ("-izquierda (diagonal)" if A[2] > 0 else "-derecha (diagonal)")
                    else:
                        what = "giro de muneca a la derecha" if A[1] > 0 else "giro de muneca a la izquierda"
                    ev = ("GOLPE " + what, "%s GOLPE %s: pico %.0f gr/s, giro (pitch %.0f, roll %.0f, yaw %.0f) en %.2f s" % (
                        self.who, what, self.swing_peak, A[0], A[1], A[2], dur))
        sh = self._shake(t, dyn_body, 0.7)
        ev = ev or sh
        jk = self._jerk(t, dyn_body, 1.6, 0.6, gm < 250 and not self.swing and not self.shaking)
        ev = ev or jk
        pl = self._pull(t, dt, dyn_body, gm)
        return ev or pl

    def update_nunchuk(self, t, dt, dyn):
        sh = self._shake(t, dyn, 0.7)
        jk = self._jerk(t, dyn, 0.9, 0.4, not self.shaking)
        return sh or jk


# ---------------------------------------------------------------- posicion
class PositionEstimator:
    """Posicion de la camara IR (m): con IR, medida absoluta; sin IR, arco de muneca/brazo segun la orientacion."""
    WRIST = 0.12

    def __init__(self):
        self.arm = 0.55
        self.pos = (0.0, -0.9, -0.2)
        self.vel = (0.0, 0.0, 0.0)
        self.home = (0.0, -0.9, -0.2)
        self.ever_ir = False
        self.prev_q = None
        self.lever = self.WRIST

    @staticmethod
    def clamp_area(p):
        return (wl.clamp(p[0], -1.5, 1.5), wl.clamp(p[1], -3.0, -0.25), wl.clamp(p[2], -1.0, 0.9))

    def update(self, q, acc_world_ms2, dt, gyro_dps, still_sec, ir_recent):
        if self.prev_q is None:
            self.prev_q = q
        target = self.WRIST + (self.arm - self.WRIST) * smooth((gyro_dps - 200.0) / 300.0)
        tau = 0.03 if target > self.lever else 0.5
        self.lever += (target - self.lever) * (1.0 - math.exp(-dt / tau))
        L = (0.0, self.lever, 0.0)
        self.pos = vadd(self.pos, vsub(qrot(q, L), qrot(self.prev_q, L)))
        self.prev_q = q
        if still_sec > 0.1:
            self.vel = (0.0, 0.0, 0.0)
        elif gyro_dps < 80.0:
            m = vlen(acc_world_ms2)
            a = vmul(acc_world_ms2, (m - 1.5) / m) if m > 1.5 else (0.0, 0.0, 0.0)
            self.vel = vmul(vadd(self.vel, vmul(a, dt)), math.exp(-2.5 * dt))
        else:
            self.vel = vmul(self.vel, math.exp(-8.0 * dt))
        sp = vlen(self.vel)
        if sp > 3.0:
            self.vel = vmul(self.vel, 3.0 / sp)
        self.pos = vadd(self.pos, vmul(self.vel, dt))
        if not ir_recent and still_sec > 0.5:
            self.pos = vadd(self.pos, vmul(vsub(self.home, self.pos), 1.0 - math.exp(-dt / 1.5)))
        self.pos = self.clamp_area(self.pos)

    def correct_ir(self, measured, dt, reacquired):
        m = self.clamp_area(measured)
        if not self.ever_ir:
            self.home = m
        self.ever_ir = True
        if reacquired:
            self.pos = m
            self.vel = (0.0, 0.0, 0.0)
        else:
            self.pos = vadd(self.pos, vmul(vsub(m, self.pos), 0.25))
            self.vel = vmul(self.vel, 0.9)
        self.home = vlerp(self.home, m, 1.0 - math.exp(-dt / 15.0))


# ---------------------------------------------------------------- mando simulado
class SimRemote:
    def __init__(self, cfg, log, slot):
        self.cfg, self.log, self.slot = cfg, log, slot
        self.q = QI
        self.need_init = True
        self.est = PositionEstimator()
        self.gest_remote = Gestures("Mando")
        self.gest_nun = Gestures("Nunchuk")
        self.pointer = wl.IRPointer()
        self.oe_x = wl.OneEuro(1.0, 1.5, 1.0)
        self.oe_y = wl.OneEuro(1.0, 1.5, 1.0)
        self.zero_slow = [8192.0] * 3
        self.zero_fast = [8192.0] * 3
        self.last_dps = [0.0, 0.0, 0.0]
        self.last_all_slow = True
        self.calib_req = False
        self.calib_active = False
        self.calib_n = 0
        self.calib_sum = [0.0] * 3
        self.calib_sq = [0.0] * 3
        self.calib_t0 = 0.0
        self.recenter_req = False
        self.still_count = 0
        self.g_lp = [0.0] * 3
        self.a_lp = 1.0
        self.g_dev = 0.0
        self.acc_dev = 0.0
        self.acc_lp = None
        self.g_norm = 1.0
        self.mag_ema = 1.0
        self.mag_n = 0
        self.prev_t = None
        self.prev_mp_t = None
        self.prev_buttons = 0
        self.last_mp_t = -9.0
        self.last_ir_t = -9.0
        self.last_nun_t = -9.0
        self.ir_was_visible = False
        self.ptr_ex = self.ptr_ez = self.ptr_yaw0 = self.ptr_pitch0 = 0.0
        self.ptr_ir_t = -9.0
        self.ptr_has = False
        self.ptr_out = (0.0, 0.0)
        self.ptr_prev_t = None
        self.rate = 0.0
        self._rate_n = 0
        self._rate_t = None
        self.frames = 0
        self.last_gesture = None
        self.last_gesture_t = -9.0
        self.burst_until = -9.0
        self.sample_div = 0
        self.nun = {"x": 0.0, "y": 0.0, "c": False, "z": False, "acc": (0.0, 0.0, 0.0), "center": None, "n": 0, "sum": [0.0, 0.0]}
        self.nun_lp = None
        self.nun_prev_t = None
        self.stat_t = None
        self.stat = {"rep": 0, "mp": 0, "nun": 0, "ir": 0}
        self.last_yaw_log = -9.0
        self.snapshot = {"connected": False}
        self.trail = []

    # ---- peticiones del usuario
    def request_calibrate(self):
        self.calib_req = True
        self._log("USER", "Calibrar giroscopio solicitado")

    def request_recenter(self):
        self.recenter_req = True
        self._log("USER", "Centrar yaw solicitado")

    def _log(self, cat, msg):
        if self.log:
            self.log.event("W%d" % (self.slot + 1), cat, msg)

    def _gesture(self, ev, t):
        if ev:
            self.last_gesture, self.last_gesture_t, self.burst_until = ev[0], t, t + 0.4
            self._log("GESTO", ev[1])

    def rotate_yaw(self, delta):
        self.q = qnorm(qmul(qaxis((0.0, 0.0, 1.0), delta), self.q))

    def recenter_yaw(self):
        f = qrot(self.q, (0.0, 1.0, 0.0))
        if f[0] * f[0] + f[1] * f[1] < 0.04:
            return
        psi = math.atan2(f[0], f[1])
        self.rotate_yaw(psi)

    # ---- informe
    def on_frame(self, wm, f):
        cfg = self.cfg
        t = f.t
        dt = wl.clamp(0.01 if self.prev_t is None else t - self.prev_t, 0.001, 0.05)
        self.prev_t = t
        self.frames += 1
        if self._rate_t is None:
            self._rate_t = t
        self._rate_n += 1
        if t - self._rate_t >= 1.0:
            self.rate = self._rate_n / (t - self._rate_t)
            self._rate_n, self._rate_t = 0, t

        # botones
        if f.buttons != self.prev_buttons:
            changed = f.buttons ^ self.prev_buttons
            for bit, name in wl.BUTTON_NAMES.items():
                if changed & bit:
                    self._log("BTN", ("+" if f.buttons & bit else "-") + name)
            if (f.buttons & wl.BTN_HOME) and not (self.prev_buttons & wl.BTN_HOME):
                self.recenter_req = True
            self.prev_buttons = f.buttons

        # acelerometro
        gs = [(f.acc_raw[k] - wm.acc_zero[k]) / (wm.acc_one[k] - wm.acc_zero[k]) for k in range(3)]
        acc_raw = (gs[0], gs[1], gs[2]) if cfg["invert_accel_xy"] else (-gs[0], -gs[1], gs[2])
        mag_raw = vlen(acc_raw)
        acc = vmul(acc_raw, self.g_norm)
        clip = any(v <= 1 or v >= 254 for v in f.acc_raw)

        # extension: MotionPlus (independiente) o Nunchuk directo
        mp = None if wm.use_mp is False else wl.decode_mp(f)
        nun_frame = (not wm.use_mp) and wl.decode_nunchuk_plain(f)
        if mp:
            self.last_mp_t = t
            self.stat["mp"] += 1
        dps = self.last_dps
        dt_mp = dt
        if mp:
            yaw_r, roll_r, pitch_r, s_yaw, s_roll, s_pitch, _ext = mp
            raw = (yaw_r, roll_r, pitch_r)
            slow = (s_yaw, s_roll, s_pitch)
            self.last_all_slow = s_yaw and s_roll and s_pitch
            dt_mp = wl.clamp(dt if self.prev_mp_t is None else t - self.prev_mp_t, 0.001, 0.1)
            self.prev_mp_t = t
            if self.calib_req:
                self.calib_req, self.calib_active, self.calib_n, self.calib_t0 = False, True, 0, t
                self.calib_sum, self.calib_sq = [0.0] * 3, [0.0] * 3
                self._log("CAL", "Calibrando giroscopio: no muevas el mando")
            if self.calib_active:
                if t - self.calib_t0 > 12:
                    self.calib_active = False
                    self._log("CAL", "Calibracion cancelada: el mando no estuvo quieto 12 s")
                elif self.last_all_slow:
                    for k in range(3):
                        self.calib_sum[k] += raw[k]
                        self.calib_sq[k] += raw[k] * raw[k]
                    self.calib_n += 1
                    if self.calib_n >= 150:
                        std = 0.0
                        for k in range(3):
                            mean = self.calib_sum[k] / self.calib_n
                            std = max(std, math.sqrt(max(0.0, self.calib_sq[k] / self.calib_n - mean * mean)))
                        if std > 6.0:
                            self._log("CAL", "Calibracion descartada (ruido %.1f > 6): se repite" % std)
                            self.calib_n, self.calib_sum, self.calib_sq = 0, [0.0] * 3, [0.0] * 3
                        else:
                            for k in range(3):
                                self.zero_slow[k] = self.zero_fast[k] = self.calib_sum[k] / self.calib_n
                            self.calib_active = False
                            self._log("CAL", "Giroscopio calibrado: cero=%s ruido=%.1f" % ([round(z, 1) for z in self.zero_slow], std))
                else:
                    self.calib_n, self.calib_sum, self.calib_sq = 0, [0.0] * 3, [0.0] * 3
            for k in range(3):
                zero = self.zero_slow[k] if slow[k] else self.zero_fast[k]
                scale = SLOW_SCALE if slow[k] else FAST_SCALE
                dps[k] = (raw[k] - zero) * scale
        gyro_mag = vlen(dps)

        # reposo (v0.5: media cercana a cero; "rest_fix": por estabilidad de las lecturas)
        la = 1.0 - math.exp(-dt / 0.25)
        dev_now = math.sqrt(sum((dps[k] - self.g_lp[k]) ** 2 for k in range(3)))
        self.g_dev += (dev_now - self.g_dev) * la
        for k in range(3):
            self.g_lp[k] += (dps[k] - self.g_lp[k]) * la
        if self.acc_lp is None:
            self.acc_lp = acc
        self.acc_dev += (vlen(vsub(acc, self.acc_lp)) - self.acc_dev) * la
        self.acc_lp = vlerp(self.acc_lp, acc, la)
        self.a_lp += (mag_raw * self.g_norm - self.a_lp) * la
        g_lp_mag = vlen(self.g_lp)
        if cfg.get("rest_fix"):
            still = self.last_all_slow and self.g_dev < 1.5 and dev_now < 8.0 and self.acc_dev < 0.03 and g_lp_mag < 12.0 \
                and abs(mag_raw - 1) < 0.1 and not self.calib_active and not clip
        else:
            still = self.last_all_slow and g_lp_mag < 2.0 and gyro_mag < 25.0 and abs(self.a_lp - 1.0) < 0.05 \
                and not self.calib_active and not clip
        self.still_count = self.still_count + 1 if still else 0
        if mp and self.still_count > 60:
            gain = 0.006 if cfg.get("rest_fix") else 0.02
            for k, r in enumerate((mp[0], mp[1], mp[2])):
                self.zero_slow[k] += (r - self.zero_slow[k]) * gain
                self.zero_fast[k] = self.zero_slow[k]
        if self.still_count > 40:
            self.mag_ema += (mag_raw - self.mag_ema) * 0.005
            self.mag_n += 1
            if self.mag_n >= 300:
                new_g = wl.clamp(1.0 / self.mag_ema, 0.9, 1.1)
                if abs(new_g - self.g_norm) > 0.004:
                    self._log("AUTOCAL", "Normalizacion de gravedad x%.3f -> x%.3f" % (self.g_norm, new_g))
                    self.g_norm = new_g

        # orientacion
        if self.need_init and mag_raw > 0.5:
            self.q = q_from_to(vnorm(acc), (0.0, 0.0, 1.0))
            self.need_init = False
            self._log("FUSION", "Orientacion inicial tomada de la gravedad")
        if self.recenter_req:
            self.recenter_req = False
            self.recenter_yaw()
            self._log("FUSION", "Yaw centrado")
        yaw_f = dps[0] * (-1 if cfg["invert_yaw"] else 1)
        roll_f = dps[1] * (-1 if cfg["invert_roll"] else 1)
        pitch_f = dps[2] * (-1 if cfg["invert_pitch"] else 1)
        gyro_body = (pitch_f, roll_f, -yaw_f)    # X pitch(+arriba) Y roll(+derecha) Z yaw(+izquierda), gr/s
        if mp:
            gyro_rad = (0.0, 0.0, 0.0) if self.calib_active else vmul(gyro_body, DEG)
            self._fuse(gyro_rad, acc, dt_mp, cfg["accel_gain"])
        elif t - self.last_mp_t > 0.5:
            self._fuse((0.0, 0.0, 0.0), acc, dt, cfg["accel_gain"])
        q = self.q
        lin_g = vsub(qrot(q, acc), (0.0, 0.0, 1.0))
        dyn_body = qrot(qconj(q), lin_g)

        # IR, posicion y puntero
        ir_recent_before = t - self.last_ir_t < 0.5
        still_sec = self.still_count / max(60.0, self.rate)
        self.est.arm = cfg["arm_length"]
        if cfg["use_accel_position"]:
            self.est.update(q, vmul(lin_g, G), dt, gyro_mag, still_sec, ir_recent_before)
        self.pointer.bar_width = cfg["bar_width"]
        info = self.pointer.update(f.ir, t)
        if info:
            u, v, z = info["u"], info["v"], info["dist"]
            p_ir = vmul(qrot(q, (u * z, z, v * z)), -1.0)
            if cfg["yaw_ir_assist"] and p_ir[1] < -0.25:
                phi = math.atan2(p_ir[0], -p_ir[1])
                ad = abs(phi) / DEG
                k = 0.0008 + 0.0092 * smooth((ad - 20.0) / 40.0)
                self.rotate_yaw(-k * phi)
                if ad > 30 and t - self.last_yaw_log > 5:
                    self.last_yaw_log = t
                    self._log("FUSION", "Yaw corregido con el IR: el mando estaba %.0f grados fuera del eje de la barra" % ad)
                q = self.q
            reacq = t - self.last_ir_t > 0.5
            self.est.correct_ir(p_ir, dt, reacq)
            if reacq:
                self._log("IR", "Barra vista: %d puntos, separacion %.0f px, distancia %.2f m" % (info["n"], info["sep"], z))
            self.last_ir_t = t
            self.stat["ir"] += 1
            self.ptr_ex, self.ptr_ez, self.ptr_ir_t, self.ptr_has = info["ex"], info["ez"], t, True
            fa = qrot(q, (0.0, 1.0, 0.0))
            self.ptr_yaw0 = math.atan2(fa[0], fa[1])
            self.ptr_pitch0 = math.asin(wl.clamp(fa[2], -1, 1))
        ir_visible = t - self.last_ir_t < 0.25
        if self.ir_was_visible and not ir_visible:
            self._log("IR", "Barra perdida: la posicion sigue la orientacion (arco de muneca/brazo)")
        self.ir_was_visible = ir_visible

        ptr_valid = ptr_est = False
        nx = ny = 0.0
        if self.ptr_has:
            age = t - self.ptr_ir_t
            ex, ez = self.ptr_ex, self.ptr_ez
            if age < 0.25:
                ptr_valid = True
            elif age < 3.0:
                fb = qrot(q, (0.0, 1.0, 0.0))
                ex += wl.wrap_angle(math.atan2(fb[0], fb[1]) - self.ptr_yaw0)
                ez += math.asin(wl.clamp(fb[2], -1, 1)) - self.ptr_pitch0
                ptr_valid = ptr_est = True
            if ptr_valid:
                half = max(2.0, cfg["pointer_half_deg"]) * DEG
                half_y = half * 9.0 / 16.0
                raw_nx, raw_ny = ex / half, (ez - 1.18 * half_y) / half_y
                pdt = 0.01 if self.ptr_prev_t is None else wl.clamp(t - self.ptr_prev_t, 0.001, 0.1)
                self.ptr_prev_t = t
                if abs(raw_nx - self.ptr_out[0]) > 0.8 or abs(raw_ny - self.ptr_out[1]) > 0.8:
                    self.oe_x.reset()
                    self.oe_y.reset()
                nx, ny = self.oe_x.filter(raw_nx, pdt), self.oe_y.filter(raw_ny, pdt)
                self.ptr_out = (nx, ny)

        # Nunchuk directo
        nun_connected = False
        if nun_frame:
            self._nunchuk(nun_frame, t)
        nun_connected = t - self.last_nun_t < 0.7

        # gestos del mando
        if not self.calib_active:
            self._gesture(self.gest_remote.update_remote(t, dt, dyn_body, gyro_body), t)
        if acc and vlen(acc) > 2.0 or gyro_mag > 250:
            self.burst_until = t + 0.4

        # estadisticas y muestras
        self.stat["rep"] += 1
        if self.stat_t is None:
            self.stat_t = t
        if t - self.stat_t >= 1.0:
            self._log("STAT", "informes=%.0f/s mp=%d nunchuk=%d ir=%d pos=(%.2f,%.2f,%.2f) puntero=(%.2f,%.2f)%s" % (
                self.rate, self.stat["mp"], self.stat["nun"], self.stat["ir"], self.est.pos[0], self.est.pos[1], self.est.pos[2],
                nx, ny, (" est" if ptr_est else " IR") if ptr_valid else " --"))
            self.stat = {"rep": 0, "mp": 0, "nun": 0, "ir": 0}
            self.stat_t = t
        self.sample_div += 1
        if (self.sample_div & 3) == 0 or t < self.burst_until:
            yaw_d, pitch_d, roll_d = euler(q)
            dots = list(f.ir) + [None] * (4 - len(f.ir))
            row = [("%.3f" % (self.log.now() if self.log else 0)), self.slot + 1, "MP" if mp else ("NUN" if nun_frame else "OTRO"),
                   int(self.last_all_slow), mp[0] if mp else 0, mp[1] if mp else 0, mp[2] if mp else 0,
                   "%.2f" % dps[0], "%.2f" % dps[1], "%.2f" % dps[2], "%.3f" % acc[0], "%.3f" % acc[1], "%.3f" % acc[2], "%.3f" % vlen(acc),
                   "%.4f" % q[0], "%.4f" % q[1], "%.4f" % q[2], "%.4f" % q[3], "%.2f" % yaw_d, "%.2f" % pitch_d, "%.2f" % roll_d,
                   "%.3f" % self.est.pos[0], "%.3f" % self.est.pos[1], "%.3f" % self.est.pos[2], "IR" if ir_visible else "EST",
                   ("EST" if ptr_est else "IR") if ptr_valid else "NO", "%.3f" % nx if ptr_valid else "", "%.3f" % ny if ptr_valid else "",
                   len(f.ir)]
            for d in dots:
                row += ["%d" % d[0], "%d" % d[1]] if d else ["", ""]
            row += [f.buttons, "%.3f" % self.nun["x"], "%.3f" % self.nun["y"], "%.3f" % self.nun["acc"][0], "%.3f" % self.nun["acc"][1],
                    "%.3f" % self.nun["acc"][2], int(self.nun["c"]), int(self.nun["z"]), wl.hexs(f.raw)]
            if self.log:
                self.log.sample(",".join(str(x) for x in row))

        # estela
        if self.trail:
            last = self.trail[-1][0]
            if vlen(vsub(self.est.pos, last)) > 0.006:
                self.trail.append((self.est.pos, ir_visible))
        else:
            self.trail.append((self.est.pos, ir_visible))
        if len(self.trail) > 90:
            self.trail.pop(0)

        self.snapshot = {
            "connected": True, "q": q, "pos": self.est.pos, "ir_visible": ir_visible, "ir_ever": self.est.ever_ir,
            "buttons": f.buttons, "acc": acc, "gyro": tuple(dps), "mp_active": t - self.last_mp_t < 0.5,
            "dots": list(f.ir), "battery": wm.battery, "rate": self.rate, "calib": (self.calib_n / 150.0) if self.calib_active else -1.0,
            "clip": clip, "g_norm": self.g_norm, "ptr_valid": ptr_valid, "ptr_est": ptr_est, "nx": nx, "ny": ny,
            "gesture": self.last_gesture, "gesture_age": t - self.last_gesture_t, "nun_connected": nun_connected,
            "nun": dict(self.nun), "t": t, "still": still, "slow": self.last_all_slow, "status": wm.status_text,
        }

    def _fuse(self, gyro, acc, dt, kp):
        w = gyro
        mag = vlen(acc)
        if mag > 0.01 and abs(mag - 1.0) < 0.25:
            mu = vmul(acc, 1.0 / mag)
            eu = qrot(qconj(self.q), (0.0, 0.0, 1.0))
            w = vadd(w, vmul(vcross(mu, eu), kp))
        ang = vlen(w) * dt
        if ang > 1e-9:
            self.q = qnorm(qmul(self.q, qaxis(vmul(w, 1.0 / vlen(w)), ang)))

    def _nunchuk(self, n, t):
        self.stat["nun"] += 1
        nu = self.nun
        if nu["center"] is None:
            nu["n"] += 1
            nu["sum"][0] += n["sx"]
            nu["sum"][1] += n["sy"]
            if nu["n"] >= 15:
                nu["center"] = (nu["sum"][0] / nu["n"], nu["sum"][1] / nu["n"])
                self._log("NUNCHUK", "Centro de la palanca: (%.1f, %.1f)" % nu["center"])
        cx, cy = nu["center"] if nu["center"] else (131.0, 125.0)
        nu["x"] = wl.clamp((n["sx"] - cx) / 95.0, -1, 1)
        nu["y"] = wl.clamp((n["sy"] - cy) / 95.0, -1, 1)
        nu["acc"] = n["acc"]
        for key in ("c", "z"):
            if n[key] != nu[key]:
                self._log("NUNCHUK", ("+" if n[key] else "-") + key.upper())
            nu[key] = n[key]
        if self.last_nun_t < 0 or t - self.last_nun_t > 1.0:
            self._log("NUNCHUK", "Datos de Nunchuk recibidos")
        self.last_nun_t = t
        if self.nun_lp is None:
            self.nun_lp, self.nun_prev_t = n["acc"], t
        ndt = wl.clamp(t - self.nun_prev_t, 0.005, 0.2)
        self.nun_prev_t = t
        self.nun_lp = vlerp(self.nun_lp, n["acc"], 1.0 - math.exp(-ndt / 0.2))
        self._gesture(self.gest_nun.update_nunchuk(t, ndt, vsub(n["acc"], self.nun_lp)), t)
