import { useEffect, useState, type FormEvent } from "react";

import { api, message } from "../api";
import type { NetworkStatus, SetupStatus } from "../types";
import { PasswordForm } from "./Access";

type Step = "admin" | "hotspot";

interface Props {
  setup: SetupStatus;
  // Called when the wizard is finished or skipped.
  onClose: () => void;
}

// Shown after login while something is still on its factory default: the
// admin password, the Wi-Fi hotspot's password, or both. Every step can be
// skipped; the page keeps a reminder up for what was left.
export function SetupWizard({ setup, onClose }: Props) {
  // Decided once, so finishing a step does not shorten the list under us.
  const [steps] = useState<Step[]>(() => [
    ...(setup.admin_password_default ? (["admin"] as Step[]) : []),
    // Last: saving it disconnects everyone on the hotspot.
    ...(setup.hotspot_password_default ? (["hotspot"] as Step[]) : []),
  ]);
  const [index, setIndex] = useState(0);
  // Once the hotspot is saved there is nothing left to skip, only "Finish".
  const [saved, setSaved] = useState(false);

  const next = () => (index + 1 < steps.length ? setIndex(index + 1) : onClose());
  const step = steps[index];
  if (!step) return null;

  return (
    <div className="access wide">
      <p className="muted small">Set up Midwire · step {index + 1} of {steps.length}</p>
      {step === "admin" && (
        <>
          <h1>Choose an admin password</h1>
          <p>
            This device still uses the password <code>admin</code>. Anyone who can reach it, over the hotspot or
            the network, can log in and control the USB proxy.
          </p>
          <PasswordForm current="admin" submitLabel="Save and continue" onChanged={next} />
        </>
      )}
      {step === "hotspot" && <HotspotStep onDone={onClose} onSaved={() => setSaved(true)} />}
      {!saved && (
        <button className="quiet" onClick={next}>
          {index + 1 < steps.length ? "Skip this step" : "Skip for now"}
        </button>
      )}
    </div>
  );
}

function HotspotStep({ onDone, onSaved }: { onDone: () => void; onSaved: () => void }) {
  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<NetworkStatus>("/network")
      .then((n) => setSsid((current) => current || n.hotspot?.ssid || ""))
      .catch(() => undefined);
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (password.length < 8 || password.length > 63) return setError("A Wi-Fi password is 8 to 63 characters.");
    if (password !== repeat) return setError("The two passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      await api.put("/network/hotspot", { ssid, password });
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };

  if (saved) {
    return (
      <>
        <h1>Hotspot updated</h1>
        <p className="notice">
          The hotspot "{ssid}" is restarting with the new password. If you are connected through it, join it again
          with the new password and reopen this page.
        </p>
        <button className="primary" onClick={onDone}>Finish</button>
      </>
    );
  }

  return (
    <>
      <h1>Secure the Wi-Fi hotspot</h1>
      <p>
        Every new Midwire starts with the same hotspot password, so anyone nearby who knows it can join. Choose
        your own.
      </p>
      <form className="stack" onSubmit={submit}>
        <label>
          Network name
          <input value={ssid} maxLength={32} onChange={(e) => setSsid(e.target.value)} />
        </label>
        <label>
          New hotspot password
          <input type="password" autoComplete="new-password" value={password}
            onChange={(e) => setPassword(e.target.value)} />
        </label>
        <label>
          Repeat password
          <input type="password" autoComplete="new-password" value={repeat}
            onChange={(e) => setRepeat(e.target.value)} />
        </label>
        <p className="muted small">
          Saving disconnects everything on the hotspot. Ethernet and other Wi-Fi networks are not affected.
        </p>
        {error && <p className="notice bad">{error}</p>}
        <button className="primary" disabled={busy || !ssid || !password}>Save hotspot</button>
      </form>
    </>
  );
}
