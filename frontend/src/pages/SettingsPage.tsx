import { useCallback, useEffect, useState } from "react";

import { api, message } from "../api";
import { OptionFields } from "../components/OptionFields";
import { summarize } from "../format";
import type { AppState, Preferences } from "../types";
import { PasswordForm } from "./Access";

type Editable = Pick<Preferences, "autostart" | "udc" | "defaults">;

export function SettingsPage({ onPasswordChanged }: { onPasswordChanged: () => Promise<void> }) {
  const [state, setState] = useState<AppState | null>(null);
  const [draft, setDraft] = useState<Editable | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (resetDraft: boolean) => {
    try {
      const fresh = await api.get<AppState>("/state");
      setState(fresh);
      if (resetDraft) {
        const { autostart, udc, defaults } = fresh.preferences;
        setDraft({ autostart, udc, defaults });
      }
    } catch (err) {
      setNote({ ok: false, text: message(err) });
    }
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  if (!state || !draft) {
    return note ? <p className="notice bad">{note.text}</p> : <p className="muted">Loading…</p>;
  }

  const save = async () => {
    setBusy(true);
    try {
      // Interface numbers only mean something for one device.
      await api.put("/preferences", { ...draft, defaults: { ...draft.defaults, hide_interfaces: [] } });
      setNote({ ok: true, text: "Saved." });
      await load(true);
    } catch (err) {
      setNote({ ok: false, text: message(err) });
    } finally {
      setBusy(false);
    }
  };

  const forget = async (key: string) => {
    try {
      await api.delete(`/profiles/${encodeURIComponent(key)}`);
      await load(false);
    } catch (err) {
      setNote({ ok: false, text: message(err) });
    }
  };

  const profiles = Object.entries(state.preferences.profiles);

  return (
    <>
      <section className="card">
        <div className="card-head">
          <h2>Auto-start</h2>
        </div>
        <label className="check">
          <input type="checkbox" checked={draft.autostart.enabled}
            onChange={(e) => setDraft({ ...draft, autostart: { ...draft.autostart, enabled: e.target.checked } })} />
          <span>
            Start the proxy when a USB device is plugged in
            <small>
              Also at power-on, if exactly one device is already attached. The boot drive is never picked. A device
              the Pi uses as a network interface is picked only after you have started it from the Proxy page
              once. Stopping the proxy by hand keeps it stopped until the device is re-plugged. When a device
              is not started, the Proxy page says why.
            </small>
          </span>
        </label>
        <fieldset className="options" disabled={!draft.autostart.enabled}>
          <label className="check">
            <input type="radio" name="which" checked={!draft.autostart.known_only}
              onChange={() => setDraft({ ...draft, autostart: { ...draft.autostart, known_only: false } })} />
            <span>Any device</span>
          </label>
          <label className="check">
            <input type="radio" name="which" checked={draft.autostart.known_only}
              onChange={() => setDraft({ ...draft, autostart: { ...draft.autostart, known_only: true } })} />
            <span>Only devices I have started from this page before</span>
          </label>
          {state.udcs.length > 1 && (
            <label>
              Gadget controller
              <select value={draft.udc ?? ""} onChange={(e) => setDraft({ ...draft, udc: e.target.value || null })}>
                <option value="">Choose…</option>
                {state.udcs.map((u) => (
                  <option key={u.name} value={u.name}>{u.name}</option>
                ))}
              </select>
            </label>
          )}
        </fieldset>

        <h3>Default options</h3>
        <p className="muted small">
          Used for a device that has no saved options yet, both here and when it starts automatically.
        </p>
        <OptionFields options={draft.defaults} injectionFiles={state.injection_files}
          onChange={(defaults) => setDraft({ ...draft, defaults })} />

        {note && <p className={note.ok ? "notice" : "notice bad"}>{note.text}</p>}
        <button className="primary" disabled={busy} onClick={() => void save()}>Save settings</button>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Saved device options</h2>
        </div>
        {profiles.length === 0 ? (
          <p className="muted">
            Nothing saved yet. Each time you start a device from the Proxy page, its options are remembered here.
          </p>
        ) : (
          <table>
            <thead>
              <tr><th>Device (vendor:product)</th><th>Options</th><th /></tr>
            </thead>
            <tbody>
              {profiles.map(([key, options]) => (
                <tr key={key}>
                  <td><code>{key}</code></td>
                  <td>{summarize(options)}</td>
                  <td className="row-actions">
                    <button className="quiet" onClick={() => void forget(key)}>Forget</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Admin password</h2>
        </div>
        <PasswordForm submitLabel="Change password" onChanged={onPasswordChanged} />
      </section>
    </>
  );
}
