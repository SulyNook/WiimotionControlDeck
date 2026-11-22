#!/usr/bin/env python3
"""
WiiDeck 0.4 - controla la Steam Deck (tambien en Modo Juego) con un Wii Remote Plus a traves de la Dolphin Bar.

  * Puntero IR -> raton virtual            * Agitar a izquierda/derecha/arriba/abajo -> lo que quieras (de fabrica L1 / R1)
  * Modos: VERTICAL (apuntando), HORIZONTAL (como un mando de NES; la cruceta hace de stick), NUNCHUK
  * Perfiles: "Menus de Steam" (A = clic), "Juegos" (A, B... como botones de la Deck) y los tuyos (empiezan en blanco)
  * Editor de botones tipo Steam Input: cada boton del mando se asigna a uno o VARIOS botones/stick/tecla/clic (A + B ...)
  * Giroscopio (MotionPlus) -> servidor DSU (cemuhook) para emuladores de Switch, o -> stick derecho

Cambiar de modo: ventana o 1 + 2 en el mando.   Cambiar de perfil (tambien los tuyos): ventana o + y - a la vez.
Mantener 2 s:  Abajo + Plus = puntero IR si/no      Home + Plus = abrir el menu ... de Steam (QAM)
Solo libreria estandar de Python 3 (tkinter para la ventana). Opciones:
  --nogui   sin ventana     --mode vertical|horizontal|nunchuk     --profile menus|juego|<tuyo>
  --list    mandos hallados --check comprueba permisos y sale
"""
import argparse
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.join(HERE, "..", "common")):
    if os.path.exists(os.path.join(_p, "deckcore.py")):
        sys.path.insert(0, _p)
        break
import wiilink as wl  # noqa: E402
import deckcore as dc  # noqa: E402
from deckcore import (APP_NAME, VERSION, MODES, MODE_TITLES, INPUTS, ACTION_GROUPS, ACTION_LABELS,  # noqa: E402
                      POINTER_CHOICES, STICK_CHOICES, MAX_COMBO, split_action, join_actions, profile_ids, profile_title,
                      default_bindings, BUILTIN_PROFILES, MAX_CUSTOM_PROFILES)

BG, PANEL, PANEL2, FG, DIM, ACC, OK, BAD, WARN = "#10161d", "#1b2430", "#263445", "#e6edf3", "#8fa3b8", "#3fa9f5", "#4cd964", "#f55a3f", "#ffd60a"

# columnas del editor de botones: (titulo, [entradas])
BIND_COLUMNS = [
    ("Mando", ["Pointer", "A", "B", "One", "Two", "Plus", "Minus", "Home"]),
    ("Cruceta y Nunchuk", ["Up", "Down", "Left", "Right", "NunStick", "NunC", "NunZ", "NunShake"]),
    ("Agitar el mando", ["ShakeLeft", "ShakeRight", "ShakeUp", "ShakeDown"]),
]
SHORT = {"Pointer": "Puntero IR", "ShakeLeft": "Hacia la izquierda", "ShakeRight": "Hacia la derecha", "ShakeUp": "Hacia arriba",
         "ShakeDown": "Hacia abajo"}
MODE_HELP = {"vertical": "Mando vertical\napuntando a la pantalla", "horizontal": "Mando horizontal\ncomo un mando de NES",
             "nunchuk": "Mando + Nunchuk\npuntero y palanca"}
AXIS_NAMES = ("Acel X", "Acel Y", "Acel Z", "Giro X", "Giro Y", "Giro Z")


def value_label(input_name, value):
    if input_name == "Pointer":
        return dict(POINTER_CHOICES).get(value, value)
    if input_name == "NunStick":
        return dict(STICK_CHOICES).get(value, value)
    parts = split_action(value)
    return " + ".join(ACTION_LABELS.get(p, p) for p in parts) if parts else "Nada"


# ----------------------------------------------------------------------------- ventana
def run_gui(svc):
    import tkinter as tk

    ctrl, cfg, mgr, log = svc.ctrl, svc.cfg, svc.mgr, svc.log

    def rebind():
        """Tras un reinicio del servicio (boton o despertar de la suspension) controlador y config son objetos nuevos."""
        nonlocal ctrl, cfg, mgr, log
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

    def clip(text, n):
        return text if len(text) <= n else text[:n - 1] + "…"

    def sel(b, on):
        b.config(bg=ACC if on else PANEL, fg="#08111a" if on else FG)

    # ---- cabecera
    head = tk.Frame(root, bg=BG)
    head.pack(fill="x", padx=24, pady=(10, 0))
    label(head, "WiiDeck  -  Wiimote Plus para la Steam Deck", F_BIG).pack(side="left")
    master = button(head, "", lambda: ctrl.set_enabled(not cfg["enabled"]), font=("DejaVu Sans", 16, "bold"), width=18, height=2)
    master.pack(side="right")
    ir_btn = button(head, "", lambda: svc.set_option("ir_enabled", not cfg["ir_enabled"]), font=("DejaVu Sans", 12, "bold"), width=14, height=2)
    ir_btn.pack(side="right", padx=8)
    button(head, "REINICIAR\nTODO", lambda: threading.Thread(target=svc.restart, daemon=True).start(),
           font=("DejaVu Sans", 12, "bold"), width=10, height=2).pack(side="right")
    status = label(root, "", F_SMALL, DIM)
    status.pack(fill="x", padx=24)
    banner = tk.Label(root, text="", font=F_SMALL, fg=WARN, bg=BG, anchor="w", justify="left", wraplength=1200)
    banner.pack(fill="x", padx=24)

    tabs = tk.Frame(root, bg=BG)
    tabs.pack(fill="x", padx=24, pady=(4, 4))
    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=24)
    pages, tab_buttons = {}, {}

    # ---- ventanas superpuestas (selector de acciones, nombre de perfil)
    overlay = {"frame": None}

    def close_overlay():
        fr = overlay["frame"]
        if fr is not None:
            try:
                fr.destroy()
            except Exception:
                pass
            overlay["frame"] = None
        try:
            root.unbind("<Key>")
        except Exception:
            pass

    def new_overlay():
        close_overlay()
        fr = tk.Frame(root, bg=BG)
        fr.place(relx=0, rely=0, relwidth=1, relheight=1)
        fr.lift()
        overlay["frame"] = fr
        return fr

    def show(name):
        for p in pages.values():
            p.pack_forget()
        pages[name].pack(fill="both", expand=True)
        for n, b in tab_buttons.items():
            sel(b, n == name)
        close_overlay()

    for key, title in (("inicio", "INICIO"), ("botones", "BOTONES"), ("mov", "MOVIMIENTO")):
        pages[key] = tk.Frame(body, bg=BG)
        b = button(tabs, title, lambda k=key: show(k), font=("DejaVu Sans", 14, "bold"), width=16, height=1)
        b.pack(side="left", padx=(0, 8))
        tab_buttons[key] = b

    # =========================================================== INICIO
    home = pages["inicio"]
    label(home, "Modo del mando  (1 + 2 en el mando)", F_SMALL, DIM).pack(anchor="w", pady=(4, 0))
    mode_buttons = {}
    mrow = tk.Frame(home, bg=BG)
    mrow.pack(fill="x")
    for m in MODES:
        b = button(mrow, "%s\n%s" % (MODE_TITLES[m].upper(), MODE_HELP[m]), lambda m=m: ctrl.set_mode(m),
                   font=("DejaVu Sans", 14, "bold"), width=24, height=3)
        b.pack(side="left", padx=(0, 10))
        mode_buttons[m] = b
    label(home, "Perfil  (+ y - a la vez en el mando)", F_SMALL, DIM).pack(anchor="w", pady=(8, 0))
    prow = tk.Frame(home, bg=BG)
    prow.pack(fill="x")
    profile_buttons = {}
    label(home, "Acceso rapido: perfiles por los que rotan + y - en el mando (toca para incluir o quitar)", F_SMALL, DIM).pack(anchor="w", pady=(4, 0))
    qrow = tk.Frame(home, bg=BG)
    qrow.pack(fill="x")
    qstate = {"sig": None, "widgets": []}
    dyn = {"home": [], "edit": [], "sig": None}
    mid = tk.Frame(home, bg=BG)
    mid.pack(fill="both", expand=True, pady=6)
    remotes = tk.Label(mid, text="", font=F_MONO, fg=FG, bg=PANEL, anchor="nw", justify="left", padx=12, pady=8, width=90, height=5)
    remotes.pack(side="left", fill="y")
    cam = tk.Canvas(mid, width=256, height=192, bg="#0a0d11", highlightthickness=1, highlightbackground="#2c3948")
    cam.pack(side="left", padx=16, anchor="n")
    tail = tk.Label(home, text="", font=("DejaVu Sans Mono", 10), fg="#7e92a8", bg=BG, anchor="nw", justify="left", height=3)
    tail.pack(fill="x")
    label(home, "Mantener 2 s en el mando:  Abajo + Plus = puntero IR si/no     Home + Plus = abrir el menu ... de Steam", ("DejaVu Sans", 11),
          DIM).pack(fill="x")

    # =========================================================== BOTONES (editor tipo Steam Input)
    bp = pages["botones"]
    edit = {"profile": cfg["profile"], "mode": cfg["mode"], "confirm": None}
    drafts = {}          # (perfil, modo, entrada) -> valor SIN aplicar: se acumulan y se guardan juntos con APLICAR
    row1 = tk.Frame(bp, bg=BG)
    row1.pack(fill="x", pady=(2, 2))
    row2 = tk.Frame(bp, bg=BG)
    row2.pack(fill="x", pady=(0, 2))
    label(row2, "Modo:", F_SMALL, DIM).pack(side="left", padx=(0, 8))
    em_buttons = {}
    for m in MODES:
        b = button(row2, MODE_TITLES[m], lambda m=m: set_edit(mode=m), font=("DejaVu Sans", 12, "bold"), width=11)
        b.pack(side="left", padx=2)
        em_buttons[m] = b
    button(row2, "Restaurar este modo", lambda: restore_draft(), font=("DejaVu Sans", 12), width=19).pack(side="right")
    del_btn = button(row2, "Borrar perfil", lambda: delete_profile(), font=("DejaVu Sans", 12), width=17, fg=BAD)
    note = label(bp, "", F_SMALL, DIM)
    note.pack(fill="x")
    bar = tk.Frame(bp, bg=PANEL)
    bar.pack(side="bottom", fill="x", pady=(4, 2))
    pend_lbl = tk.Label(bar, text="", font=("DejaVu Sans", 13, "bold"), fg=FG, bg=PANEL, anchor="w", padx=12)
    pend_lbl.pack(side="left")
    apply_btn = button(bar, "APLICAR", lambda: apply_drafts(), font=("DejaVu Sans", 14, "bold"), width=16, height=1, bg=OK, fg="#08111a")
    apply_btn.pack(side="right", padx=6, pady=4)
    discard_btn = button(bar, "DESCARTAR", lambda: discard_drafts(), font=("DejaVu Sans", 12, "bold"), width=12, height=1)
    discard_btn.pack(side="right", padx=6, pady=4)

    def apply_drafts():
        if not drafts:
            return
        changes = [(p, m, n, v) for (p, m, n), v in drafts.items()]
        if ctrl.apply_bindings(changes):
            drafts.clear()
        refresh_bindings(force=True)

    def discard_drafts():
        drafts.clear()
        close_overlay()
        refresh_bindings(force=True)

    def restore_draft():
        """'Restaurar este modo' tambien es un cambio pendiente: se aplica con APLICAR."""
        saved = {i["input"]: i["value"] for i in svc.bindings_view(edit["mode"], edit["profile"])["inputs"]}
        for name, dv in default_bindings(edit["profile"], edit["mode"]).items():
            if saved.get(name) != dv:
                drafts[(edit["profile"], edit["mode"], name)] = dv
            else:
                drafts.pop((edit["profile"], edit["mode"], name), None)
        refresh_bindings(force=True)

    def set_edit(profile=None, mode=None):
        if profile:
            edit["profile"] = profile
        if mode:
            edit["mode"] = mode
        edit["confirm"] = None
        close_overlay()
        refresh_bindings(force=True)

    def delete_profile():
        if edit["profile"] in BUILTIN_PROFILES:
            return
        if edit["confirm"] != edit["profile"]:
            edit["confirm"] = edit["profile"]
            del_btn.config(text="¿SEGURO? OTRA VEZ")
            return
        for k in [k for k in drafts if k[0] == edit["profile"]]:
            del drafts[k]
        ctrl.delete_profile(edit["profile"])
        edit["profile"], edit["confirm"] = "menus", None
        refresh_bindings(force=True)

    grid = tk.Frame(bp, bg=BG)
    grid.pack(fill="both", expand=True, pady=(2, 0))
    bind_buttons = {}
    labels_by_input = dict(INPUTS)
    for title, names in BIND_COLUMNS:
        col = tk.Frame(grid, bg=BG)
        col.pack(side="left", fill="both", expand=True, padx=(0, 12), anchor="n")
        label(col, title.upper(), F_SMALL, ACC).pack(anchor="w", pady=(0, 2))
        for name in names:
            r = tk.Frame(col, bg=BG)
            r.pack(fill="x", pady=2)
            label(r, SHORT.get(name, labels_by_input[name]), ("DejaVu Sans", 12), FG, width=17).pack(side="left")
            b = button(r, "", lambda n=name: open_picker(n), font=("DejaVu Sans", 12, "bold"), width=16, height=1, bg=PANEL)
            b.pack(side="left", fill="x", expand=True)
            bind_buttons[name] = b

    # ---- selector de acciones con huecos "+"
    def saved_value(name, profile=None, mode=None):
        view = svc.bindings_view(mode or edit["mode"], profile or edit["profile"])
        return next((i["value"] for i in view["inputs"] if i["input"] == name), "none")

    def assign(name, value, slot=0):
        """No guarda: apunta el cambio como borrador (se aplica con APLICAR)."""
        key = (edit["profile"], edit["mode"], name)
        if value == saved_value(name):
            drafts.pop(key, None)
        else:
            drafts[key] = value
        refresh_bindings(force=True)

    def current_value(name):
        return drafts.get((edit["profile"], edit["mode"], name), saved_value(name))

    def open_picker(name, slot=0):
        fr = new_overlay()
        value = current_value(name)
        simple = name in ("Pointer", "NunStick")
        parts = [] if simple else split_action(value)
        hd = tk.Frame(fr, bg=BG)
        hd.pack(fill="x", padx=24, pady=(10, 4))
        label(hd, "Asignar: %s" % SHORT.get(name, labels_by_input[name]), F_BIG).pack(side="left")
        button(hd, "LISTO", close_overlay, font=("DejaVu Sans", 15, "bold"), width=12, height=2, bg=OK, fg="#08111a").pack(side="right")
        label(fr, "%s  /  %s" % (profile_title(cfg, edit["profile"]), MODE_TITLES[edit["mode"]]), F_SMALL, DIM).pack(fill="x", padx=24)
        if simple:
            groups = [("Opciones", POINTER_CHOICES if name == "Pointer" else STICK_CHOICES)]
            current = value
        else:
            # huecos: A [+] B [+] ... el ultimo "+" siempre libre para sumar otro boton (hasta MAX_COMBO)
            slot = min(slot, len(parts))
            sl = tk.Frame(fr, bg=BG)
            sl.pack(fill="x", padx=24, pady=(8, 2))
            label(sl, "Botones a la vez:", F_SMALL, DIM).pack(side="left", padx=(0, 8))
            shown = max(len(parts), 1)
            for k in range(shown):
                text = ACTION_LABELS.get(parts[k], parts[k]) if k < len(parts) else "(vacio)"
                b = button(sl, text, lambda k=k: open_picker(name, k), font=("DejaVu Sans", 13, "bold"), width=14, height=2)
                sel(b, k == slot)
                b.pack(side="left", padx=2)
                if k < len(parts) - 1 or (k == len(parts) - 1 and len(parts) < MAX_COMBO):
                    label(sl, "+", F_BIG).pack(side="left", padx=2)
            if parts and len(parts) < MAX_COMBO:
                b = button(sl, "+  añadir", lambda: open_picker(name, len(parts)), font=("DejaVu Sans", 13, "bold"), width=14, height=2)
                sel(b, slot == len(parts))
                b.pack(side="left", padx=2)
            if slot < len(parts):
                button(sl, "Quitar este", lambda: assign_slot(name, parts, slot, "none"), font=("DejaVu Sans", 12), width=12, height=2,
                       fg=BAD).pack(side="right")
            groups = ACTION_GROUPS
            current = parts[slot] if slot < len(parts) else None
        area = tk.Frame(fr, bg=BG)
        area.pack(fill="both", expand=True, padx=24, pady=4)
        for gtitle, items in groups:
            label(area, gtitle.upper(), F_SMALL, ACC).pack(anchor="w", pady=(4, 0))
            g = tk.Frame(area, bg=BG)
            g.pack(fill="x")
            for k, (aid, text) in enumerate(items):
                if simple:
                    cmd = lambda a=aid: (assign(name, a), close_overlay())
                else:
                    cmd = lambda a=aid: assign_slot(name, parts, slot, a)
                b = button(g, text, cmd, font=("DejaVu Sans", 12, "bold"), width=17, height=1)
                sel(b, aid == current)
                b.grid(row=k // 6, column=k % 6, padx=2, pady=2, sticky="we")

    def assign_slot(name, parts, slot, action):
        new = list(parts)
        if slot < len(new):
            new[slot] = action
        else:
            new.append(action)
        assign(name, join_actions(new))
        open_picker(name, slot)

    # ---- perfiles nuevos: nombre con teclado en pantalla (o el del teclado fisico)
    def open_name_dialog(text="", upper=False):
        fr = new_overlay()
        hd = tk.Frame(fr, bg=BG)
        hd.pack(fill="x", padx=24, pady=(12, 4))
        label(hd, "Nuevo perfil", F_BIG).pack(side="left")
        button(hd, "CANCELAR", close_overlay, font=("DejaVu Sans", 15, "bold"), width=12, height=2, bg=BAD, fg="#08111a").pack(side="right")
        label(fr, "Empieza en blanco: todos los botones en 'Nada'. Ponle nombre y luego asigna lo que quieras en BOTONES.", F_SMALL, DIM).pack(
            fill="x", padx=24)
        tk.Label(fr, text=(text or "") + "_", font=("DejaVu Sans", 26, "bold"), fg=FG, bg=PANEL, anchor="w", padx=14, pady=10).pack(
            fill="x", padx=24, pady=10)

        def create():
            pid = ctrl.create_profile(text)
            if pid:
                edit["profile"], edit["confirm"] = pid, None
                close_overlay()
                show("botones")
                refresh_bindings(force=True)

        def redraw(t=None, u=None):
            open_name_dialog(text if t is None else t, upper if u is None else u)

        kb = tk.Frame(fr, bg=BG)
        kb.pack(padx=24)
        for ri, keys in enumerate(("1234567890", "qwertyuiop", "asdfghjklñ", "zxcvbnm-_.")):
            for ci, ch in enumerate(keys):
                c2 = ch.upper() if upper else ch
                button(kb, c2, lambda c=c2: redraw((text + c)[:24]), font=("DejaVu Sans", 18, "bold"), width=4, height=1).grid(
                    row=ri, column=ci, padx=3, pady=3)
        bt = tk.Frame(fr, bg=BG)
        bt.pack(pady=8)
        button(bt, "MAYUS", lambda: redraw(u=not upper), font=("DejaVu Sans", 15, "bold"), width=10, height=2, bg=ACC if upper else PANEL).pack(side="left", padx=4)
        button(bt, "ESPACIO", lambda: redraw((text + " ")[:24]), font=("DejaVu Sans", 15, "bold"), width=14, height=2).pack(side="left", padx=4)
        button(bt, "BORRAR", lambda: redraw(text[:-1]), font=("DejaVu Sans", 15, "bold"), width=10, height=2).pack(side="left", padx=4)
        button(bt, "CREAR PERFIL", create, font=("DejaVu Sans", 15, "bold"), width=16, height=2, bg=OK, fg="#08111a").pack(side="left", padx=4)

        def on_key(e):
            k = getattr(e, "keysym", "")
            ch = getattr(e, "char", "")
            if k == "BackSpace":
                redraw(text[:-1])
            elif k == "Return":
                create()
            elif k == "Escape":
                close_overlay()
            elif ch and ch.isprintable():
                redraw((text + ch)[:24])
        root.bind("<Key>", on_key)

    def sync_profiles(st):
        """Reconstruye los botones de perfil cuando se crea o borra alguno."""
        sig = tuple((p["id"], p["title"]) for p in st["profiles"])
        if sig == dyn["sig"]:
            return
        dyn["sig"] = sig
        for w in dyn["home"] + dyn["edit"]:
            try:
                w.destroy()
            except Exception:
                pass
        dyn["home"], dyn["edit"] = [], []
        profile_buttons.clear()
        lb = label(row1, "Perfil:", F_SMALL, DIM)
        lb.pack(side="left", padx=(0, 8))
        dyn["edit"].append(lb)
        for i, p in enumerate(st["profiles"]):
            b = button(prow, clip(p["title"].upper(), 17), lambda pid=p["id"]: ctrl.set_profile(pid), font=("DejaVu Sans", 13, "bold"), width=17, height=2)
            b.grid(row=i // 4, column=i % 4, padx=(0, 8), pady=3)
            profile_buttons[p["id"]] = b
            dyn["home"].append(b)
            e = button(row1, clip(p["title"], 11), lambda pid=p["id"]: set_edit(profile=pid), font=("DejaVu Sans", 12, "bold"), width=11)
            e.pack(side="left", padx=2)
            dyn["edit"].append(e)
            e.pid = p["id"]
        if len(st["profiles"]) - len(BUILTIN_PROFILES) < MAX_CUSTOM_PROFILES:
            i = len(st["profiles"])
            b = button(prow, "+ Añadir perfil", lambda: open_name_dialog(), font=("DejaVu Sans", 13, "bold"), width=17, height=2, fg=ACC)
            b.grid(row=i // 4, column=i % 4, padx=(0, 8), pady=3)
            dyn["home"].append(b)
            e = button(row1, "+ Añadir perfil", lambda: open_name_dialog(), font=("DejaVu Sans", 12, "bold"), width=14, fg=ACC)
            e.pack(side="left", padx=2)
            dyn["edit"].append(e)

    def toggle_quick(pid):
        q = list(cfg.get("quick_profiles", []))
        if pid in q:
            q.remove(pid)
        else:
            q.append(pid)
        ctrl.set_quick_profiles(q)

    def sync_quick(st):
        sig = (tuple((p["id"], p["title"]) for p in st["profiles"]), tuple(st["quick_profiles"]))
        if sig == qstate["sig"]:
            return
        qstate["sig"] = sig
        for w in qstate["widgets"]:
            try:
                w.destroy()
            except Exception:
                pass
        qstate["widgets"] = []
        for p in st["profiles"]:
            on = p["id"] in st["quick_profiles"]
            b = button(qrow, "%s %s" % ("SI" if on else "NO", clip(p["title"], 14)), lambda pid=p["id"]: toggle_quick(pid),
                       font=("DejaVu Sans", 11, "bold"), width=18, bg=OK if on else PANEL, fg="#08111a" if on else FG)
            b.pack(side="left", padx=(0, 6), pady=2)
            qstate["widgets"].append(b)

    last_bind = {"key": None}

    def refresh_bindings(force=False):
        view = svc.bindings_view(edit["mode"], edit["profile"])
        if edit["profile"] not in profile_ids(cfg):
            edit["profile"] = "menus"
            view = svc.bindings_view(edit["mode"], edit["profile"])
        key = (edit["profile"], edit["mode"], tuple(i["value"] for i in view["inputs"]), ctrl.profile, ctrl.mode, dyn["sig"],
               tuple(sorted(drafts.items())))
        if not force and key == last_bind["key"]:
            return
        last_bind["key"] = key
        defaults = default_bindings(edit["profile"], edit["mode"])
        for i in view["inputs"]:
            b = bind_buttons.get(i["input"])
            if b is None:
                continue
            pending = (edit["profile"], edit["mode"], i["input"]) in drafts
            val = drafts[(edit["profile"], edit["mode"], i["input"])] if pending else i["value"]
            changed = val != defaults.get(i["input"], "none")
            b.config(text=clip(value_label(i["input"], val), 18) + ("  \u25cf" if pending else ("  *" if changed else "")),
                     bg=ACC if pending else (PANEL2 if changed else PANEL), fg="#08111a" if pending else (WARN if changed else FG))
        n = len(drafts)
        pend_lbl.config(text=("%d cambio%s SIN APLICAR  (en todos los perfiles/modos que hayas tocado)" % (n, "" if n == 1 else "s"))
                        if n else "Sin cambios pendientes", fg=ACC if n else DIM)
        apply_btn.config(state="normal" if n else "disabled", bg=OK if n else PANEL)
        discard_btn.config(state="normal" if n else "disabled")
        for w in dyn["edit"]:
            if hasattr(w, "pid"):
                sel(w, w.pid == edit["profile"])
        for m, b in em_buttons.items():
            sel(b, m == edit["mode"])
        if edit["profile"] in BUILTIN_PROFILES:
            del_btn.pack_forget()
        else:
            del_btn.config(text="¿SEGURO? OTRA VEZ" if edit["confirm"] == edit["profile"] else "Borrar perfil")
            del_btn.pack(side="right", padx=6)
        live = "  (es lo que esta activo ahora)" if (edit["profile"], edit["mode"]) == (ctrl.profile, ctrl.mode) else ""
        blank = "  Perfil en blanco: asigna lo que quieras." if edit["profile"] not in BUILTIN_PROFILES else ""
        note.config(text="Toca un boton para cambiar lo que hace (varios a la vez: A + B). Los cambios NO se guardan hasta APLICAR.  * = no es de fabrica  \u25cf = pendiente.%s%s" % (live, blank))

    # =========================================================== MOVIMIENTO
    mv = pages["mov"]

    def slider(parent, text, key, lo, hi, res):
        fr = tk.Frame(parent, bg=BG)
        fr.pack(side="left", padx=(0, 18))
        label(fr, text, F_SMALL, DIM).pack(anchor="w")
        var = tk.DoubleVar(value=cfg[key])

        def changed(_=None):
            svc.set_option(key, float(var.get()))
        tk.Scale(fr, from_=lo, to=hi, resolution=res, orient="horizontal", length=270, variable=var, command=changed,
                 bg=BG, fg=FG, troughcolor=PANEL, highlightthickness=0, font=("DejaVu Sans", 11)).pack()

    def checks(parent, items):
        fr = tk.Frame(parent, bg=BG)
        fr.pack(fill="x", pady=1)
        for key, text in items:
            v = tk.BooleanVar(value=cfg[key])
            tk.Checkbutton(fr, text=text, variable=v, command=lambda k=key, v=v: svc.set_option(k, bool(v.get())),
                           font=("DejaVu Sans", 12), fg=FG, bg=BG, selectcolor=PANEL, activebackground=BG,
                           activeforeground=FG).pack(side="left", padx=(0, 14))

    label(mv, "PUNTERO Y AGITAR  (las 4 direcciones se asignan en BOTONES; con todas en 'Nada' el agitado queda libre para los juegos)", F_SMALL, ACC).pack(anchor="w")
    sl = tk.Frame(mv, bg=BG)
    sl.pack(fill="x")
    slider(sl, "Velocidad del puntero (px/grado)", "px_per_deg", 10, 150, 1)
    slider(sl, "Suavizado (menos = mas suave)", "smooth_min_cut", 0.3, 6, 0.1)
    slider(sl, "Fuerza del agitado (g, menos = mas facil)", "shake_threshold", 0.3, 2.5, 0.05)
    checks(mv, (("shake_enabled", "Detectar agitado"), ("shake_flip_x", "Invertir izquierda/derecha del agitado"),
                ("shake_flip_y", "Invertir arriba/abajo"), ("invert_x", "Invertir puntero X"), ("invert_y", "Invertir puntero Y")))

    label(mv, "GIROSCOPIO Y MOVIMIENTO PARA EMULADORES", F_SMALL, ACC).pack(anchor="w", pady=(8, 0))
    checks(mv, (("gyro_enabled", "Giroscopio activo (MotionPlus)"), ("dsu_enabled", "Enviar movimiento al emulador (DSU)"),
                ("gyro_stick", "Giroscopio -> stick derecho")))
    sl2 = tk.Frame(mv, bg=BG)
    sl2.pack(fill="x", pady=(2, 0))
    slider(sl2, "Sensibilidad del giroscopio -> stick", "gyro_stick_gain", 0.3, 4.0, 0.1)
    cal = tk.Frame(sl2, bg=BG)
    cal.pack(side="left", padx=10, anchor="s")
    button(cal, "CALIBRAR GIROSCOPIO\n(deja el mando quieto)", lambda: ctrl.calibrate_gyro(), font=("DejaVu Sans", 12, "bold"), width=24, height=2).pack()
    prt = tk.Frame(sl2, bg=BG)
    prt.pack(side="left", padx=18, anchor="s")
    label(prt, "Puerto del servidor DSU", F_SMALL, DIM).pack(anchor="w")
    pr = tk.Frame(prt, bg=BG)
    pr.pack(anchor="w")
    button(pr, "-", lambda: svc.set_option("dsu_port", max(1024, cfg["dsu_port"] - 1)), font=("DejaVu Sans", 16, "bold"), width=3).pack(side="left")
    port_lbl = tk.Label(pr, text="", font=("DejaVu Sans", 15, "bold"), fg=FG, bg=BG, width=7)
    port_lbl.pack(side="left")
    button(pr, "+", lambda: svc.set_option("dsu_port", min(65530, cfg["dsu_port"] + 1)), font=("DejaVu Sans", 16, "bold"), width=3).pack(side="left")

    # ejes: por si el emulador mueve el juego al reves
    axes = tk.Frame(mv, bg=BG)
    axes.pack(fill="x", pady=(2, 0))
    label(axes, "Invertir ejes:", F_SMALL, DIM).pack(side="left", padx=(0, 8))
    axis_vars = []
    inv0 = list(cfg["dsu_invert"])

    def axis_changed():
        svc.set_option("dsu_invert", [bool(v.get()) for v in axis_vars])
    for i, nm in enumerate(AXIS_NAMES):
        v = tk.BooleanVar(value=bool(inv0[i]))
        axis_vars.append(v)
        tk.Checkbutton(axes, text=nm, variable=v, command=axis_changed, font=("DejaVu Sans", 12), fg=FG, bg=BG, selectcolor=PANEL,
                       activebackground=BG, activeforeground=FG).pack(side="left", padx=(0, 10))

    dsu_lbl = tk.Label(mv, text="", font=("DejaVu Sans Mono", 11), fg=FG, bg=PANEL, anchor="nw", justify="left", padx=12, pady=6)
    dsu_lbl.pack(fill="x", pady=(6, 0))
    label(mv, "Emulador (Ryujinx, Yuzu y derivados, Cemu, Dolphin...): Movimiento -> servidor DSU 127.0.0.1, el puerto de arriba. "
              "Si usas SteamDeckGyroDSU (EmuDeck) en 26760, no lo mezcles: ese es el giro de la Deck.", ("DejaVu Sans", 11), DIM,
          wraplength=1200).pack(fill="x", pady=(4, 0))

    # =========================================================== refresco
    def refresh():
        if not svc.started:                      # reiniciando (boton o despertar): se espera al servicio nuevo
            root.after(300, refresh)
            return
        try:
            rebind()
            st = svc.status()
            ok = st["devices_ok"]
            status.config(text="Dispositivos virtuales: %s    |    hidraw: %d    |    Modo: %s    |    Perfil: %s" % (
                "OK" if ok else "ERROR", st["hid_seen"], MODE_TITLES[st["mode"]], st["profile_title"]), fg=OK if ok else BAD)
            msgs = list(st["problems"])
            if st["hid_seen"] == 0:
                msgs.append("No se ve la Dolphin Bar (modo 4, 057e:0306). Conectala y enciende el mando.")
            if st["dsu_enabled"] and not st["dsu_open"]:
                msgs.append("El servidor DSU no pudo abrir ningun puerto cerca de %d." % st["dsu_port_wanted"])
            banner.config(text="  ".join(msgs[:2]))
            master.config(text="WIIDECK: ACTIVO\n(toca para apagar)" if st["enabled"] else "WIIDECK: APAGADO\n(toca para activar)",
                          bg=OK if st["enabled"] else BAD, fg="#08111a")
            ir_btn.config(text="PUNTERO IR:\n%s" % ("SI" if st["ir_enabled"] else "NO"), bg=OK if st["ir_enabled"] else BAD, fg="#08111a")
            sync_profiles(st)
            sync_quick(st)
            for m, b in mode_buttons.items():
                sel(b, m == st["mode"])
            for p, b in profile_buttons.items():
                sel(b, p == st["profile"])
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
            tail.config(text=log.get_tail(3))
            if st["dsu_open"]:
                moved = "" if st["dsu_port"] == st["dsu_port_wanted"] else "  (el %d estaba ocupado)" % st["dsu_port_wanted"]
                port_lbl.config(text=str(st["dsu_port"]))
                dsu_state = "ACTIVO en 127.0.0.1:%d%s" % (st["dsu_port"], moved)
            else:
                port_lbl.config(text=str(st["dsu_port_wanted"]))
                dsu_state = "apagado" if not st["dsu_enabled"] else "SIN PUERTO"
            mo = st["motion"]
            dsu_lbl.config(text="Servidor DSU: %s\nEmuladores conectados: %d    Paquetes enviados: %d\n"
                                "Lo que se envia ahora ->  Acel (g): %6.2f %6.2f %6.2f     Giro (grados/s): %7.1f %7.1f %7.1f" % (
                dsu_state, st["dsu_clients"], st["dsu_sent"], mo["acc"][0], mo["acc"][1], mo["acc"][2],
                mo["gyro"][0], mo["gyro"][1], mo["gyro"][2]))
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
    ap.add_argument("--profile", help="menus, juego o el id de un perfil propio (p1, p2...)")
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
