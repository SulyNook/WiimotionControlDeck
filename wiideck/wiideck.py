#!/usr/bin/env python3
"""
WiiDeck 0.2 - controla la Steam Deck (tambien en Modo Juego) con un Wii Remote Plus a traves de la Dolphin Bar.

  * Puntero IR -> raton virtual            * Agitar -> cambiar de coleccion (L1 / R1)
  * Modos: VERTICAL (apuntando), HORIZONTAL (como un mando de NES; la cruceta hace de stick), NUNCHUK
  * Perfiles: "Menus de Steam" (A = clic) y "Juegos" (A, B... como botones de la Deck)
  * Editor de botones tipo Steam Input: cada boton del mando se asigna a cualquier boton/stick/tecla/clic
  * Giroscopio (MotionPlus) -> servidor DSU (cemuhook) para emuladores de Switch, o -> stick derecho

Cambiar de modo: ventana o 1 + 2 en el mando.   Cambiar de perfil: ventana o + y - a la vez.
Solo libreria estandar de Python 3 (tkinter para la ventana). Opciones:
  --nogui   sin ventana     --mode vertical|horizontal|nunchuk     --profile menus|juego
  --list    mandos hallados --check comprueba permisos y sale
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "common")):
    if os.path.exists(os.path.join(_p, "deckcore.py")):
        sys.path.insert(0, _p)
        break
import wiilink as wl  # noqa: E402
import deckcore as dc  # noqa: E402
from deckcore import (APP_NAME, VERSION, MODES, MODE_TITLES, PROFILES, PROFILE_TITLES, INPUTS, ACTION_GROUPS,  # noqa: E402
                      ACTION_LABELS, POINTER_CHOICES, STICK_CHOICES, DEFAULT_PROFILES)

BG, PANEL, PANEL2, FG, DIM, ACC, OK, BAD, WARN = "#10161d", "#1b2430", "#263445", "#e6edf3", "#8fa3b8", "#3fa9f5", "#4cd964", "#f55a3f", "#ffd60a"

# columnas del editor de botones: (titulo, [entradas])
BIND_COLUMNS = [
    ("Mando", ["Pointer", "A", "B", "One", "Two", "Plus", "Minus", "Home"]),
    ("Cruceta, Nunchuk y gestos", ["Up", "Down", "Left", "Right", "NunStick", "NunC", "NunZ", "ShakeNext", "ShakePrev"]),
]
MODE_HELP = {"vertical": "Mando vertical\napuntando a la pantalla", "horizontal": "Mando horizontal\ncomo un mando de NES",
             "nunchuk": "Mando + Nunchuk\npuntero y palanca"}
PROFILE_HELP = {"menus": "A = clic. Para moverte por\nSteam y sus menus", "juego": "A, B, 1, 2... como botones\nde la Deck, para jugar"}


def value_label(input_name, value):
    if input_name == "Pointer":
        return dict(POINTER_CHOICES).get(value, value)
    if input_name == "NunStick":
        return dict(STICK_CHOICES).get(value, value)
    return ACTION_LABELS.get(value, value or "Nada")


# ----------------------------------------------------------------------------- ventana
def run_gui(svc):
    import tkinter as tk

    ctrl, cfg, mgr, log = svc.ctrl, svc.cfg, svc.mgr, svc.log
    root = tk.Tk()
    root.title("%s %s" % (APP_NAME, VERSION))
    root.configure(bg=BG)
    root.geometry("1280x800")
    F_BIG, F_MID, F_SMALL, F_MONO = ("DejaVu Sans", 22, "bold"), ("DejaVu Sans", 15), ("DejaVu Sans", 12), ("DejaVu Sans Mono", 11)

    def label(parent, text="", font=F_MID, fg=FG, bg=BG, **kw):
        return tk.Label(parent, text=text, font=font, fg=fg, bg=bg, anchor="w", justify="left", **kw)

    def button(parent, text, command, font=F_MID, bg=PANEL, fg=FG, **kw):
        return tk.Button(parent, text=text, font=font, command=command, bg=bg, fg=fg, relief="flat", bd=0,
                         activebackground=ACC, activeforeground="#08111a", **kw)

    # ---- cabecera
    head = tk.Frame(root, bg=BG)
    head.pack(fill="x", padx=24, pady=(14, 0))
    label(head, "WiiDeck  -  Wiimote Plus para la Steam Deck", F_BIG).pack(side="left")
    master = button(head, "", lambda: ctrl.set_enabled(not cfg["enabled"]), font=("DejaVu Sans", 16, "bold"), width=18, height=2)
    master.pack(side="right")
    status = label(root, "", F_MID, DIM)
    status.pack(fill="x", padx=24)
    banner = tk.Label(root, text="", font=F_SMALL, fg=WARN, bg=BG, anchor="w", justify="left", wraplength=1200)
    banner.pack(fill="x", padx=24)

    tabs = tk.Frame(root, bg=BG)
    tabs.pack(fill="x", padx=24, pady=(6, 6))
    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=24)
    pages, tab_buttons = {}, {}

    def show(name):
        for p in pages.values():
            p.pack_forget()
        pages[name].pack(fill="both", expand=True)
        for n, b in tab_buttons.items():
            b.config(bg=ACC if n == name else PANEL, fg="#08111a" if n == name else FG)
        close_picker()

    for key, title in (("inicio", "INICIO"), ("botones", "BOTONES"), ("mov", "MOVIMIENTO")):
        pages[key] = tk.Frame(body, bg=BG)
        b = button(tabs, title, lambda k=key: show(k), font=("DejaVu Sans", 14, "bold"), width=16, height=1)
        b.pack(side="left", padx=(0, 8))
        tab_buttons[key] = b

    # =========================================================== INICIO
    home = pages["inicio"]
    row = tk.Frame(home, bg=BG)
    row.pack(fill="x", pady=(4, 6))
    label(row, "Modo del mando  (1 + 2 en el mando)", F_SMALL, DIM).pack(anchor="w")
    mode_buttons = {}
    mrow = tk.Frame(home, bg=BG)
    mrow.pack(fill="x")
    for m in MODES:
        b = button(mrow, "%s\n%s" % (MODE_TITLES[m].upper(), MODE_HELP[m]), lambda m=m: ctrl.set_mode(m),
                   font=("DejaVu Sans", 15, "bold"), width=24, height=4)
        b.pack(side="left", padx=(0, 10))
        mode_buttons[m] = b
    label(home, "Perfil  (+ y - a la vez en el mando)", F_SMALL, DIM).pack(anchor="w", pady=(8, 0))
    profile_buttons = {}
    prow = tk.Frame(home, bg=BG)
    prow.pack(fill="x")
    for p in PROFILES:
        b = button(prow, "%s\n%s" % (PROFILE_TITLES[p].upper(), PROFILE_HELP[p]), lambda p=p: ctrl.set_profile(p),
                   font=("DejaVu Sans", 14, "bold"), width=28, height=3)
        b.pack(side="left", padx=(0, 10))
        profile_buttons[p] = b
    mid = tk.Frame(home, bg=BG)
    mid.pack(fill="both", expand=True, pady=8)
    remotes = tk.Label(mid, text="", font=F_MONO, fg=FG, bg=PANEL, anchor="nw", justify="left", padx=12, pady=8, width=90, height=6)
    remotes.pack(side="left", fill="y")
    cam = tk.Canvas(mid, width=256, height=192, bg="#0a0d11", highlightthickness=1, highlightbackground="#2c3948")
    cam.pack(side="left", padx=16, anchor="n")
    tail = tk.Label(home, text="", font=("DejaVu Sans Mono", 10), fg="#7e92a8", bg=BG, anchor="nw", justify="left", height=4)
    tail.pack(fill="x")

    # =========================================================== BOTONES (editor tipo Steam Input)
    bp = pages["botones"]
    edit = {"profile": cfg["profile"], "mode": cfg["mode"]}
    top = tk.Frame(bp, bg=BG)
    top.pack(fill="x", pady=(4, 6))
    label(top, "Editando:", F_SMALL, DIM).pack(side="left", padx=(0, 8))
    ep_buttons, em_buttons = {}, {}

    def set_edit(profile=None, mode=None):
        if profile:
            edit["profile"] = profile
        if mode:
            edit["mode"] = mode
        close_picker()
        refresh_bindings(force=True)

    for p in PROFILES:
        b = button(top, PROFILE_TITLES[p], lambda p=p: set_edit(profile=p), font=("DejaVu Sans", 13, "bold"), width=15)
        b.pack(side="left", padx=2)
        ep_buttons[p] = b
    label(top, "   ", F_SMALL).pack(side="left")
    for m in MODES:
        b = button(top, MODE_TITLES[m], lambda m=m: set_edit(mode=m), font=("DejaVu Sans", 13, "bold"), width=11)
        b.pack(side="left", padx=2)
        em_buttons[m] = b
    button(top, "Restaurar este modo", lambda: (ctrl.reset_bindings(edit["mode"], edit["profile"]), refresh_bindings(force=True)),
           font=("DejaVu Sans", 12), width=19).pack(side="right")
    note = label(bp, "", F_SMALL, DIM)
    note.pack(fill="x")

    grid = tk.Frame(bp, bg=BG)
    grid.pack(fill="both", expand=True, pady=(4, 0))
    bind_buttons = {}
    for ci, (title, names) in enumerate(BIND_COLUMNS):
        col = tk.Frame(grid, bg=BG)
        col.pack(side="left", fill="both", expand=True, padx=(0, 16))
        label(col, title.upper(), F_SMALL, ACC).pack(anchor="w", pady=(0, 2))
        for name in names:
            r = tk.Frame(col, bg=BG)
            r.pack(fill="x", pady=2)
            label(r, dict(INPUTS)[name], ("DejaVu Sans", 14), FG, width=20).pack(side="left")
            b = button(r, "", lambda n=name: open_picker(n), font=("DejaVu Sans", 14, "bold"), width=22, height=1, bg=PANEL)
            b.pack(side="left", fill="x", expand=True)
            bind_buttons[name] = b

    picker = {"frame": None}

    def close_picker():
        fr = picker["frame"]
        if fr is not None:
            try:
                fr.destroy()
            except Exception:
                pass
            picker["frame"] = None

    def assign(name, value):
        ctrl.set_binding(name, value, edit["mode"], edit["profile"])
        close_picker()
        refresh_bindings(force=True)

    def open_picker(name):
        close_picker()
        fr = tk.Frame(root, bg=BG)
        fr.place(relx=0, rely=0, relwidth=1, relheight=1)
        fr.lift()
        picker["frame"] = fr
        cur = svc.bindings_view(edit["mode"], edit["profile"])
        current = next((i["value"] for i in cur["inputs"] if i["input"] == name), "none")
        hd = tk.Frame(fr, bg=BG)
        hd.pack(fill="x", padx=24, pady=(14, 6))
        label(hd, "Asignar: %s" % dict(INPUTS)[name], F_BIG).pack(side="left")
        button(hd, "CANCELAR", close_picker, font=("DejaVu Sans", 15, "bold"), width=14, height=2, bg=BAD, fg="#08111a").pack(side="right")
        label(fr, "%s  /  %s      Ahora: %s" % (PROFILE_TITLES[edit["profile"]], MODE_TITLES[edit["mode"]], value_label(name, current)),
              F_SMALL, DIM).pack(fill="x", padx=24)
        if name in ("Pointer", "NunStick"):
            groups = [("Opciones", POINTER_CHOICES if name == "Pointer" else STICK_CHOICES)]
        else:
            groups = ACTION_GROUPS
        area = tk.Frame(fr, bg=BG)
        area.pack(fill="both", expand=True, padx=24, pady=6)
        for gtitle, items in groups:
            label(area, gtitle.upper(), F_SMALL, ACC).pack(anchor="w", pady=(6, 0))
            g = tk.Frame(area, bg=BG)
            g.pack(fill="x")
            for k, (aid, text) in enumerate(items):
                b = button(g, text, lambda a=aid: assign(name, a), font=("DejaVu Sans", 12, "bold"), width=17, height=1,
                           bg=ACC if aid == current else PANEL, fg="#08111a" if aid == current else FG)
                b.grid(row=k // 6, column=k % 6, padx=2, pady=2, sticky="we")

    last_bind = {"key": None}

    def refresh_bindings(force=False):
        view = svc.bindings_view(edit["mode"], edit["profile"])
        key = (edit["profile"], edit["mode"], tuple(i["value"] for i in view["inputs"]), ctrl.profile, ctrl.mode)
        if not force and key == last_bind["key"]:
            return
        last_bind["key"] = key
        defaults = DEFAULT_PROFILES[edit["profile"]][edit["mode"]]
        for i in view["inputs"]:
            b = bind_buttons.get(i["input"])
            if b is None:
                continue
            changed = i["value"] != defaults.get(i["input"], "none")
            b.config(text=value_label(i["input"], i["value"]) + ("  *" if changed else ""), bg=PANEL2 if changed else PANEL,
                     fg=WARN if changed else FG)
        for p, b in ep_buttons.items():
            b.config(bg=ACC if p == edit["profile"] else PANEL, fg="#08111a" if p == edit["profile"] else FG)
        for m, b in em_buttons.items():
            b.config(bg=ACC if m == edit["mode"] else PANEL, fg="#08111a" if m == edit["mode"] else FG)
        live = "  (es lo que esta activo ahora)" if (edit["profile"], edit["mode"]) == (ctrl.profile, ctrl.mode) else ""
        note.config(text="Toca un boton para cambiar lo que hace.  * = distinto de fabrica.%s" % live)

    # =========================================================== MOVIMIENTO
    mv = pages["mov"]

    def slider(parent, text, key, lo, hi, res):
        fr = tk.Frame(parent, bg=BG)
        fr.pack(side="left", padx=(0, 18))
        label(fr, text, F_SMALL, DIM).pack(anchor="w")
        var = tk.DoubleVar(value=cfg[key])

        def changed(_=None):
            v = float(var.get())
            svc.set_option(key, int(v) if key == "shake_reversals" else v)
        tk.Scale(fr, from_=lo, to=hi, resolution=res, orient="horizontal", length=270, variable=var, command=changed,
                 bg=BG, fg=FG, troughcolor=PANEL, highlightthickness=0, font=("DejaVu Sans", 11)).pack()

    def checks(parent, items):
        fr = tk.Frame(parent, bg=BG)
        fr.pack(fill="x", pady=2)
        for key, text in items:
            v = tk.BooleanVar(value=cfg[key])
            tk.Checkbutton(fr, text=text, variable=v, command=lambda k=key, v=v: svc.set_option(k, bool(v.get())),
                           font=("DejaVu Sans", 13), fg=FG, bg=BG, selectcolor=PANEL, activebackground=BG,
                           activeforeground=FG).pack(side="left", padx=(0, 18))

    label(mv, "PUNTERO Y SACUDIDA", F_SMALL, ACC).pack(anchor="w", pady=(4, 0))
    sl = tk.Frame(mv, bg=BG)
    sl.pack(fill="x")
    slider(sl, "Velocidad del puntero (px/grado)", "px_per_deg", 10, 150, 1)
    slider(sl, "Suavizado (menos = mas suave)", "smooth_min_cut", 0.3, 6, 0.1)
    slider(sl, "Fuerza de la sacudida (g, menos = mas facil)", "shake_threshold", 0.3, 2.5, 0.05)
    checks(mv, (("shake_enabled", "Agitar = cambiar de coleccion"), ("invert_x", "Invertir X"), ("invert_y", "Invertir Y")))

    label(mv, "GIROSCOPIO (MotionPlus)", F_SMALL, ACC).pack(anchor="w", pady=(14, 0))
    checks(mv, (("gyro_enabled", "Giroscopio activo"), ("dsu_enabled", "Enviar movimiento a emuladores (DSU)"),
                ("gyro_stick", "Giroscopio -> stick derecho")))
    sl2 = tk.Frame(mv, bg=BG)
    sl2.pack(fill="x", pady=(4, 0))
    slider(sl2, "Sensibilidad del giroscopio -> stick", "gyro_stick_gain", 0.3, 4.0, 0.1)
    cal = tk.Frame(sl2, bg=BG)
    cal.pack(side="left", padx=10, anchor="s")
    button(cal, "CALIBRAR GIROSCOPIO\n(deja el mando quieto)", ctrl.calibrate_gyro, font=("DejaVu Sans", 13, "bold"), width=24, height=2).pack()
    dsu_lbl = tk.Label(mv, text="", font=F_SMALL, fg=FG, bg=PANEL, anchor="nw", justify="left", padx=12, pady=8)
    dsu_lbl.pack(fill="x", pady=(12, 0))
    label(mv, "Para jugar a la Switch con el movimiento del mando: en el emulador (Ryujinx, Yuzu y derivados, Cemu, Dolphin...) activa\n"
              "'Movimiento' / 'DSU' y pon servidor 127.0.0.1 puerto 26760. El Nunchuk y el giroscopio no se pueden usar a la vez.",
          F_SMALL, DIM).pack(fill="x", pady=(8, 0))

    # =========================================================== refresco
    def refresh():
        try:
            st = svc.status()
            ok = st["devices_ok"]
            status.config(text="Dispositivos virtuales: %s    |    hidraw: %d    |    Modo: %s    |    Perfil: %s" % (
                "OK" if ok else "ERROR", st["hid_seen"], MODE_TITLES[st["mode"]], PROFILE_TITLES[st["profile"]]), fg=OK if ok else BAD)
            msgs = list(st["problems"])
            if st["hid_seen"] == 0:
                msgs.append("No se ve la Dolphin Bar (modo 4, 057e:0306). Conectala y enciende el mando.")
            banner.config(text="  ".join(msgs[:2]))
            master.config(text="WIIDECK: ACTIVO\n(toca para apagar)" if st["enabled"] else "WIIDECK: APAGADO\n(toca para activar)",
                          bg=OK if st["enabled"] else BAD, fg="#08111a")
            for m, b in mode_buttons.items():
                b.config(bg=ACC if m == st["mode"] else PANEL, fg="#08111a" if m == st["mode"] else FG)
            for p, b in profile_buttons.items():
                b.config(bg=ACC if p == st["profile"] else PANEL, fg="#08111a" if p == st["profile"] else FG)
            lines = []
            cam.delete("all")
            for r in st["remotes"]:
                lines.append("Mando %d  %-16s bateria %3s%%  IR %d  Nunchuk: %s  Giroscopio: %s%s  %s" % (
                    r["slot"], r["status"][:16], r["battery"] if r["battery"] >= 0 else "?", r["ir"],
                    "si" if r["nunchuk"] else "no", "si" if r["gyro"] else "no", "  (principal)" if r["owner"] else "", r["last"]))
            owner = ctrl.states.get(ctrl.owner_slot)
            if owner:
                for (x, y) in owner.last_ir:
                    cam.create_oval(x / 4 - 4, 192 - y / 4 - 4, x / 4 + 4, 192 - y / 4 + 4, fill=ACC, outline="")
            remotes.config(text="\n".join(lines) if lines else "Ningun mando conectado todavia.\nPulsa un boton del mando.")
            tail.config(text=log.get_tail(4))
            dsu_lbl.config(text="Servidor DSU: %s    Clientes conectados: %d    Puerto: %d" % (
                "ACTIVO" if (st["dsu_enabled"] and svc.dsu.sock) else "apagado", st["dsu_clients"], st["dsu_port"]))
            refresh_bindings()
        except Exception as e:  # la ventana nunca debe romper el control
            log.event("APP", "ERROR", "ventana: %r" % e)
        root.after(150, refresh)

    def on_close():
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    show("inicio")
    refresh()
    root.mainloop()


def show_message(text):
    print(text, file=sys.stderr)
    try:
        import tkinter as tk
        r = tk.Tk()
        r.title(APP_NAME)
        r.configure(bg=BG)
        r.geometry("900x300")
        tk.Label(r, text=text, font=("DejaVu Sans", 16), fg=WARN, bg=BG, wraplength=860, justify="left").pack(expand=True, padx=20)
        r.after(8000, r.destroy)
        r.mainloop()
    except Exception:
        pass


def run_headless(svc):
    print("%s %s sin ventana. Ctrl+C para salir." % (APP_NAME, VERSION))
    last = ""
    try:
        while True:
            st = svc.status()
            s = "modo=%s perfil=%s mandos=%d %s" % (st["mode"], st["profile"], len(st["remotes"]), "; ".join(st["problems"]))
            if s != last:
                print(s)
                last = s
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


def main():
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("--nogui", action="store_true")
    ap.add_argument("--mode", choices=MODES)
    ap.add_argument("--profile", choices=PROFILES)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if args.list or args.check:
        infos = wl.list_wiimote_hidraws()
        if not infos:
            print("No se ve ningun nodo hidraw de Wii Remote / Dolphin Bar (057e:0306/0330).")
        for i in infos:
            print(i, "OK" if os.access(i.path, os.R_OK | os.W_OK) else "SIN PERMISO")
        ui = any(os.access(p, os.W_OK) for p in dc.UINPUT_PATHS)
        print("uinput:", "OK" if ui else "SIN PERMISO (/dev/uinput)")
        return 0

    svc = dc.DeckService()
    overrides = {k: v for k, v in (("mode", args.mode), ("profile", args.profile)) if v}
    try:
        svc.start(overrides)
    except dc.AlreadyRunning as e:
        show_message(str(e))
        return 2
    try:
        if args.nogui:
            run_headless(svc)
        else:
            try:
                run_gui(svc)
            except ImportError:
                print("Falta tkinter (paquete python3-tk). Se continua sin ventana.")
                run_headless(svc)
    finally:
        svc.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
