import { addEventListener, callable, definePlugin, removeEventListener } from "@decky/api";
import { ButtonItem, DropdownItem, Navigation, PanelSection, PanelSectionRow, SliderField, TextField, ToggleField, staticClasses } from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";

// ------------------------------------------------------------------ tipos (los devuelve main.py)
type Remote = { slot: number; status: string; battery: number; connected: boolean; ir: number; nunchuk: boolean; gyro: boolean; owner: boolean };
type ProfileInfo = { id: string; title: string; custom: boolean };
type Status = {
  running: boolean; active?: boolean; error: string; version?: string; enabled?: boolean; mode?: string; profile?: string; profile_title?: string;
  profiles?: ProfileInfo[]; ir_enabled?: boolean; devices_ok?: boolean;
  hid_seen?: number; problems?: string[]; remotes?: Remote[]; gyro_enabled?: boolean; dsu_enabled?: boolean; dsu_clients?: number;
  dsu_port?: number; px_per_deg?: number; shake_enabled?: boolean; shake_threshold?: number; gyro_stick?: boolean; gyro_stick_gain?: number;
};
type Option = { id: string; label: string };
type InputRow = { input: string; label: string; value: string; options: Option[] | null };
type Action = { id: string; label: string; group: string };
type BindingsView = { mode: string; profile: string; inputs: InputRow[]; actions: Action[] };

const getStatus = callable<[], Status>("get_status");
const getBindings = callable<[string, string], BindingsView | null>("get_bindings");
const setEnabled = callable<[boolean], boolean>("set_enabled");
const restartAll = callable<[], boolean>("restart");
const setMode = callable<[string], boolean>("set_mode");
const setProfile = callable<[string], boolean>("set_profile");
const createProfile = callable<[string], string | null>("create_profile");
const deleteProfile = callable<[string], boolean>("delete_profile");
const setOption = callable<[string, boolean | number], boolean>("set_option");
const applyBindings = callable<[string[][]], boolean>("apply_bindings");
const resetBindings = callable<[string, string], boolean>("reset_bindings");
const calibrate = callable<[], boolean>("calibrate");

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

function ButtonsEditor(props: { profiles?: ProfileInfo[]; onChanged: () => void }) {
  const [editProfile, setEditProfile] = useState<string | null>(null);
  const [editMode, setEditMode] = useState<string | null>(null);
  const [view, setView] = useState<BindingsView | null>(null);
  // Cambios sin aplicar: clave "perfil|modo|entrada" -> valor. Nada se guarda hasta pulsar APLICAR.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
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
  const actionOptions = view.actions.map((a) => ({ data: a.id, label: a.group + ": " + a.label }));
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
        <DropdownItem label="Perfil que editas" rgOptions={profileOptions(props.profiles)} selectedOption={editProfile} onChange={(o) => setEditProfile(o.data as string)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem label="Modo que editas" rgOptions={MODES} selectedOption={editMode} onChange={(o) => setEditMode(o.data as string)} />
      </PanelSectionRow>
      {view.inputs.map((row) => {
        const shown = drafts[keyOf(row.input)] ?? row.value;
        const opts = row.options ? row.options.map((o) => ({ data: o.id, label: o.label })) : actionOptions;
        // un combo (A + B) hecho en la ventana de escritorio no esta en la lista: se muestra tal cual
        if (!opts.some((o) => o.data === shown)) opts.unshift({ data: shown, label: "Combo: " + shown.replace(/[a-z]+:/g, "").replace(/\+/g, " + ") });
        return (
          <PanelSectionRow key={row.input}>
            <DropdownItem
              label={row.label + (keyOf(row.input) in drafts ? "  *" : "")}
              rgOptions={opts}
              selectedOption={shown}
              onChange={(o) => {
                const v = o.data as string;
                setMsg("");
                setDrafts((d) => {
                  const n = { ...d };
                  if (v === row.value) delete n[keyOf(row.input)];   // volver al valor guardado = no es cambio
                  else n[keyOf(row.input)] = v;
                  return n;
                });
              }}
            />
          </PanelSectionRow>
        );
      })}
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={pending === 0} onClick={apply}>
          {pending ? "APLICAR cambios (" + pending + ")" : "APLICAR (sin cambios)"}
        </ButtonItem>
      </PanelSectionRow>
      {pending > 0 && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => { setDrafts({}); setMsg("Cambios descartados"); }}>Descartar cambios</ButtonItem>
        </PanelSectionRow>
      )}
      {msg && <PanelSectionRow><div style={{ fontSize: "12px" }}>{msg}</div></PanelSectionRow>}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={async () => {
            await resetBindings(editMode, editProfile);
            setDrafts({});
            load(editProfile, editMode);
          }}
        >
          Restaurar este modo
        </ButtonItem>
      </PanelSectionRow>
      {info && info.custom && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={async () => {
              await deleteProfile(editProfile);
              setDrafts({});
              setEditProfile(null);
              props.onChanged();
            }}
          >
            Borrar el perfil "{info.title}"
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <TextField label="Perfil nuevo (en blanco)" description="Escribe un nombre y pulsa Crear" value={newName} onChange={(e) => setNewName(e.target.value)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          disabled={!newName.trim()}
          onClick={async () => {
            const id = await createProfile(newName.trim());
            if (id) {
              setNewName("");
              setDrafts({});
              setEditProfile(id);
              setMsg("Perfil creado: todo en blanco. Asigna botones y pulsa APLICAR.");
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
  const [showButtons, setShowButtons] = useState(false);
  const [wait, setWait] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setSt(await getStatus());
    } catch (e) {
      setSt({ running: false, error: "No se puede hablar con el backend de WiiDeck: " + e });
    }
  }, []);
  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 1000);
    return () => window.clearInterval(id);
  }, [refresh]);

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
        <PanelSectionRow><ButtonItem layout="below" disabled={wait} onClick={() => slow(restartAll())}>Reiniciar WiiDeck</ButtonItem></PanelSectionRow>
      </PanelSection>
    );

  const remotes = st.remotes ?? [];
  const problems = [...(st.problems ?? [])];
  if (st.hid_seen === 0) problems.push("No se ve la Dolphin Bar (modo 4). Conectala y enciende el mando.");

  return (
    <>
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
          <ButtonItem layout="below" disabled={wait} onClick={() => slow(restartAll())}>
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
          <DropdownItem label="Modo (1 + 2 en el mando)" rgOptions={MODES} selectedOption={st.mode} onChange={(o) => act(setMode(o.data as string))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem label="Perfil (+ y − en el mando)" rgOptions={profileOptions(st.profiles)} selectedOption={st.profile} onChange={(o) => act(setProfile(o.data as string))} />
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
            description={"Servidor 127.0.0.1:" + st.dsu_port + " · " + (st.dsu_clients ?? 0) + " cliente(s). Para Switch: activa 'Movimiento' en el emulador"}
            checked={!!st.dsu_enabled} onChange={(v: boolean) => act(setOption("dsu_enabled", v))} />
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
          <OptionSlider label="Fuerza de la sacudida" description="Menos = se activa mas facil" value={st.shake_threshold ?? 0.55} min={0.3} max={2.5} step={0.05}
            onCommit={(n) => act(setOption("shake_threshold", n))} />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Asignacion de botones">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => setShowButtons(!showButtons)}>
            {showButtons ? "Ocultar asignacion" : "Editar asignacion de botones"}
          </ButtonItem>
        </PanelSectionRow>
        {showButtons && <ButtonsEditor profiles={st.profiles} onChanged={refresh} />}
      </PanelSection>
    </>
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
  return {
    name: "WiiDeck",
    titleView: <div className={staticClasses.Title}>WiiDeck</div>,
    content: <Content />,
    icon: <Icon />,
    onDismount() {
      removeEventListener("open_qam", onQam);
    },
  };
});
