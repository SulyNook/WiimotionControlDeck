import { callable, definePlugin } from "@decky/api";
import { ButtonItem, DropdownItem, PanelSection, PanelSectionRow, SliderField, ToggleField, staticClasses } from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";

// ------------------------------------------------------------------ tipos (los devuelve main.py)
type Remote = { slot: number; status: string; battery: number; connected: boolean; ir: number; nunchuk: boolean; gyro: boolean; owner: boolean };
type Status = {
  running: boolean; error: string; version?: string; enabled?: boolean; mode?: string; profile?: string; devices_ok?: boolean;
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
const setMode = callable<[string], boolean>("set_mode");
const setProfile = callable<[string], boolean>("set_profile");
const setOption = callable<[string, boolean | number], boolean>("set_option");
const setBinding = callable<[string, string, string, string], boolean>("set_binding");
const resetBindings = callable<[string, string], boolean>("reset_bindings");
const calibrate = callable<[], boolean>("calibrate");

const MODES = [
  { data: "vertical", label: "Vertical (apuntando a la pantalla)" },
  { data: "horizontal", label: "Horizontal (como un mando de NES)" },
  { data: "nunchuk", label: "Nunchuk (puntero + palanca)" },
];
const PROFILES = [
  { data: "menus", label: "Menus de Steam (A = clic)" },
  { data: "juego", label: "Juegos (A, B... como la Deck)" },
];

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

function ButtonsEditor() {
  const [editProfile, setEditProfile] = useState<string | null>(null);
  const [editMode, setEditMode] = useState<string | null>(null);
  const [view, setView] = useState<BindingsView | null>(null);

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

  return (
    <>
      <PanelSectionRow>
        <DropdownItem label="Perfil que editas" rgOptions={PROFILES} selectedOption={editProfile} onChange={(o) => setEditProfile(o.data as string)} />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem label="Modo que editas" rgOptions={MODES} selectedOption={editMode} onChange={(o) => setEditMode(o.data as string)} />
      </PanelSectionRow>
      {view.inputs.map((row) => (
        <PanelSectionRow key={row.input}>
          <DropdownItem
            label={row.label}
            rgOptions={row.options ? row.options.map((o) => ({ data: o.id, label: o.label })) : actionOptions}
            selectedOption={row.value}
            onChange={async (o) => {
              await setBinding(row.input, o.data as string, editMode, editProfile);
              load(editProfile, editMode);
            }}
          />
        </PanelSectionRow>
      ))}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={async () => {
            await resetBindings(editMode, editProfile);
            load(editProfile, editMode);
          }}
        >
          Restaurar este modo
        </ButtonItem>
      </PanelSectionRow>
    </>
  );
}

function Content() {
  const [st, setSt] = useState<Status | null>(null);
  const [showButtons, setShowButtons] = useState(false);

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

  if (!st) return <PanelSection title="WiiDeck"><PanelSectionRow>Cargando...</PanelSectionRow></PanelSection>;
  if (!st.running)
    return (
      <PanelSection title="WiiDeck">
        <PanelSectionRow><div style={{ color: "#ffd60a" }}>{st.error}</div></PanelSectionRow>
        <PanelSectionRow><ButtonItem layout="below" onClick={refresh}>Reintentar</ButtonItem></PanelSectionRow>
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
            description={st.enabled ? "El mando controla la Deck" : "Apagado: el mando no hace nada"}
            checked={!!st.enabled}
            onChange={(v: boolean) => act(setEnabled(v))}
          />
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
          <DropdownItem label="Perfil (+ y − en el mando)" rgOptions={PROFILES} selectedOption={st.profile} onChange={(o) => act(setProfile(o.data as string))} />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Giroscopio">
        <PanelSectionRow>
          <ToggleField label="Giroscopio (MotionPlus)" description="No se puede usar a la vez que el Nunchuk" checked={!!st.gyro_enabled}
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
          <ToggleField label="Agitar = cambiar de coleccion" checked={!!st.shake_enabled}
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
        {showButtons && <ButtonsEditor />}
      </PanelSection>
    </>
  );
}

const Icon = () => (
  <svg width="1em" height="1em" viewBox="0 0 24 24" fill="currentColor">
    <path d="M8 1h8a2 2 0 0 1 2 2v18a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V3a2 2 0 0 1 2-2zm4 3a1.6 1.6 0 1 0 0 3.2A1.6 1.6 0 0 0 12 4zm0 5.5a2.6 2.6 0 1 0 0 5.2 2.6 2.6 0 0 0 0-5.2zM9 17h6v2H9z" />
  </svg>
);

export default definePlugin(() => ({
  name: "WiiDeck",
  titleView: <div className={staticClasses.Title}>WiiDeck</div>,
  content: <Content />,
  icon: <Icon />,
  onDismount() {},
}));
