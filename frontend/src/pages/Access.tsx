import { useState, type FormEvent } from "react";

import { api, message } from "../api";

export function Login({ defaultPassword, onDone }: { defaultPassword: boolean; onDone: () => Promise<void> }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api.post("/login", { username, password });
      await onDone();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="access" onSubmit={submit}>
      <h1>Midwire</h1>
      <label>
        User name
        <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
      </label>
      <label>
        Password
        <input type="password" autoComplete="current-password" autoFocus value={password}
          onChange={(e) => setPassword(e.target.value)} />
      </label>
      {error && <p className="notice bad">{error}</p>}
      {/* An empty password is allowed, so the button never waits for one. */}
      <button className="primary" disabled={busy || !username}>Log in</button>
      {defaultPassword ? (
        <p className="muted small">
          New device: the user name is <code>admin</code> and the password is <code>admin</code>.
        </p>
      ) : (
        <p className="muted small">
          Forgot it? Run <code>sudo midwire-web-ui set-password</code> on the device.
        </p>
      )}
    </form>
  );
}

interface PasswordFormProps {
  // Known in advance on first login; otherwise the form asks for it.
  current?: string;
  submitLabel: string;
  onChanged: () => Promise<void> | void;
}

export function PasswordForm({ current, submitLabel, onChanged }: PasswordFormProps) {
  const [typedCurrent, setTypedCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (next !== repeat) return setNote({ ok: false, text: "The two new passwords do not match." });
    setBusy(true);
    try {
      await api.post("/password", { current: current ?? typedCurrent, new: next });
      setNote({ ok: true, text: "Password changed. Other browsers have been logged out." });
      setTypedCurrent("");
      setNext("");
      setRepeat("");
      await onChanged();
    } catch (err) {
      setNote({ ok: false, text: message(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="stack" onSubmit={submit}>
      {current === undefined && (
        <label>
          Current password
          <input type="password" autoComplete="current-password" value={typedCurrent}
            onChange={(e) => setTypedCurrent(e.target.value)} />
        </label>
      )}
      <label>
        New password
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
      </label>
      <label>
        Repeat new password
        <input type="password" autoComplete="new-password" value={repeat}
          onChange={(e) => setRepeat(e.target.value)} />
      </label>
      {next === "" && repeat === "" ? (
        <p className="muted small">
          Leaving both empty sets an empty password: logging in then needs only the user name.
        </p>
      ) : (
        next.length < 8 && <p className="muted small">Short passwords are easy to guess. 8 characters or more is safer.</p>
      )}
      {note && <p className={note.ok ? "notice" : "notice bad"}>{note.text}</p>}
      <button className="primary" disabled={busy}>{submitLabel}</button>
    </form>
  );
}
