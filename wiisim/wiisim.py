#!/usr/bin/env python3
"""
WiiSim - 3D Wii Remote Plus simulator (MotionPlus + IR + Nunchuk) for Linux, via Dolphin Bar in mode 4.
Linux version of WiiMotionSim (Windows). Standard library only (tkinter for the window).

  Mouse: drag = orbit, wheel = zoom.   C: calibrate gyro (remote at rest)   R / Home button: recenter yaw
  F2: write a line to the log (// Start / // End)

  --nogui   no window: only logs events and samples (for debugging)      --list   remotes found
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "common")):
    if os.path.exists(os.path.join(_p, "wiilink.py")):
        sys.path.insert(0, _p)
import wiilink as wl  # noqa: E402
import simcore as sc  # noqa: E402
import sim3d  # noqa: E402

APP_NAME = "WiiSim"
VERSION = "0.1"
CONFIG_DIR = os.path.expanduser("~/.config/wiisim")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_DIR = os.path.expanduser("~/Documents/WiiSim/Logs") if os.path.isdir(os.path.expanduser("~/Documents")) \
    else os.path.expanduser("~/.local/share/wiisim/logs")


def load_config():
    cfg = dict(sc.DEFAULT_SIM_CONFIG)
    try:
        with open(CONFIG_PATH) as f:
            user = json.load(f)
        for k, v in user.items():
            if k in cfg:
                cfg[k] = v
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


class SimApp:
    """Ties the remotes (wiilink) to one SimRemote per player."""

    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        self.sims = {}
        self.mgr = None

    def start(self):
        self.mgr = wl.Manager(log=self.log, on_frame=self.on_frame, use_mp=not self.cfg["nunchuk_direct"], ir=True)
        self.mgr.start()

    def stop(self):
        if self.mgr:
            self.mgr.stop()

    def restart(self):
        """Switching between MotionPlus and direct Nunchuk requires reopening the remotes."""
        self.stop()
        self.sims.clear()
        self.start()

    def on_frame(self, wm, f):
        sim = self.sims.get(wm.slot)
        if sim is None:
            sim = sc.SimRemote(self.cfg, self.log, wm.slot)
            self.sims[wm.slot] = sim
        sim.on_frame(wm, f)

    def snapshots(self):
        now = time.monotonic()
        out = []
        for slot in sorted(self.sims):
            s = self.sims[slot].snapshot
            if s.get("connected") and now - s["t"] < 1.0:
                s = dict(s)
                s["trail"] = list(self.sims[slot].trail)
                out.append((slot, s))
        return out

    def each(self, fn):
        for sim in list(self.sims.values()):
            fn(sim)


def run_gui(app, log, cfg):
    import tkinter as tk

    BG, PANEL, FG, DIM = "#0d1117", "#161d27", "#e6edf3", "#8fa3b8"
    root = tk.Tk()
    root.title("%s %s - Wii Remote Plus 3D" % (APP_NAME, VERSION))
    root.configure(bg=BG)
    root.geometry("1360x820")

    left = tk.Frame(root, bg=BG)
    left.pack(side="left", fill="both", expand=True)
    canvas = tk.Canvas(left, bg="#0e1521", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    note_bar = tk.Frame(left, bg="#101720")
    note_bar.pack(fill="x")
    tk.Label(note_bar, text="Log line:", fg=DIM, bg="#101720").pack(side="left", padx=8)
    note = tk.Entry(note_bar, bg=BG, fg=FG, insertbackground=FG, relief="flat")
    note.pack(side="left", fill="x", expand=True, pady=6)

    def write_note(prefix="", suffix=""):
        t = note.get().strip()
        if prefix or suffix:
            t = "%s%s%s" % (prefix, t or "Test", suffix)
        if t:
            log.note(t)
        note.delete(0, "end")

    tk.Button(note_bar, text="Add note", command=write_note).pack(side="left", padx=4)
    tk.Button(note_bar, text="// Start", command=lambda: write_note("// ", " Start")).pack(side="left", padx=4)
    tk.Button(note_bar, text="// End", command=lambda: write_note("// ", " End")).pack(side="left", padx=(4, 8))
    note.bind("<Return>", lambda e: write_note())
    note.bind("<Escape>", lambda e: root.focus_set())

    panel_outer = tk.Frame(root, bg=PANEL, width=400)
    panel_outer.pack(side="right", fill="y")
    panel_outer.pack_propagate(False)
    panel = tk.Frame(panel_outer, bg=PANEL)
    panel.pack(fill="both", expand=True, padx=10, pady=8)

    tk.Label(panel, text="WiiSim - Wii Remote Plus 3D", font=("DejaVu Sans", 15, "bold"), fg=FG, bg=PANEL).pack(anchor="w")
    info = tk.Label(panel, text="", fg=DIM, bg=PANEL, anchor="w", justify="left", wraplength=370)
    info.pack(fill="x")
    cards = []
    for i in range(4):
        lb = tk.Label(panel, text="", font=("DejaVu Sans Mono", 9), fg=FG, bg="#1c2530", anchor="nw", justify="left",
                      highlightthickness=2, highlightbackground=sim3d.hexcolor(sim3d.SLOT_COLORS[i]), padx=6, pady=4)
        cards.append(lb)

    row = tk.Frame(panel, bg=PANEL)
    row.pack(fill="x", pady=4)
    tk.Button(row, text="Calibrate gyro (C)", command=lambda: app.each(lambda s: s.request_calibrate())).pack(side="left", padx=2)
    tk.Button(row, text="Recenter yaw (R)", command=lambda: app.each(lambda s: s.request_recenter())).pack(side="left", padx=2)
    row2 = tk.Frame(panel, bg=PANEL)
    row2.pack(fill="x")
    cam = sim3d.Camera()
    tk.Button(row2, text="Reset camera", command=cam.reset).pack(side="left", padx=2)

    def open_logs():
        try:
            subprocess.Popen(["xdg-open", LOG_DIR])
        except OSError:
            pass
    tk.Button(row2, text="Open logs", command=open_logs).pack(side="left", padx=2)

    cams = tk.Frame(panel, bg=PANEL)
    cams.pack(fill="x", pady=4)
    ir_cv = tk.Canvas(cams, width=200, height=150, bg="#0a0d11", highlightthickness=1, highlightbackground="#2c3948")
    ir_cv.pack(side="left")
    ptr_cv = tk.Canvas(cams, width=176, height=99, bg="#0b1626", highlightthickness=1, highlightbackground="#2c3948")
    ptr_cv.pack(side="left", padx=6, anchor="n")

    def check(key, text, restart=False):
        var = tk.BooleanVar(value=bool(cfg[key]))

        def changed():
            cfg[key] = bool(var.get())
            save_config(cfg)
            log.event("APP", "SETTING", "%s=%s" % (key, cfg[key]))
            if restart:
                app.restart()
        tk.Checkbutton(panel, text=text, variable=var, command=changed, fg=FG, bg=PANEL, selectcolor=BG, activebackground=PANEL,
                       activeforeground=FG, anchor="w").pack(fill="x")

    def scale(key, text, lo, hi, res):
        tk.Label(panel, text=text, fg=DIM, bg=PANEL, anchor="w").pack(fill="x")
        var = tk.DoubleVar(value=cfg[key])

        def changed(_=None):
            cfg[key] = float(var.get())
            save_config(cfg)
        tk.Scale(panel, from_=lo, to=hi, resolution=res, orient="horizontal", variable=var, command=changed, bg=PANEL, fg=FG,
                 troughcolor=BG, highlightthickness=0).pack(fill="x")

    check("invert_yaw", "Invert yaw")
    check("invert_roll", "Invert roll")
    check("invert_pitch", "Invert pitch")
    check("invert_accel_xy", "Invert accelerometer X/Y")
    check("use_accel_position", "Track motion without IR (arm arc)")
    check("yaw_ir_assist", "Correct yaw with IR")
    check("nunchuk_direct", "Direct Nunchuk (no MotionPlus: the remote does not use the gyro)", restart=True)
    check("rest_fix", "Auto-zero the gyro when steadily at rest (experimental)")
    check("show_trail", "Trail")
    check("show_frustum", "IR view cone")
    check("show_axes", "Remote axes")
    scale("arm_length", "Arm length (m)", 0.0, 1.0, 0.05)
    scale("pointer_half_deg", "Pointer range (half-width in degrees)", 4, 25, 1)
    scale("accel_gain", "Accelerometer correction", 0.2, 5.0, 0.1)
    logtail = tk.Label(panel, text="", font=("DejaVu Sans Mono", 8), fg="#7e92a8", bg=PANEL, anchor="nw", justify="left", wraplength=380)
    logtail.pack(fill="x", pady=4)

    surf = sim3d.TkSurface(canvas)
    scene = sim3d.Scene()
    drag = {"x": 0, "y": 0, "on": False}

    def press(e):
        drag.update(x=e.x, y=e.y, on=True)

    def motion(e):
        if drag["on"]:
            cam.az -= (e.x - drag["x"]) * 0.008
            cam.el = max(-1.4, min(1.4, cam.el + (e.y - drag["y"]) * 0.008))
            drag.update(x=e.x, y=e.y)

    def wheel(e):
        up = getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4
        cam.dist = max(0.4, min(15.0, cam.dist * (0.9 if up else 1.1)))

    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<ButtonRelease-1>", lambda e: drag.update(on=False))
    canvas.bind("<B1-Motion>", motion)
    canvas.bind("<MouseWheel>", wheel)
    canvas.bind("<Button-4>", wheel)
    canvas.bind("<Button-5>", wheel)

    def key(e):
        if root.focus_get() is note:
            return
        k = (e.keysym or "").lower()
        if k == "c":
            app.each(lambda s: s.request_calibrate())
        elif k == "r":
            app.each(lambda s: s.request_recenter())
        elif k == "f2":
            note.focus_set()
    root.bind("<Key>", key)

    state = {"last_text": 0.0}

    def card_text(slot, s):
        yaw, pitch, roll = sc.euler(s["q"])
        gy = s["gyro"]
        acc = s["acc"]
        lines = ["Remote %d  %s  bat %s%%  %.0f Hz  MP %s%s" % (slot + 1, s["status"], s["battery"] if s["battery"] >= 0 else "?", s["rate"],
                                                               "OK" if s["mp_active"] else "NO DATA", "" if s["slow"] else " (fast)"),
                 "yaw %6.1f  pitch %6.1f  roll %6.1f" % (yaw, pitch, roll),
                 "gyro Y%6.0f R%6.0f P%6.0f deg/s" % gy,
                 "accel %+.2f %+.2f %+.2f |a|=%.2f g%s" % (acc[0], acc[1], acc[2], sc.vlen(acc), "  CLIPPING" if s["clip"] else ""),
                 "pos %+.2f %+.2f %+.2f m [%s]" % (s["pos"][0], s["pos"][1], s["pos"][2], "IR" if s["ir_visible"] else ("estimated" if s["ir_ever"] else "no data"))]
        if s["ptr_valid"]:
            lines.append("pointer (%+.2f , %+.2f) %s" % (s["nx"], s["ny"], "[estimated]" if s["ptr_est"] else "[IR]"))
        else:
            lines.append("pointer: aim at the bar")
        if s["gesture"] and s["gesture_age"] < 8:
            lines.append("gesture: %s (%.1f s ago)" % (s["gesture"], s["gesture_age"]))
        if s["nun_connected"]:
            n = s["nun"]
            lines.append("nunchuk: stick (%+.2f,%+.2f) %s%s" % (n["x"], n["y"], "[C]" if n["c"] else "", "[Z]" if n["z"] else ""))
        if s["calib"] >= 0:
            lines.append("CALIBRATING... %.0f%% (keep the remote still)" % (s["calib"] * 100))
        names = [wl.BUTTON_NAMES[b] for b in wl.BUTTON_NAMES if s["buttons"] & b]
        lines.append("buttons: " + (", ".join(names) if names else "-"))
        return "\n".join(lines)

    def tick():
        try:
            w, h = max(200, canvas.winfo_width()), max(200, canvas.winfo_height())
            snaps = app.snapshots()
            scene.render(surf, w, h, cam, snaps, cfg, "Drag: rotate   Wheel: zoom   C: calibrate   R: recenter yaw   F2: note")
            now = time.monotonic()
            if now - state["last_text"] > 0.12:
                state["last_text"] = now
                mgr = app.mgr
                msgs = ["Nintendo HID interfaces: %d   Remotes: %d" % (mgr.hid_seen if mgr else 0, len(snaps))]
                if mgr and mgr.problems:
                    msgs.append(mgr.problems[0] + "  (run install-udev.sh)")
                if mgr and mgr.hid_seen == 0:
                    msgs.append("Dolphin Bar not detected (mode 4).")
                info.config(text="\n".join(msgs))
                for lb in cards:
                    lb.pack_forget()
                ir_cv.delete("all")
                ptr_cv.delete("all")
                ptr_cv.create_rectangle(1, 1, 175, 98, outline="#3c6496")
                ptr_cv.create_line(88, 0, 88, 99, fill="#1e3250")
                ptr_cv.create_line(0, 50, 176, 50, fill="#1e3250")
                for slot, s in snaps:
                    cards[slot].config(text=card_text(slot, s))
                    cards[slot].pack(fill="x", pady=2, before=row)
                    col = sim3d.hexcolor(sim3d.SLOT_COLORS[slot])
                    for (x, y) in s["dots"]:
                        ir_cv.create_oval(x / 1024 * 200 - 3, 150 - y / 768 * 150 - 3, x / 1024 * 200 + 3, 150 - y / 768 * 150 + 3, fill=col, outline="")
                    if s["ptr_valid"]:
                        px = (max(-1.4, min(1.4, s["nx"])) * 0.5 + 0.5) * 176
                        py = (0.5 - max(-1.4, min(1.4, s["ny"])) * 0.5) * 99
                        ptr_cv.create_oval(px - 5, py - 5, px + 5, py + 5, fill="" if s["ptr_est"] else col, outline=col, width=2)
                logtail.config(text=log.get_tail(6))
        except Exception as e:
            log.event("APP", "ERROR", "window: %r" % e)
        root.after(40, tick)

    def on_close():
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    tick()
    root.mainloop()


def run_headless(app, log):
    print("%s %s without a window (logging to %s). Ctrl+C to quit." % (APP_NAME, VERSION, log.events_path))
    try:
        while True:
            time.sleep(1)
            s = app.snapshots()
            print("remotes=%d %s" % (len(s), " ".join("W%d:%s" % (sl + 1, "IR" if sn["ir_visible"] else "--") for sl, sn in s)))
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("--nogui", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for i in wl.list_wiimote_hidraws():
            print(i, "OK" if os.access(i.path, os.R_OK | os.W_OK) else "NO PERMISSION")
        return 0
    cfg = load_config()
    log = wl.EventLog(LOG_DIR, "wiisim", sc.CSV_HEADER)
    log.event("APP", "APP", "%s %s started. Settings: %s" % (APP_NAME, VERSION, json.dumps(cfg)))
    app = SimApp(cfg, log)
    app.start()
    try:
        if args.nogui:
            run_headless(app, log)
        else:
            try:
                run_gui(app, log, cfg)
            except ImportError:
                print("tkinter is missing (python3-tk package). Continuing without a window.")
                run_headless(app, log)
    finally:
        app.stop()
        save_config(cfg)
        log.event("APP", "APP", "Shutting down")
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
