import { useCallback, useEffect, useState } from "react";

import { api, message, setLoggedOutHandler } from "./api";
import { Login } from "./pages/Access";
import { NetworkPage } from "./pages/NetworkPage";
import { ProxyPage } from "./pages/ProxyPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SetupWizard } from "./pages/SetupWizard";
import { UpdatesPage } from "./pages/UpdatesPage";
import type { Session, SetupStatus, UpdateStatus } from "./types";

type Tab = "proxy" | "settings" | "network" | "updates";
const TABS: { id: Tab; label: string }[] = [
  { id: "proxy", label: "Proxy" },
  { id: "settings", label: "Settings" },
  { id: "network", label: "Network" },
  { id: "updates", label: "Updates" },
];

// Remembered per browser tab, so the setup wizard is offered once per login
// rather than on every page load. The reminders stay either way.
const SKIP_KEY = "midwire-skip-setup";
// How often to look for a finished daily check, for the dot on the tab.
const UPDATE_POLL_MS = 60_000;

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [setup, setSetup] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("proxy");
  const [skipped, setSkipped] = useState(() => sessionStorage.getItem(SKIP_KEY) === "1");
  const [updateAvailable, setUpdateAvailable] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const fresh = await api.get<Session>("/session");
      setSession(fresh);
      setError(null);
      // What is still on a factory default: drives the wizard and reminders.
      setSetup(fresh.authenticated ? await api.get<SetupStatus>("/setup").catch(() => null) : null);
    } catch (err) {
      setError(message(err));
    }
  }, []);

  useEffect(() => {
    // Any API call that finds the session gone brings back the login page.
    setLoggedOutHandler(() => void refresh());
    void refresh();
  }, [refresh]);

  const noteUpdates = useCallback((status: UpdateStatus) => {
    setUpdateAvailable(status.supported && status.update_available === true);
  }, []);

  const authenticated = session?.authenticated === true;
  useEffect(() => {
    if (!authenticated) return;
    const look = () => api.get<UpdateStatus>("/updates").then(noteUpdates).catch(() => undefined);
    void look();
    const timer = setInterval(() => void look(), UPDATE_POLL_MS);
    return () => clearInterval(timer);
  }, [authenticated, noteUpdates]);

  if (!session) {
    return (
      <div className="access">
        <h1>Midwire</h1>
        {error ? <p className="notice bad">{error}</p> : <p className="muted">Loading…</p>}
        {error && <button onClick={() => void refresh()}>Try again</button>}
      </div>
    );
  }
  if (!session.authenticated) {
    return <Login defaultPassword={session.default_password} onDone={refresh} />;
  }

  const closeWizard = () => {
    sessionStorage.setItem(SKIP_KEY, "1");
    setSkipped(true);
    void refresh();
  };
  if (setup && !skipped && (setup.admin_password_default || setup.hotspot_password_default)) {
    return <SetupWizard setup={setup} onClose={closeWizard} />;
  }

  const logout = async () => {
    await api.post("/logout").catch(() => undefined);
    sessionStorage.removeItem(SKIP_KEY);
    setSkipped(false);
    await refresh();
  };

  return (
    <>
      <header className="topbar">
        <span className="brand">Midwire</span>
        <nav>
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? "tab active" : "tab"} onClick={() => setTab(t.id)}>
              {t.label}
              {t.id === "updates" && updateAvailable && <span className="dot ok tab-dot" title="Update available" />}
            </button>
          ))}
        </nav>
        <span className="muted version">v{session.version}</span>
        <button className="quiet" onClick={() => void logout()}>
          Log out
        </button>
      </header>
      <main>
        {setup?.admin_password_default && (
          <p className="notice warn">
            The admin password is still the default (<code>admin</code>).{" "}
            <button className="link" onClick={() => setTab("settings")}>Change it in Settings</button>
          </p>
        )}
        {setup?.hotspot_password_default && (
          <p className="notice warn">
            The Wi-Fi hotspot still has the password every new Midwire starts with.{" "}
            <button className="link" onClick={() => setTab("network")}>Change it on the Network tab</button>
          </p>
        )}
        {tab === "proxy" && <ProxyPage />}
        {tab === "settings" && <SettingsPage onPasswordChanged={refresh} />}
        {tab === "network" && <NetworkPage onChanged={refresh} />}
        {tab === "updates" && <UpdatesPage onChange={noteUpdates} />}
      </main>
    </>
  );
}
