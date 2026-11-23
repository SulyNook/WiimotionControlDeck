import { addEventListener, callable, definePlugin, removeEventListener, toaster } from "@decky/api";
import { ButtonItem, ConfirmModal, DropdownItem, Navigation, PanelSection, PanelSectionRow, SliderField, TextField, ToggleField, showModal, staticClasses } from "@decky/ui";
import { useCallback, useEffect, useRef, useState } from "react";

// ------------------------------------------------------------------ types (returned by main.py)
type Remote = { slot: number; status: string; battery: number; connected: boolean; ir: number; nunchuk: boolean; gyro: boolean; owner: boolean };
type ProfileInfo = { id: string; title: string; custom: boolean };
type Status = {
  running: boolean; active?: boolean; error: string; version?: string; enabled?: boolean; mode?: string; profile?: string; profile_title?: string;
  profiles?: ProfileInfo[]; quick_profiles?: string[]; ir_enabled?: boolean; devices_ok?: boolean;
  hid_seen?: number; problems?: string[]; remotes?: Remote[]; gyro_enabled?: boolean; dsu_enabled?: boolean; dsu_clients?: number;
  dsu_port?: number; dsu_ports?: Record<string, { state: string; owner: string }>; px_per_deg?: number; shake_enabled?: boolean; shake_threshold?: number; shake_reversals?: number; shake_gap?: number; gyro_deadzone?: number; notify_enabled?: boolean; eden_shake_amp?: number; eden_shake_gyro?: number; dsu_mirror?: boolean; eden_shake_hz?: number; eden_shake_cycles?: number; dsu_accel_gain?: number; motion?: { acc: number[]; gyro: number[]; peak: number }; gyro_from_accel?: boolean; gyro_stick?: boolean; gyro_stick_gain?: number;
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
const freeDsuPort = callable<[number], [boolean, string]>("free_dsu_port");
const edenShake = callable<[string, number], boolean>("eden_shake");
const calibrate = callable<[], boolean>("calibrate");

const SHAKE_DIRS = [
  { data: "up", label: "Up" }, { data: "down", label: "Down" }, { data: "left", label: "Left" },
  { data: "right", label: "Right" }, { data: "forward", label: "Forward" }, { data: "back", label: "Back" },
];
const MAX_COMBO = 4;   // same as in deckcore.py
const MODES = [
  { data: "vertical", label: "Vertical (pointing at the screen)" },
  { data: "horizontal", label: "Horizontal (like an NES controller)" },
  { data: "nunchuk", label: "Nunchuk (pointer + stick)" },
];
const FALLBACK_PROFILES: ProfileInfo[] = [
  { id: "menus", title: "Steam Menus (A = click)", custom: false },
  { id: "juego", title: "Games (A, B... like the Deck)", custom: false },
];
const profileOptions = (ps?: ProfileInfo[]) => (ps && ps.length ? ps : FALLBACK_PROFILES).map((p) => ({ data: p.id, label: p.title }));

/** Mandatory confirmation: one dialog per step (the last one runs the action). Cancelling at any step aborts. */
function confirmSteps(steps: { title: string; text: string; ok: string }[], action: () => void, i = 0) {
  const st = steps[i];
  showModal(
    <ConfirmModal
      strTitle={st.title}
      strDescription={st.text}
      strOKButtonText={st.ok}
      strCancelButtonText="Cancel"
      onOK={() => { if (i + 1 < steps.length) confirmSteps(steps, action, i + 1); else action(); }}
    />
  );
}

// ------------------------------------------------------------------ state that survives panel re-creation
// When an option is picked in a dropdown, Decky/Steam re-creates the panel and jumps to the top. What matters
// (editor open, profile/mode being edited, unapplied changes) lives outside the component.
const ui = {
  showButtons: false,
  editProfile: null as string | null,
  editMode: null as string | null,
  drafts: {} as Record<string, string>,
  expanded: null as string | null,
};

/** First ancestor with vertical scroll (the quick access menu container). */
function scrollParent(el: HTMLElement | null): HTMLElement | null {
  let n: HTMLElement | null = el;
  while (n) {
    const oy = window.getComputedStyle(n).overflowY;
    if ((oy === "auto" || oy === "scroll") && n.scrollHeight > n.clientHeight) return n;
    n = n.parentElement;
  }
  return null;
}

/** Call from a dropdown's onChange: remembers the scroll position and restores it once Decky finishes handling focus (300 ms). */
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

// ------------------------------------------------------------------ components
/** Slider that does not flood the backend: saves 250 ms after release and is not overwritten by polling while it is being moved. */
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
  // Unapplied changes: key "profile|mode|input" -> value. Nothing is saved until APPLY is pressed.
  const [drafts, setDraftsS] = useState<Record<string, string>>(ui.drafts);
  const setDrafts = (v: Record<string, string> | ((c: Record<string, string>) => Record<string, string>)) =>
    setDraftsS((c) => { const n = typeof v === "function" ? v(c) : v; ui.drafts = n; return n; });
  const [expanded, setExpandedS] = useState<string | null>(ui.expanded);
  const setExpanded = (v: string | null) => { ui.expanded = v; setExpandedS(v); };
  const [newName, setNewName] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async (p: string | null, m: string | null) => {
    const v = await getBindings(m ?? "", p ?? "");   // "" = the active mode/profile
    if (v) {
      setView(v);
      setEditProfile((cur) => cur ?? v.profile);
      setEditMode((cur) => cur ?? v.mode);
    }
  }, []);
  useEffect(() => {
    load(editProfile, editMode);
  }, [editProfile, editMode, load]);

  if (!view || !editProfile || !editMode) return <PanelSectionRow>Loading...</PanelSectionRow>;
  const labelOf = (id: string) => view.actions.find((a) => a.id === id)?.label ?? id;
  const catOf = (id: string) => (id === "none" ? "__none" : view.actions.find((a) => a.id === id)?.cat ?? "Program");
  const keyOf = (input: string) => editProfile + "|" + editMode + "|" + input;
  const pending = Object.keys(drafts).length;
  const info = (props.profiles ?? []).find((p) => p.id === editProfile);

  const apply = async () => {
    const changes = Object.keys(drafts).map((k) => [...k.split("|"), drafts[k]]);
    const ok = await applyBindings(changes);
    setMsg(ok ? "Saved and applied (" + changes.length + ")" : "Could not apply");
    if (ok) setDrafts({});
    load(editProfile, editMode);
  };

  return (
    <>
      <PanelSectionRow>
        <DropdownItem label="Profile being edited" rgOptions={profileOptions(props.profiles)} selectedOption={editProfile} onChange={(o) => { props.keep(); setEditProfile(o.data as string); }} />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem label="Mode being edited" rgOptions={MODES} selectedOption={editMode} onChange={(o) => { props.keep(); setEditMode(o.data as string); }} />
      </PanelSectionRow>
      {view.inputs.map((row) => {
        const shown = drafts[keyOf(row.input)] ?? row.value;
        const changed = keyOf(row.input) in drafts;
        const setValue = (v: string) => {
          props.keep();
          setMsg("");
          setDrafts((d) => {
            const n = { ...d };
            if (v === row.value) delete n[keyOf(row.input)];   // back to the saved value = not a change
            else n[keyOf(row.input)] = v;
            return n;
          });
        };
        if (row.options) {   // pointer and stick: a single choice
          const opts = row.options.map((o) => ({ data: o.id, label: o.label }));
          return (
            <PanelSectionRow key={row.input}>
              <DropdownItem label={row.label + (changed ? "  *" : "")} rgOptions={opts} selectedOption={shown} onChange={(o) => setValue(o.data as string)} />
            </PanelSectionRow>
          );
        }
        // Several buttons at once (A + B + ...). Closed: a one-line summary. Open: for each button a "Type"
        // (Gamepad / Keyboard / Mouse / Program) and, inside it, the action; at the end a "+" slot to add another (maximum 4).
        const parts = shown === "none" ? [] : shown.split("+");
        const join = (ps: string[]) => (ps.length ? ps.join("+") : "none");
        const summary = parts.length ? parts.map((p) => labelOf(p)).join(" + ") : "None";
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
                ...(filled || i === 0 ? [] : [{ data: "__add", label: "+ Add another button..." }]),
                ...(i === 0 ? [{ data: "__none", label: "None" }] : filled ? [{ data: "__del", label: "Remove this button" }] : []),
                ...view.categories.map((c) => ({ data: c, label: c })),
              ];
              const actOpts = view.actions.filter((x) => x.cat === cat && x.id !== "none").map((x) => ({ data: x.id, label: x.group.replace("Keyboard: ", "") === x.group ? x.label : x.group.replace("Keyboard: ", "") + ": " + x.label }));
              return (
                <div key={row.input + i}>
                  <PanelSectionRow>
                    <DropdownItem
                      label={(i === 0 ? "Type" : "+ Type")}
                      rgOptions={typeOpts}
                      selectedOption={filled ? cat : i === 0 ? "__none" : "__add"}
                      onChange={(o) => {
                        const v = o.data as string;
                        const ps = [...parts];
                        if (v === "__add") return;
                        if (v === "__del") ps.splice(i, 1);
                        else if (v === "__none") ps.splice(0, ps.length);
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
                        label={i === 0 ? "Button" : "+ Button"}
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
          {pending ? "APPLY changes (" + pending + ")" : "APPLY (no changes)"}
        </ButtonItem>
      </PanelSectionRow>
      {pending > 0 && (
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => confirmSteps([{ title: "Discard changes", text: "The " + pending + " unapplied changes will be lost.", ok: "Discard" }], () => { setDrafts({}); setMsg("Changes discarded"); })}>Discard changes</ButtonItem>
        </PanelSectionRow>
      )}
      {msg && <PanelSectionRow><div style={{ fontSize: "12px" }}>{msg}</div></PanelSectionRow>}
      <PanelSectionRow>
        <ButtonItem
          layout="below"
          onClick={() => confirmSteps([
            { title: "Restore this mode", text: "The buttons of mode \"" + editMode + "\" in profile \"" + (info ? info.title : editProfile) + "\" go back to their default values.", ok: "Continue" },
            { title: "Final confirmation", text: "The current assignment for that mode will be lost. This cannot be undone.", ok: "Restore" },
          ], async () => {
            await resetBindings(editMode, editProfile);
            setDrafts({});
            load(editProfile, editMode);
          })}
        >
          Restore this mode
        </ButtonItem>
      </PanelSectionRow>
      {info && info.custom && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => confirmSteps([
              { title: "Delete profile", text: "You are about to delete profile \"" + info.title + "\" with all its buttons.", ok: "Continue" },
              { title: "Final confirmation", text: "Profile \"" + info.title + "\" will be deleted for good. This cannot be undone.", ok: "Delete" },
            ], async () => {
              await deleteProfile(editProfile);
              setDrafts({});
              setEditProfile(null);
              props.onChanged();
            })}
          >
            Delete profile "{info.title}"
          </ButtonItem>
        </PanelSectionRow>
      )}
      <PanelSectionRow>
        <TextField label="New profile (copy of the one you are editing)" description={"Copy of \"" + (info ? info.title : editProfile) + "\". Type a name and press Add"} value={newName} onChange={(e) => setNewName(e.target.value)} />
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
              setMsg("Profile created as a copy. Change whatever you like and press APPLY.");
            } else setMsg("Could not create (empty name or maximum number of profiles reached)");
            props.onChanged();
          }}
        >
          + Add profile
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
  const [portMsg, setPortMsg] = useState("");

  const refresh = useCallback(async () => {
    try {
      const n = await getStatus();
      // if nothing changed the same object is kept: no re-render, so dropdowns stay open
      setSt((cur) => (cur && JSON.stringify(cur) === JSON.stringify(n) ? cur : n));
    } catch (e) {
      setSt({ running: false, error: "Cannot talk to the WimotionControlDeck backend: " + e });
    }
  }, []);
  useEffect(() => {
    refresh();
    // no polling while the button editor is open: re-rendering every second closes the dropdowns and jumps to the top
    if (showButtons) return () => {};
    const id = window.setInterval(refresh, 1000);
    return () => window.clearInterval(id);
  }, [refresh, showButtons]);

  const act = (p: Promise<unknown>) => p.then(refresh);
  const slow = async (p: Promise<unknown>) => {   // starting/restarting takes a few seconds
    setWait(true);
    try { await p; } finally { setWait(false); refresh(); }
  };

  if (!st) return <PanelSection title="WimotionControlDeck"><PanelSectionRow>Loading...</PanelSectionRow></PanelSection>;
  if (!st.running)
    // Fully off (or failed to start): only the switch and restart. Profiles remain saved.
    return (
      <PanelSection title="WimotionControlDeck">
        <PanelSectionRow>
          <ToggleField label="Enable WimotionControlDeck" description={wait ? "Starting..." : "Fully off: the remote does nothing"} checked={false}
            disabled={wait} onChange={(v: boolean) => slow(setEnabled(v))} />
        </PanelSectionRow>
        {st.error && <PanelSectionRow><div style={{ color: "#ffd60a" }}>{st.error}</div></PanelSectionRow>}
        <PanelSectionRow><ButtonItem layout="below" disabled={wait} onClick={() => confirmSteps([{ title: "Restart WimotionControlDeck", text: "Everything restarts (the remote reconnects). Profiles and settings are kept.", ok: "Restart" }], () => slow(restartAll()))}>Restart WimotionControlDeck</ButtonItem></PanelSectionRow>
      </PanelSection>
    );

  const remotes = st.remotes ?? [];
  const problems = [...(st.problems ?? [])];
  if (st.hid_seen === 0) problems.push("Dolphin Bar not detected (mode 4). Plug it in and turn the remote on.");

  return (
    <div ref={rootRef}>
      <PanelSection title="WimotionControlDeck">
        <PanelSectionRow>
          <ToggleField
            label="Enable WimotionControlDeck"
            description={wait ? "Shutting down..." : "On. Turning it off stops everything completely"}
            checked={true}
            disabled={wait}
            onChange={(v: boolean) => slow(setEnabled(v))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={wait} onClick={() => confirmSteps([{ title: "Restart WimotionControlDeck", text: "Everything restarts (the remote reconnects). Profiles and settings are kept.", ok: "Restart" }], () => slow(restartAll()))}>
            {wait ? "Restarting..." : "Restart WimotionControlDeck (profiles and settings are kept)"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", lineHeight: "1.4" }}>
            {remotes.length === 0 ? "No remote connected. Press a button on the remote." : remotes.map((r) => (
              <div key={r.slot}>
                Remote {r.slot}: {r.battery >= 0 ? r.battery + "%" : "?"} · IR {r.ir} · Nunchuk {r.nunchuk ? "yes" : "no"} · Gyro {r.gyro ? "yes" : "no"}
              </div>
            ))}
            {problems.map((p, i) => <div key={i} style={{ color: "#ffd60a" }}>{p}</div>)}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem label="Mode (1 + 2 on the remote)" rgOptions={MODES} selectedOption={st.mode} onChange={(o) => { keep(); act(setMode(o.data as string)); }} />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem label="Profile" rgOptions={profileOptions(st.profiles)} selectedOption={st.profile} onChange={(o) => { keep(); act(setProfile(o.data as string)); }} />
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.8 }}>Quick access: profiles that + and − together cycle through on the remote</div>
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
          <ToggleField label="Mode and profile alerts" description="Toast notification on change" checked={st.notify_enabled !== false}
            onChange={(v: boolean) => act(setOption("notify_enabled", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="IR pointer" description="Off: the remote does not move the cursor (also: hold Down + Plus)"
            checked={st.ir_enabled !== false} onChange={(v: boolean) => act(setOption("ir_enabled", v))} />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Gyro">
        <PanelSectionRow>
          <ToggleField label="Gyro (MotionPlus)" description="Plus remotes have it built in" checked={!!st.gyro_enabled}
            onChange={(v: boolean) => act(setOption("gyro_enabled", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Motion for emulators (DSU)"
            description={"Server 127.0.0.1:" + st.dsu_port + " (also 26760/26761) · " + (st.dsu_clients ?? 0) + " client(s). For Switch: enable 'Motion' in the emulator"}
            checked={!!st.dsu_enabled} onChange={(v: boolean) => act(setOption("dsu_enabled", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Gyro dead zone (degrees/s)" description="Raise it if the emulator cursor slowly drifts" value={st.gyro_deadzone ?? 2} min={0} max={8} step={0.5}
            onCommit={(n) => act(setOption("gyro_deadzone", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Accelerometer gain (emulator)" description={"Raise it if the game does not notice hits. Peak now: " + (st.motion ? st.motion.peak : 0) + " g"} value={st.dsu_accel_gain ?? 1} min={0.5} max={4} step={0.1}
            onCommit={(n) => act(setOption("dsu_accel_gain", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Estimated gyro without MotionPlus" description="In Nunchuk mode there is no gyro: it is approximated from the accelerometer (pitch and roll)"
            checked={st.gyro_from_accel !== false} onChange={(v: boolean) => act(setOption("gyro_from_accel", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", lineHeight: "1.4" }}>
            {["26760", "26761"].map((p) => {
              const x = (st.dsu_ports ?? {})[p];
              const own = st.dsu_port !== undefined && String(st.dsu_port) === p;
              return <div key={p}>Port {p}: {own || (x && x.state === "wimotioncontroldeck") ? "WimotionControlDeck" : x ? "in use by " + x.owner : "free"}</div>;
            })}
            {portMsg && <div style={{ color: "#ffd60a" }}>{portMsg}</div>}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => confirmSteps([
            { title: "Use port 26760 (Steam Deck mode)", text: "If port 26760 is in use by the Deck's DSU gyro (SteamDeckGyroDSU), it is stopped. Emulators that read the Deck's motion on that port will receive the remote's instead.", ok: "Continue" },
            { title: "Final confirmation", text: "That program is stopped until it is restarted. It is only stopped if it looks like a gyro server.", ok: "Stop it and use 26760" },
          ], async () => { const r = await freeDsuPort(26760); setPortMsg(r[1]); refresh(); })}>Use port 26760 (like the Deck)</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Gyro -> right stick" description="Aim with the remote in any game"
            checked={!!st.gyro_stick} onChange={(v: boolean) => act(setOption("gyro_stick", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Stick sensitivity" value={st.gyro_stick_gain ?? 1} min={0.3} max={4} step={0.1}
            onCommit={(n) => act(setOption("gyro_stick_gain", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => act(calibrate())}>Calibrate gyro (keep the remote still)</ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Shake for the emulator">
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.8 }}>
            Assign "Emulator shake: ..." (Program type) to any button or to a remote shake. A burst of acceleration is sent over DSU, which the game reads as a shake.
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Strength (g)" value={st.eden_shake_amp ?? 5} min={1} max={10} step={0.5} onCommit={(n) => act(setOption("eden_shake_amp", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Accompanying gyro (degrees/s)" description="A shaking wrist also rotates: 0 = acceleration only" value={st.eden_shake_gyro ?? 700} min={0} max={2000} step={50} onCommit={(n) => act(setOption("eden_shake_gyro", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Shake rate (Hz)" value={st.eden_shake_hz ?? 8} min={2} max={20} step={1} onCommit={(n) => act(setOption("eden_shake_hz", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Number of shake cycles" value={st.eden_shake_cycles ?? 2} min={1} max={6} step={1} onCommit={(n) => act(setOption("eden_shake_cycles", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem label="Test direction" rgOptions={SHAKE_DIRS} selectedOption={shakeDir} onChange={(o) => setShakeDir(o.data as string)} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => act(edenShake(shakeDir, 0))}>Test shake</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => act(edenShake(shakeDir, 5))}>Continuous test (5 s)</ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Copy motion to DSU pad 1" description="In case the game reads the emulator's 2nd sensor (Motion 2)"
            checked={!!st.dsu_mirror} onChange={(v: boolean) => act(setOption("dsu_mirror", v))} />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Pointer and shake">
        <PanelSectionRow>
          <OptionSlider label="Pointer speed" value={st.px_per_deg ?? 45} min={10} max={150} step={1}
            onCommit={(n) => act(setOption("px_per_deg", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField label="Shake the remote (up/down/left/right)" description="Each direction is assigned in the button editor" checked={!!st.shake_enabled}
            onChange={(v: boolean) => act(setOption("shake_enabled", v))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Shake strength" description="Lower = detects gentler movements" value={st.shake_threshold ?? 0.55} min={0.08} max={2.5} step={0.02}
            onCommit={(n) => act(setOption("shake_threshold", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Direction changes" description="2 = back and forth; higher = you have to shake more" value={st.shake_reversals ?? 3} min={1} max={6} step={1}
            onCommit={(n) => act(setOption("shake_reversals", n))} />
        </PanelSectionRow>
        <PanelSectionRow>
          <OptionSlider label="Time between changes (s)" description="Higher = allows slower shaking" value={st.shake_gap ?? 0.4} min={0.2} max={1.2} step={0.05}
            onCommit={(n) => act(setOption("shake_gap", n))} />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Button mapping">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => setShowButtons(!showButtons)}>
            {showButtons ? "Hide mapping" : "Edit button mapping"}
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
  // Home + Plus held on the remote: the backend signals and here Steam's ··· menu (QAM) is opened
  const onQam = () => {
    try { Navigation.OpenQuickAccessMenu(); } catch (e) { console.error("WimotionControlDeck: could not open the QAM", e); }
  };
  addEventListener("open_qam", onQam);
  // Mode or profile change: Steam toast notification (like "X is playing"), without asking for confirmation
  const onNotify = (title: string, body: string) => {
    try { toaster.toast({ title, body, duration: 2500, critical: false, showNewIndicator: false, expiry: 0 } as any); } catch (e) { console.error("WimotionControlDeck: could not show the notification", e); }
  };
  addEventListener("notify", onNotify);
  return {
    name: "WimotionControlDeck",
    titleView: <div className={staticClasses.Title}>WimotionControlDeck</div>,
    content: <Content />,
    icon: <Icon />,
    onDismount() {
      removeEventListener("open_qam", onQam);
      removeEventListener("notify", onNotify);
    },
  };
});
