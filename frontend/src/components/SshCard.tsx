import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, message } from "../api";
import type { SystemStatus } from "../types";

// Used when the device has no login user and the page creates the first one.
const NEW_USER = "midwire";

export function SshCard() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const [newName, setNewName] = useState(NEW_USER);
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [key, setKey] = useState("");

  const load = useCallback(async () => {
    try {
      setStatus(await api.get<SystemStatus>("/system"));
    } catch (err) {
      setNote({ ok: false, text: message(err) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!status) {
    return (
      <section className="card">
        <div className="card-head"><h2>SSH and system login</h2></div>
        <p className={note ? "notice bad" : "muted"}>{note ? note.text : "Loading…"}</p>
      </section>
    );
  }
  if (!status.supported) {
    return (
      <section className="card">
        <div className="card-head"><h2>SSH and system login</h2></div>
        <p className="notice warn">{status.reason}</p>
      </section>
    );
  }

  const ssh = status.ssh!;
  const users = status.users ?? [];
  const user = users.find((u) => u.name === picked) ?? users[0] ?? null;
  const target = user ? user.name : newName;

  // Every change answers with the fresh status.
  const act = async (done: string, work: () => Promise<SystemStatus>) => {
    setBusy(true);
    setNote(null);
    try {
      setStatus(await work());
      setNote({ ok: true, text: done });
      return true;
    } catch (err) {
      setNote({ ok: false, text: message(err) });
      await load();
      return false;
    } finally {
      setBusy(false);
    }
  };

  const toggleSsh = () =>
    act(ssh.enabled ? "SSH is off." : "SSH is on.", () =>
      api.put<SystemStatus>("/system/ssh", { enabled: !ssh.enabled }));

  const savePassword = async (event: FormEvent) => {
    event.preventDefault();
    if (password.length < 8) return setNote({ ok: false, text: "Use a password of at least 8 characters." });
    if (password !== repeat) return setNote({ ok: false, text: "The two passwords do not match." });
    const ok = await act(user ? `Password set for ${target}.` : `User ${target} created.`, () =>
      api.post<SystemStatus>("/system/password", { user: target, password }));
    if (ok) {
      setPassword("");
      setRepeat("");
      setPicked(target);
    }
  };

  const addKey = async (event: FormEvent) => {
    event.preventDefault();
    const ok = await act("Key added.", () => api.post<SystemStatus>("/system/keys", { user: target, key: key.trim() }));
    if (ok) setKey("");
  };

  const removeKey = (fingerprint: string) =>
    act("Key removed.", () => api.post<SystemStatus>("/system/keys/remove", { user: target, fingerprint }));

  return (
    <section className="card">
      <div className="card-head">
        <h2>SSH and system login</h2>
        <span className={ssh.enabled ? "badge on" : "badge"}>{ssh.enabled ? "SSH on" : "SSH off"}</span>
        <span className="spacer" />
        {ssh.installed && (
          <button disabled={busy} onClick={() => void toggleSsh()}>
            {ssh.enabled ? "Turn SSH off" : "Turn SSH on"}
          </button>
        )}
      </div>
      {!ssh.installed && <p className="notice warn">The SSH server is not installed on this device.</p>}
      <p className="muted small">
        SSH gives a command line on the Pi itself. It uses a system user of the Pi, not the admin password of this
        page.{user && <> Connect with <code>ssh {user.name}@midwire.local</code>.</>}
      </p>
      {ssh.enabled && !users.some((u) => u.has_password || u.keys.length > 0) && (
        <p className="notice warn">SSH is on, but no user has a password or a key yet, so nobody can log in.</p>
      )}
      {note && <p className={note.ok ? "notice" : "notice bad"}>{note.text}</p>}

      {status.locked && (
        <p className="notice warn">
          Passwords and keys are locked while this page's admin password is the default or empty. Anyone who can
          open this page could otherwise give themselves a root login on the Pi. Change the admin password below
          first.
        </p>
      )}

      <fieldset className="options" disabled={status.locked || busy}>
        <h3>System user</h3>
        {users.length === 0 && (
          <>
            <p className="muted small">
              This Pi has no login user yet. Setting a password creates one, with permission to use{" "}
              <code>sudo</code>.
            </p>
            <label>
              User name
              <input value={newName} maxLength={31} onChange={(e) => setNewName(e.target.value.toLowerCase())} />
            </label>
          </>
        )}
        {users.length > 1 && (
          <label>
            User
            <select value={target} onChange={(e) => setPicked(e.target.value)}>
              {users.map((u) => (
                <option key={u.name} value={u.name}>{u.name}</option>
              ))}
            </select>
          </label>
        )}
        {users.length === 1 && (
          <p>
            <strong>{user!.name}</strong>{" "}
            <span className="muted small">
              {user!.has_password ? "has a password" : "has no password"}
              {user!.sudo ? " · may use sudo" : ""}
            </span>
          </p>
        )}

        <form className="stack" onSubmit={savePassword}>
          <label>
            {user ? `New password for ${user.name}` : "Password"}
            <input type="password" autoComplete="new-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </label>
          <label>
            Repeat password
            <input type="password" autoComplete="new-password" value={repeat}
              onChange={(e) => setRepeat(e.target.value)} />
          </label>
          <button disabled={!password || !target}>{user ? "Set password" : "Create user"}</button>
        </form>

        {user && (
          <>
            <h3>SSH keys of {user.name}</h3>
            {user.keys.length === 0 ? (
              <p className="muted small">No keys. With a key you can log in without typing the password.</p>
            ) : (
              <table>
                <thead>
                  <tr><th>Type</th><th>Fingerprint</th><th>Comment</th><th /></tr>
                </thead>
                <tbody>
                  {user.keys.map((k) => (
                    <tr key={k.fingerprint}>
                      <td>{k.type}</td>
                      <td><code>{k.fingerprint}</code></td>
                      <td>{k.comment}{k.restricted ? " (restricted)" : ""}</td>
                      <td className="row-actions">
                        <button type="button" className="quiet" onClick={() => void removeKey(k.fingerprint)}>
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <form className="stack" onSubmit={addKey}>
              <label>
                Add a public key
                <textarea rows={3} spellCheck={false} value={key} onChange={(e) => setKey(e.target.value)}
                  placeholder="ssh-ed25519 AAAA… you@computer   (the contents of a .pub file)" />
              </label>
              <button disabled={key.trim().length < 20}>Add key</button>
            </form>
          </>
        )}
      </fieldset>
    </section>
  );
}
