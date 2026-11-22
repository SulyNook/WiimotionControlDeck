import { addEventListener, callable, definePlugin, removeEventListener, toaster } from "@decky/api";
import { ButtonItem, ConfirmModal, DropdownItem, Navigation, PanelSection, PanelSectionRow, SliderField, TextField, ToggleField, showModal, staticClasses } from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";

// ------------------------------------------------------------------ tipos (los devuelve main.py)
type Remote = { slot: number; status: string; battery: number; connected: boolean; ir: number; nunchuk: boolean; gyro: boolean; owner: boolean };
type ProfileInfo = { id: string; title: string; custom: boolean };
type Status = {
  running: boolean; active?: boolean; error: string; version?: string; enabled?: boolean; mode?: string; profile?: string; profile_title?: string;
  profiles?: ProfileInfo[]; quick_profiles?: string[]; ir_enabled?: boolean; devices_ok?: boolean;
  hid_seen?: number; problems?: string[]; remotes?: Remote[]; gyro_enabled?: boolean; dsu_enabled?: boolean; dsu_clients?: number;
  dsu_port?: number; px_per_deg?: number; shake_enabled?: boolean; shake_threshold?: number; shake_reversals?: number; shake_gap?: number; gyro_deadzone?: number; notify_enabled?: boolean; eden_shake_amp?: number; eden_shake_gyro?: number; dsu_mirror?: boolean; eden_shake_hz?: number; eden_shake_cycles?: number; dsu_accel_gain?: number; motion?: { acc: number[]; gyro: number[]; peak: number }; gyro_from_accel?: boolean; gyro_stick?: boolean; gyro_stick_gain?: number;
};
type Option = { id: string; label: string };
type InputRow = { input: string; label: string; value: string; options: Option[] | null };
type Action = { id: string; label: string; group: string; cat: string };
type BindingsView = { mode: string; profile: string; inputs: InputRow[]; actions: Action[]; categories: string[] };

const getStatus = callable<[], Status>("get_status");
const getBindings = callable<[string, string], BindingsView | null>("get_bindings");
const setEnabled = callable<[boolean], boolean>("set_enabled");
const restartAll = callable<[], boolean>("restart");
const setMode = callable<[string], boolean>("set_mode");
const setProfile = callable<[string], boolean>("set_profile");
const createProfile = callable<[string, string], string | null>("create_profile");
const setQuickProfiles = callable<[string[]], boolean>("set_quick_profiles");
const deleteProfile = callable<[string], boolean>("delete_profile");
const setOption = callable<[string, boolean | number], boolean>("set_option");
const applyBindings = callable<[string[][]], boolean>("apply_bindings");
const resetBindings = callable<[string, string], boolean>("reset_bindings");
const edenShake = callable<[string, number], boolean>("eden_shake");
const calibrate = callable<[], boolean>("calibrate");

const SHAKE_DIRS = [
  { data: "up", label: "Arriba" }, { data: "down", label: "Abajo" }, { data: "left", label: "Izquierda" },
  { data: "right", label: "Derecha" }, { data: "forward", label: "Adelante" }, { data: "back", label: "Atras" },
];
const MAX_COMBO = 4;   // igual que en deckcore.py
const MODES = [
  { data: "vertical", label: "Vertical (apuntando a la pantalla)" },
  { data: "horizontal", label: "Horizontal (como un mando de NES)" },
  { data: "nunchuk", label: "Nunchuk (puntero + palanca)" },
];
const FALLBACK_PROFILES: ProfileInfo[] = [
  { id: "menus", title: "Menus de Steam (A = clic)", custom: false },
  { id: "juego", title: "Juegos (A, B... como la Deck)", custom: false },
];
const profileOptions = (ps?: ProfileInfo[]) => (ps && ps.length ? ps : FALLBACK_PROFILES).map((p) => ({ data: p.id, label: p.title }));

/** Confirmacion obligatoria: una ventana por cada paso (el ultimo ejecuta la accion). Cancelar en cualquiera aborta. */
function confirmSteps(steps: { title: string; text: string; ok: string }[], action: () => void, i = 0) {
  const st = steps[i];
  showModal(
    <ConfirmModal
      strTitle={st.title}
      strDescription={st.text}
      strOKButtonText={st.ok}
      strCancelButtonText="Cancelar"
      onOK={() => { if (i + 1 < steps.length) confirmSteps(steps, action, i + 1); else action(); }}
    />
  );
}

// ------------------------------------------------------------------ estado que sobrevive a recreaciones del panel
// Al elegir una opcion en un desplegable, Decky/Steam recrea el panel y salta a la cabecera. Lo que importa
// (editor abierto, perfil/modo que editas, cambios sin aplicar) vive fuera del componente.
const ui = {
  showButtons: false,
  editProfile: null as string | null,
  editMode: null as string | null,
  drafts: {} as Record<string, string>,
  expanded: null as string | null,
};

/** Primer ancestro con scroll vertical (el contenedor del menu rapido). */
function scrollParent(el: HTMLElement | null): HTMLElement | null {
  let n: HTMLElement | null = el;
  while (n) {
    const oy = window.getComputedStyle(n).overflowY;
    if ((oy === "auto" || oy === "scroll") && n.scrollHeight > n.clientHeight) return n;
    n = n.parentElement;
  }
  return null;
}

/** Llamar desde onChange de un desplegable: recuerda el scroll y lo devuelve cuando Decky termina de gestionar el foco (300 ms). */
function holdScroll(anchor: HTMLElement | null) {
  const sc = scrollParent(anchor);
  if (!sc) return;
  const top = sc.scrollTop;
  [300, 700].forEach((ms) =>
    window.setTimeout(() => {
      const diff = top - sc.scrollTop;
      if (Math.abs(diff) > 2) sc.scrollBy({ top: diff });
    }, ms)
  );
}

// ------------------------------------------------------------------ componentes
/** Deslizador que no satura al backend: guarda 250 ms despues de soltar y no se pisa con el sondeo mientras se mueve. */
function OptionSlider(props: { label: string; value: number; min: number; max: number; step: number; description?: string; onCommit: (v: number) => Promise<unknown> }) {
  const [v, setV] = useState<number>(props.value);
  const busy = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!busy.current) setV(props.value);
  }, [props.value]);
  return (
    <SliderField
      label={props.label}
      description={props.description}
      value={v}
      min={props.min}
      max={props.max}
      step={props.step}
      showValue
      onChange={(n: number) => {
        busy.current = true;
        setV(n);
        window.clearTimeout(timer.current);
        timer.current = window.setTimeout(() => {
          props.onCommit(n).finally(() => {
            busy.current = false;
          });
        }, 250);
      }}
    />
  );
}

function ButtonsEditor(props: { profiles?: ProfileInfo[]; onChanged: () => void; keep: () => void }) {
  const [editProfile, setEditProfileS] = useState<string | null>(ui.editProfile);
  const [editMode, setEditModeS] = useState<string | null>(ui.editMode);
  const setEditProfile = (v: string | null | ((c: string | null) => string | null)) =>
    setEditProfileS((c) => { const n = typeof v === "function" ? v(c) : v; ui.editProfile = n; return n; });
  const setEditMode = (v: string | null | ((c: string | null) => string | null)) =>
    setEditModeS((c) => { const n = typeof v === "function" ? v(c) : v; ui.editMode = n; return n; });
  const [view, setView] = useState<BindingsView | null>(null);
  // Cambios sin aplicar: clave "perfil|modo|entrada" -> valor. Nada se guarda hasta pulsar APLICAR.
  const [drafts, setDraftsS] = useState<Record<string, string>>(ui.drafts);
  const setDrafts = (v: Record<string, string> | ((c: Record<string, string>) => Record<string, string>)) =>
    setDraftsS((c) => { const n = typeof v === "function" ? v(c) : v; ui.drafts = n; return n; });
  const [expanded, setExpandedS] = useState<string | null>(ui.expanded);
  const setExpanded = (v: string | null) => { ui.expanded = v; setExpandedS(v); };
  const [newName, setNewName] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async (p: string | null, m: string | null) => {
    const v = await getBindings(m ?? "", p ?? "");   // "" = el modo/perfil activo
    if (v) {
      setView(v);
      setEditProfile((cur) => cur ?? v.profile);
      setEditMode((cur) => cur ?? v.mode);
    }
  }, []);
  useEffect(() => {
    load(editProfile, editMode);
  }, [editProfile, editMode, load]);

  if (!view || !editProfile || !editMode) return <PanelSectionRow>Cargando...</PanelSectionRow>;
  const labelOf = (id: string) => view.actions.find((a) => a.id === id)?.label ?? id;
  const catOf = (id: string) => (id === "none" ? "Nada" : view.actions.find((a) => a.id === id)?.cat ?? "Programa");
  const keyOf = (input: string) => editProfile + "|" + editMode + "|" + input;
  const pending = Object.keys(drafts).length;
  const info = (props.profiles ?? []).find((p) => p.id === editProfile);

  const apply = async () => {
    const changes = Object.keys(drafts).map((k) => [...k.split("|"), drafts[k]]);
    const ok = await applyBindings(changes);
    setMsg(ok ? "Guardado y aplicado (" + changes.length + ")" : "No se pudo aplicar");
    if (ok) setDrafts({});
    load(editProfile, editMode);
  };

  return (
    <>
      <PanelSectionRow>
        <DropdownItem label="Perfil que editas" rgOptions={profileOptions(props.profiles)} selectedOption={editProfile} onChange={(o) => { props.keep(); setEditProfile(o.data as string); }} />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem label="Modo que editas" rgOptions={MODES} selectedOption={editMode} onChange={(o) => { props.keep(); setEditMode(o.data as string); }} />
      </PanelSectionRow>
      {view.inputs.map((row) => {
        const shown = drafts[keyOf(row.input)] ?? row.value;
        const changed = keyOf(row.input) in drafts;
        const setValue = (v: string) => {
          props.keep();
          setMsg("");
          setDrafts((d) => {
            const n = { ...d };
            if (v === row.value) delete n[keyOf(row.input)];   // volver al valor guardado = no es cambio
            else n[keyOf(row.input)] = v;
            return n;
          });
        };
        if (row.options) {   // puntero y palanca: una sola eleccion
          const opts = row.options.map((o) => ({ data: o.id, label: o.label }));
          return (
            <PanelSectionRow key={row.input}>
              <DropdownItem label={row.label + (changed ? "  *" : "")} rgOptions={opts} selectedOption={shown} onChange={(o) => setValue(o.data as string)} />
            </PanelSectionRow>
          );
        }
        // Varios botones a la vez (A + B + ...). Cerrado: una linea con el resumen. Abierto: por cada boton un "Tipo"
        // (Mando / Teclado / Raton / Programa) y, dentro, la accion; al final un hueco "+" para anadir otro (maximo 4).
        const parts = shown === "none" ? [] : shown.split("+");
        const join = (ps: string[]) => (ps.length ? ps.join("+") : "none");
        const summary = parts.length ? parts.map((p) => labelOf(p)).join(" + ") : "Nada";
        const open = expanded === row.input;
        const head = (
          <PanelSectionRow key={row.input}>
            <ButtonItem layout="below" onClick={() => { props.keep(); setExpanded(open ? null : row.input); }}>
              {(open ? "▼ " : "▶ ") + row.label + (changed ? " *" : "") + ":  " + summary}
            </ButtonItem>
          </PanelSectionRow>
        );
        if (!open) return head;
        const slots = parts.length < MAX_COMBO ? parts.length + 1 : MAX_COMBO;
        return (
          <div key={row.input}>
            {head}
            {Array.from({ length: Math.max(slots, 1) }, (_, i) => {
              const filled = i < parts.length;
              const cat = filled ? catOf(parts[i]) : "__add";
              const typeOpts = [
                ...(filled || i === 0 ? [] : [{ data: "__add", label: "+ Añadir otro botón..." }]),
                ...(i === 0 ? [{ data: "Nada", label: "Nada" }] : filled ? [{ data: "__del", label: "Quitar este botón" }] : []),
                ...view.categories.map((c) => ({ data: c, label: c })),
              ];
              const actOpts = view.actions.filter((x) => x.cat === cat && x.id !== "none").map((x) => ({ data: x.id, label: x.group.replace("Teclado: ", "") === x.group ? x.label : x.group.replace("Teclado: ", "") + ": " + x.label }));
              return (
                <div key={row.input + i}>
                  <PanelSectionRow>
                    <DropdownItem
                      label={(i === 0 ? "Tipo" : "+ Tipo")}
                      rgOptions={typeOpts}
                      selectedOption={filled ? cat : i === 0 ? "Nada" : "__add"}
                      onChange={(o) => {
                        const v = o.data as string;
                        const ps = [...parts];
                        if (v === "__add") return;
                        if (v === "__del") ps.splice(i, 1);
                        else if (v === "Nada") ps.splice(0, ps.length);
                        else if (!filled || catOf(ps[i]) !== v) {
                          const first = view.actions.find((x) => x.cat === v && x.id !== "none");
                          if (first) { if (filled) ps[i] = first.id; else ps.push(first.id); }
                        }
                        setValue(join(ps));
                      }}
                    />
                  </PanelSectionRow>
                  {filled && actOpts.length > 0 && (
                    <PanelSectionRow>
                      <DropdownItem
                        label={i === 0 ? "Botón" : "+ Botón"}
                        rgOptions={actOpts}
                        selectedOption={parts[i]}
                        onChange={(o) => {
                          const ps = [...parts];
                          ps[i] = o.data as string;
                          setValue(join(ps));
                        }}
                      />
                    </PanelSectionRow>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={pending === 0} onClick={apply}>
          {pending ? "APLICAR cambios (" + pending + ")" : "APLICAR (sin cambios)"}
        </ButtonItem>
      </PanelSectionRow>
      {pending > 0 && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => confirmSteps([{ title: "Descartar cambios", text: "Se pierden los " + pending + " cambios sin aplicar.", ok: "Descartar" }], () => { setDrafts({}); setMsg("Cambios descartados"); })}>Descartar cambios</ButtonItem>
        </PanelSectionRow>
      )}
      {msg && <PanelSectionRow><div style={{ fontSize: "12px" }}>{msg}</div></PanelSectionRow>}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={() => confirmSteps([
            { title: "Restaurar este modo", text: "Los botones del modo \"" + editMode + "\" del perfil \"" + (info ? info.title : editProfile) + "\" vuelven a los valores de fabrica.", ok: "Continuar" },
            { title: "Ultima confirmacion", text: "Se pierde la asignacion actual de ese modo. No se puede deshacer.", ok: "Restaurar" },
          ], async () => {
            await resetBindings(editMode, editProfile);
            setDrafts({});
            load(editProfile, editMode);
          })}
        >
          Restaurar este modo
        </ButtonItem>
      </PanelSectionRow>
      {info && info.custom && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => confirmSteps([
              { title: "Borrar perfil", text: "Vas a borrar el perfil \"" + info.title + "\" con todos sus botones.", ok: "Continuar" },
              { title: "Ultima confirmacion", text: "El perfil \"" + info.title + "\" se borra para siempre. No se puede deshacer.", ok: "Borrar" },
            ], async () => {
              await deleteProfile(editProfile);
              setDrafts({});
              setEditProfile(null);
              props.onChanged();
            })}
          >
            Borrar el perfil "{info.title}"
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <TextField label="Perfil nuevo (copia del que editas)" description={"Copia de \"" + (info ? info.title : editProfile) + "\". Escribe un nombre y pulsa Añadir"} value={newName} onChange={(e) => setNewName(e.target.value)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={!newName.trim()}
          onClick={async () => {
            const id = await createProfile(newName.trim(), editProfile);
            if (id) {
              setNewName("");
              setDrafts({});
              setEditProfile(id);
              setMsg("Perfil creado como copia. Cambia lo que quieras y pulsa APLICAR.");
            } else setMsg("No se pudo crear (nombre vacio o maximo de perfiles)");
            props.onChanged();
          }}
        >
          + Añadir perfil
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}

function Content() {
  const [st, setSt] = useState<Status | null>(null);
  const [showButtons, setShowButtonsS] = useState(ui.showButtons);
  const setShowButtons = (v: boolean) => { ui.showButtons = v; setShowButtonsS(v); };
  const rootRef = useRef<HTMLDivElement | null>(null);
  const keep = () => holdScroll(rootRef.current);
  const [wait, setWait] = useState(false);
  const [shakeDir, setShakeDir] = useState("up");

  const refresh = useCallback(async () => {
    try {
      const n = await getStatus();
      // si no ha cambiado nada se conserva el mismo objeto: no hay re-render y los desplegables no se cierran
      setSt((cur) => (cur && JSON.stringify(cur) === JSON.stringify(n) ? cur : n));
    } catch (e) {
      setSt({ running: false, error: "No se puede hablar con el backend de WiiDeck: " + e });
    }
  }, []);
  useEffect(() => {
    refresh();
    // con el editor de botones abierto no se sondea: re-renderizar cada segundo cierra los desplegables y salta a la cabecera
    if (showButtons) return () => {};
    const id = window.setInterval(refresh, 1000);
    return () => window.clearInterval(id);
  }, [refresh, showButtons]);

  const act = (p: Promise<unknown>) => p.then(refresh);
  const slow = async (p: Promise<unknown>) => {   // encender/reiniciar tarda unos segundos
    setWait(true);
    try { await p; } finally { setWait(false); refresh(); }
  };

  if (!st) return <PanelSection title="WiiDeck"><PanelSectionRow>Cargando...</PanelSectionRow></PanelSection>;
  if (!st.running)
    // Apagado del todo (o fallo al arrancar): solo el interruptor y el reinicio. Los perfiles siguen guardados.
    return (
      <PanelSection title="WiiDeck">
        <PanelSectionRow>
          <ToggleField label="Activar WiiDeck" description={wait ? "Arrancando..." : "Apagado del todo: el mando no hace nada"} checked={false}
            disabled={wait} onChange={(v: boolean) => slow(setEnabled(v))} />
        </PanelSectionRow>
        {st.error && <PanelSectionRow><div style={{ color: "#ffd60a" }}>{st.error}</div></PanelSectionRow>}
        <PanelSectionRow><ButtonItem layout="below" disabled={wait} onClick={() => confirmSteps([{ title: "Reiniciar WiiDeck", text: "Se reinicia todo (el mando se vuelve a conectar). Perfiles y ajustes se conservan.", ok: "Reiniciar" }], () => slow(restartAll()))}>Reiniciar WiiDeck</ButtonItem></PanelSectionRow>
      </PanelSection>
    );

  const remotes = st.remotes ?? [];
  const problems = [...(st.problems ?? [])];
  if (st.hid_seen === 0) problems.push("No se ve la Dolphin Bar (modo 4). Conectala y enciende el mando.");

  return (
    <div ref={rootRef}>
      <PanelSection title="WiiDeck">
        <PanelSectionRow>
          <ToggleField
            label="Activar WiiDeck"
            description={wait ? "Apagando..." : "Encendido. Al apagarlo se detiene todo del todo"}
            checked={true}
            disabled={wait}
            onChange={(v: boolean) => slow(setEnabled(v))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={wait} onClick={() => confirmSteps([{ title: "Reiniciar WiiDeck", text: "Se reinicia todo (el mando se vuelve a conectar). Perfiles y ajustes se conservan.", ok: "Reiniciar" }], () => slow(restartAll()))}>
            {wait ? "Reiniciando..." : "Reiniciar WiiDeck (perfiles y ajustes se conservan)"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", lineHeight: "1.4" }}>
            {remotes.length === 0 ? "Ningun mando conectado. Pulsa un boton del mando." : remotes.map((r) => (
              <div key={r.slot}>
                Mando {r.slot}: {r.battery >= 0 ? r.battery + "%" : "?"} · IR {r.ir} · Nunchuk {r.nunchuk ? "si" : "no"} · Giro {r.gyro ? "si" : "no"}
              </div>
            ))}
            {problems.map((p, i) => <div key={i} style={{ color: "#ffd60a" }}>{p}</div>)}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem label="Modo (1 + 2 en el mando)" rgOptions={MODES} selectedOption={st.mode} onChange={(o) => { keep(); act(setMode(o.data as string)); }} />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem label="Perfil" rgOptions={profileOptions(st.profiles)} selectedOption={st.profile} onChange={(o) => { keep(); act(setProfile(o.data as string)); }} />
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.8 }}>Acceso rapido: perfiles por los que rotan + y − a la vez en el mando</div>
        </PanelSectionRow>
        {(st.profiles ?? []).map((p) => {
          const q = st.quick_profiles ?? [];
          return (
            <PanelSectionRow key={"q" + p.id}>
              <ToggleField label={p.title} checked={q.includes(p.id)}
                onChange={(v: boolean) => act(setQuickProfiles(v ? [...q, p.id] : q.filter((x) => x !== p.id)))} />
            </PanelSectionRow>
          );
        })}
        <PanelSectionRow>
          <ToggleField label="Avisos de modo y perfil" description="Notificacion emergente al cambiar" checked={st.notify_enabled !== false}
            onChange={(v: boolean) => act(setOption("notify_enabled", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Puntero IR" description="Apagado: el mando no mueve el cursor (tambien: Abajo + Plus mantenidos)"
            checked={st.ir_enabled !== false} onChange={(v: boolean) => act(setOption("ir_enabled", v))} />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Giroscopio">
        <PanelSectionRow>
          <ToggleField label="Giroscopio (MotionPlus)" description="Los mandos Plus lo traen integrado" checked={!!st.gyro_enabled}
            onChange={(v: boolean) => act(setOption("gyro_enabled", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Movimiento para emuladores (DSU)"
            description={"Servidor 127.0.0.1:" + st.dsu_port + " (tambien 26760/26761) · " + (st.dsu_clients ?? 0) + " cliente(s). Para Switch: activa 'Movimiento' en el emulador"}
            checked={!!st.dsu_enabled} onChange={(v: boolean) => act(setOption("dsu_enabled", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Zona muerta del giro (grados/s)" description="Sube si el cursor del emulador deriva despacio" value={st.gyro_deadzone ?? 2} min={0} max={8} step={0.5}
            onCommit={(n) => act(setOption("gyro_deadzone", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Ganancia del acelerometro (emulador)" description={"Sube si el juego no nota los golpes. Pico ahora: " + (st.motion ? st.motion.peak : 0) + " g"} value={st.dsu_accel_gain ?? 1} min={0.5} max={4} step={0.1}
            onCommit={(n) => act(setOption("dsu_accel_gain", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Giro estimado sin MotionPlus" description="En modo Nunchuk no hay giroscopio: se aproxima con el acelerometro (cabeceo y alabeo)"
            checked={st.gyro_from_accel !== false} onChange={(v: boolean) => act(setOption("gyro_from_accel", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Giroscopio -> stick derecho" description="Apuntar con el mando en cualquier juego"
            checked={!!st.gyro_stick} onChange={(v: boolean) => act(setOption("gyro_stick", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Sensibilidad del stick" value={st.gyro_stick_gain ?? 1} min={0.3} max={4} step={0.1}
            onCommit={(n) => act(setOption("gyro_stick_gain", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => act(calibrate())}>Calibrar giroscopio (mando quieto)</ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Sacudida para el emulador">
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.8 }}>
            Asigna "Sacudida al emulador: ..." (tipo Programa) a cualquier boton o a un agitado del mando. Se manda por DSU un golpe de aceleracion que el juego lee como sacudida.
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Fuerza (g)" value={st.eden_shake_amp ?? 5} min={1} max={10} step={0.5} onCommit={(n) => act(setOption("eden_shake_amp", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Giro que acompana (grados/s)" description="Una muneca que sacude tambien gira: 0 = solo aceleracion" value={st.eden_shake_gyro ?? 700} min={0} max={2000} step={50} onCommit={(n) => act(setOption("eden_shake_gyro", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Velocidad del vaiven (Hz)" value={st.eden_shake_hz ?? 8} min={2} max={20} step={1} onCommit={(n) => act(setOption("eden_shake_hz", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Numero de vaivenes" value={st.eden_shake_cycles ?? 2} min={1} max={6} step={1} onCommit={(n) => act(setOption("eden_shake_cycles", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem label="Direccion de prueba" rgOptions={SHAKE_DIRS} selectedOption={shakeDir} onChange={(o) => setShakeDir(o.data as string)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => act(edenShake(shakeDir, 0))}>Probar sacudida</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => act(edenShake(shakeDir, 5))}>Prueba continua (5 s)</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Copiar el movimiento al pad 1 de DSU" description="Por si el juego lee el 2.o sensor (Motion 2) del emulador"
            checked={!!st.dsu_mirror} onChange={(v: boolean) => act(setOption("dsu_mirror", v))} />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Puntero y sacudida">
        <PanelSectionRow>
          <OptionSlider label="Velocidad del puntero" value={st.px_per_deg ?? 45} min={10} max={150} step={1}
            onCommit={(n) => act(setOption("px_per_deg", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Agitar el mando (arriba/abajo/izq./der.)" description="Cada direccion se asigna en la edicion de botones" checked={!!st.shake_enabled}
            onChange={(v: boolean) => act(setOption("shake_enabled", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Fuerza de la sacudida" description="Menos = detecta movimientos mas suaves" value={st.shake_threshold ?? 0.55} min={0.08} max={2.5} step={0.02}
            onCommit={(n) => act(setOption("shake_threshold", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Cambios de sentido" description="2 = ida y vuelta; mas = hay que agitar mas" value={st.shake_reversals ?? 3} min={1} max={6} step={1}
            onCommit={(n) => act(setOption("shake_reversals", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Tiempo entre cambios (s)" description="Mas = admite agitar mas despacio" value={st.shake_gap ?? 0.4} min={0.2} max={1.2} step={0.05}
            onCommit={(n) => act(setOption("shake_gap", n))} />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Asignacion de botones">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => setShowButtons(!showButtons)}>
            {showButtons ? "Ocultar asignacion" : "Editar asignacion de botones"}
          </ButtonItem>
        </PanelSectionRow>
        {showButtons && <ButtonsEditor profiles={st.profiles} onChanged={refresh} keep={keep} />}
      </PanelSection>
    </div>
  );
}

const Icon = () => (
  <svg width="1em" height="1em" viewBox="0 0 24 24" fill="currentColor">
    <path d="M8 1h8a2 2 0 0 1 2 2v18a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2zm4 3a1.6 1.6 0 1 0 0 3.2A1.6 1.6 0 0 0 12 4zm0 5.5a2.6 2.6 0 1 0 0 5.2 2.6 2.6 0 0 0 0-5.2zM9 17h6v2H9z" />
  </svg>
);

export default definePlugin(() => {
  // Home + Plus mantenidos en el mando: el backend avisa y aqui se abre el menu ··· de Steam (QAM)
  const onQam = () => {
    try { Navigation.OpenQuickAccessMenu(); } catch (e) { console.error("WiiDeck: no se pudo abrir el QAM", e); }
  };
  addEventListener("open_qam", onQam);
  // Cambio de modo o de perfil: notificacion emergente de Steam (como "X esta jugando"), sin pedir confirmacion
  const onNotify = (title: string, body: string) => {
    try { toaster.toast({ title, body, duration: 2500, critical: false, showNewIndicator: false, expiry: 0 } as any); } catch (e) { console.error("WiiDeck: no se pudo mostrar la notificacion", e); }
  };
  addEventListener("notify", onNotify);
  return {
    name: "WiiDeck",
    titleView: <div className={staticClasses.Title}>WiiDeck</div>,
    content: <Content />,
    icon: <Icon />,
    onDismount() {
      removeEventListener("open_qam", onQam);
      removeEventListener("notify", onNotify);
    },
  };
});
