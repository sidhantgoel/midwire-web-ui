import { useCallback, useEffect, useState } from "react";

import { api, message, setLoggedOutHandler } from "./api";
import { FirstLogin, Login } from "./pages/Access";
import { NetworkPage } from "./pages/NetworkPage";
import { ProxyPage } from "./pages/ProxyPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { Session } from "./types";

type Tab = "proxy" | "settings" | "network";
const TABS: { id: Tab; label: string }[] = [
  { id: "proxy", label: "Proxy" },
  { id: "settings", label: "Settings" },
  { id: "network", label: "Network" },
];

// Remembered per browser tab, so "keep the default for now" is asked once
// per login rather than on every page load.
const SKIP_KEY = "midwire-skip-password-change";

export function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("proxy");
  const [skipped, setSkipped] = useState(() => sessionStorage.getItem(SKIP_KEY) === "1");

  const refresh = useCallback(async () => {
    try {
      setSession(await api.get<Session>("/session"));
      setError(null);
    } catch (err) {
      setError(message(err));
    }
  }, []);

  useEffect(() => {
    // Any API call that finds the session gone brings back the login page.
    setLoggedOutHandler(() => void refresh());
    void refresh();
  }, [refresh]);

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

  const skip = () => {
    sessionStorage.setItem(SKIP_KEY, "1");
    setSkipped(true);
  };
  if (session.default_password && !skipped) {
    return <FirstLogin onChanged={refresh} onSkip={skip} />;
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
            </button>
          ))}
        </nav>
        <span className="muted version">v{session.version}</span>
        <button className="quiet" onClick={() => void logout()}>
          Log out
        </button>
      </header>
      <main>
        {session.default_password && (
          <p className="notice warn">
            The admin password is still the default (<code>admin</code>).{" "}
            <button className="link" onClick={() => setTab("settings")}>Change it in Settings</button>
          </p>
        )}
        {tab === "proxy" && <ProxyPage />}
        {tab === "settings" && <SettingsPage onPasswordChanged={refresh} />}
        {tab === "network" && <NetworkPage />}
      </main>
    </>
  );
}
