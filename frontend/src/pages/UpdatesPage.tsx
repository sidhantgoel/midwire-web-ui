import { useCallback, useEffect, useState } from "react";

import { api, message } from "../api";
import { LogPanel } from "../components/LogPanel";
import { dateTime } from "../format";
import type { UpdateStatus } from "../types";

const POLL_MS = 3000;

export function UpdatesPage({ onChange }: { onChange: (status: UpdateStatus) => void }) {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // Set from the click until the updater is seen running, so the buttons do
  // not flicker back on in between.
  const [asked, setAsked] = useState<"check" | "install" | null>(null);

  const load = useCallback(async () => {
    try {
      const fresh = await api.get<UpdateStatus>("/updates");
      setStatus(fresh);
      onChange(fresh);
      setError(null);
      if (fresh.state !== "idle") setAsked(null);
    } catch (err) {
      // Expected for a moment during an install: the web UI's own package
      // is replaced and the service restarts.
      setError(message(err));
    }
  }, [onChange]);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  if (!status) {
    return error ? <p className="notice bad">{error}</p> : <p className="muted">Loading…</p>;
  }
  if (!status.supported) {
    return (
      <section className="card">
        <div className="card-head">
          <h2>Updates</h2>
        </div>
        <p className="notice warn">{status.reason}</p>
        <p className="muted small">
          Images from Midwire 0.2.0 on include it. On an older image, install the <code>midwire-base</code> package
          once; the README of the midwire repository has the command.
        </p>
      </section>
    );
  }

  const run = async (what: "check" | "install") => {
    setActionError(null);
    setAsked(what);
    try {
      await api.post(`/updates/${what}`);
      await load();
    } catch (err) {
      setAsked(null);
      setActionError(message(err));
    }
    // If the run finished before it was ever seen running, release the buttons.
    setTimeout(() => setAsked(null), 2 * POLL_MS);
  };

  const busy = status.state !== "idle" || asked !== null;
  const installing = status.state === "installing" || asked === "install";
  const packages = status.packages ?? [];

  return (
    <>
      {error && installing && (
        <p className="notice warn">
          The page is restarting as part of the update. It reconnects by itself; you may need to log in again.
        </p>
      )}
      {error && !installing && <p className="notice warn">Cannot reach the device right now: {error}</p>}

      <section className="card">
        <div className="card-head">
          <h2>Updates</h2>
          {status.state === "checking" && <span className="badge on">Checking…</span>}
          {installing && <span className="badge on">Installing…</span>}
          {!busy && status.update_available && <span className="badge on">Update available</span>}
          <span className="spacer" />
          <button disabled={busy} onClick={() => void run("check")}>Check for updates</button>
        </div>

        {packages.length === 0 ? (
          <p className="muted">No check has run yet. The device checks by itself once a day when it is online.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Package</th><th>Installed</th><th>Available</th></tr>
            </thead>
            <tbody>
              {packages.map((p) => (
                <tr key={p.name}>
                  <td>{p.name}</td>
                  <td>{p.installed ?? "not installed"}</td>
                  <td>{p.upgradable ? <strong>{p.available}</strong> : (p.available ?? "unknown")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {status.checked != null && <p className="muted small">Last checked {dateTime(status.checked)}.</p>}
        {status.check_error && (
          <p className="notice bad">
            The last check failed: {status.check_error} The Pi needs an internet connection for updates, through
            Ethernet or a Wi-Fi network it has joined.
          </p>
        )}
        {!status.check_error && packages.length > 0 && !status.update_available && !busy && (
          <p className="notice">Midwire is up to date.</p>
        )}
        {status.last_install && (
          <p className={status.last_install.ok ? "notice" : "notice bad"}>
            Last update{status.last_install.time != null ? `, ${dateTime(status.last_install.time)}` : ""}:{" "}
            {status.last_install.message}
            {status.last_install.upgraded.length > 0 &&
              ` (${status.last_install.upgraded.map((u) => `${u.name} ${u.from} to ${u.to}`).join(", ")})`}
          </p>
        )}
        {actionError && <p className="notice bad">{actionError}</p>}

        {status.update_available && (
          <>
            <p className="muted small">
              Installing takes a minute or two. This page restarts during it and may ask you to log in again. A
              running proxy keeps going on the old version until it is next started. Only Midwire's own packages
              are updated; Raspberry Pi OS is left alone.
            </p>
            <button className="primary" disabled={busy} onClick={() => void run("install")}>
              Install update
            </button>
          </>
        )}
      </section>

      {(busy || status.last_install) && (
        <LogPanel title="Update progress" url="/api/updates/log" empty="Nothing from the updater yet." />
      )}
    </>
  );
}
