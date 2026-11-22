import { useCallback, useEffect, useState, type FormEvent } from "react";

import { api, message } from "../api";
import { dateTime } from "../format";
import type { NetworkStatus, WifiNetwork } from "../types";

const POLL_MS = 5000;

export function NetworkPage({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState<NetworkStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Shown after asking for a change that will probably cut this connection.
  const [pending, setPending] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await api.get<NetworkStatus>("/network"));
      setError(null);
    } catch (err) {
      setError(message(err));
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => {
      if (!document.hidden) void load();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  if (!status) {
    return error ? <p className="notice bad">{error}</p> : <p className="muted">Loading…</p>;
  }
  if (!status.available) {
    return <p className="notice bad">Network settings are unavailable: {status.error}</p>;
  }

  const wifi = status.wifi!;
  const change = async (text: string, work: () => Promise<unknown>) => {
    try {
      await work();
      setPending(text);
      // The hotspot reminder at the top of the page may no longer apply.
      // The change is made a moment after the request returns.
      setTimeout(onChanged, 4000);
    } catch (err) {
      setPending(null);
      setError(message(err));
    }
  };

  return (
    <>
      {error && <p className="notice warn">Cannot reach the device right now: {error}</p>}
      {pending && (
        <p className="notice warn">
          {pending} If this page stops responding, connect to the new network and open{" "}
          <code>http://midwire.local</code> again.
        </p>
      )}
      {status.last && (
        <p className={status.last.ok ? "notice" : "notice bad"}>
          Last change, {dateTime(status.last.time)}: {status.last.message}
        </p>
      )}

      <section className="card">
        <div className="card-head">
          <h2>Connections</h2>
          {status.busy && <span className="badge on">Changing…</span>}
        </div>
        <dl className="facts">
          <dt>Wi-Fi</dt>
          <dd>
            {!wifi.present && "No Wi-Fi adapter found"}
            {wifi.present && wifi.mode === "hotspot" && `Hosting hotspot "${wifi.ssid}"`}
            {wifi.present && wifi.mode === "client" && `Connected to "${wifi.ssid}"`}
            {wifi.present && wifi.mode === "off" && "Not connected"}
            {wifi.addresses.length > 0 && <span className="muted"> · {wifi.addresses.join(", ")}</span>}
          </dd>
          {(status.ethernet ?? []).map((eth) => (
            <FactRow key={eth.interface} label={`Ethernet (${eth.interface})`}
              value={eth.addresses.length ? `${eth.state} · ${eth.addresses.join(", ")}` : eth.state} />
          ))}
        </dl>
        <p className="muted small">
          Ethernet keeps working whatever you change here. Plug a cable straight into a computer and the Pi gives
          it an address.
        </p>
      </section>

      {wifi.present && (
        <>
          <HotspotCard ssid={status.hotspot?.ssid ?? ""} active={wifi.mode === "hotspot"} busy={status.busy}
            onChange={change} />
          <JoinCard joined={status.client?.ssid ?? null} busy={status.busy} onChange={change} />
        </>
      )}
    </>
  );
}

function FactRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

type Change = (text: string, work: () => Promise<unknown>) => Promise<void>;

function HotspotCard(props: { ssid: string; active: boolean; busy: boolean; onChange: Change }) {
  const [ssid, setSsid] = useState(props.ssid);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Follow a rename made elsewhere, unless the user is typing.
  useEffect(() => setSsid(props.ssid), [props.ssid]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (password && (password.length < 8 || password.length > 63)) {
      return setError("A Wi-Fi password is 8 to 63 characters.");
    }
    setError(null);
    void props.onChange(
      props.active ? `The hotspot is restarting as "${ssid}".` : "Hotspot settings are being saved.",
      () => api.put("/network/hotspot", { ssid, password: password || null }),
    );
    setPassword("");
  };

  return (
    <form className="card" onSubmit={submit}>
      <div className="card-head">
        <h2>Hotspot</h2>
        {props.active && <span className="badge on">On</span>}
      </div>
      <label>
        Network name
        <input value={ssid} maxLength={32} onChange={(e) => setSsid(e.target.value)} />
      </label>
      <label>
        New password
        <input type="password" autoComplete="new-password" placeholder="Leave empty to keep the current one"
          value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>
      {props.active && (
        <p className="muted small">Saving disconnects everything on the hotspot. Rejoin it with the new details.</p>
      )}
      {error && <p className="notice bad">{error}</p>}
      <button disabled={props.busy || !ssid}>Save hotspot</button>
    </form>
  );
}

function JoinCard(props: { joined: string | null; busy: boolean; onChange: Change }) {
  const [networks, setNetworks] = useState<WifiNetwork[] | null>(null);
  const [scanning, setScanning] = useState(false);
  const [ssid, setSsid] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const scan = async () => {
    setScanning(true);
    setError(null);
    try {
      setNetworks(await api.get<WifiNetwork[]>("/network/scan"));
    } catch (err) {
      setError(message(err));
    } finally {
      setScanning(false);
    }
  };

  const chosen = networks?.find((n) => n.ssid === ssid);
  const needsPassword = chosen ? chosen.secured : true;

  const join = (event: FormEvent) => {
    event.preventDefault();
    void props.onChange(`Joining "${ssid}". The hotspot turns off while this happens.`, () =>
      api.put("/network/wifi", { ssid, password: password || null }),
    );
    setPassword("");
  };

  return (
    <form className="card" onSubmit={join}>
      <div className="card-head">
        <h2>Join an existing Wi-Fi network</h2>
        {props.joined && <span className="badge on">Using "{props.joined}"</span>}
      </div>
      <p className="muted small">
        The Pi joins that network instead of hosting its hotspot. If joining fails, or the network is out of range
        at power-on, the hotspot comes back by itself.
      </p>
      <div className="row">
        <button type="button" disabled={scanning} onClick={() => void scan()}>
          {scanning ? "Scanning…" : "Scan for networks"}
        </button>
        {props.joined && (
          <button type="button" className="quiet" disabled={props.busy}
            onClick={() => void props.onChange("Switching back to the hotspot.", () => api.delete("/network/wifi"))}>
            Forget "{props.joined}" and use the hotspot
          </button>
        )}
      </div>
      {networks && networks.length === 0 && <p className="muted">No networks found.</p>}
      {networks && networks.length > 0 && (
        <ul className="devices">
          {networks.map((n) => (
            <li key={n.ssid}>
              <label className={n.ssid === ssid ? "device selected" : "device"}>
                <input type="radio" name="network" checked={n.ssid === ssid} onChange={() => setSsid(n.ssid)} />
                <span className="device-body">
                  <strong>{n.ssid}</strong>
                  <span className="muted small">
                    Signal {n.signal}% · {n.secured ? "password needed" : "open"}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <label>
        Network name
        <input value={ssid} maxLength={32} placeholder="Pick from a scan, or type a hidden network's name"
          onChange={(e) => setSsid(e.target.value)} />
      </label>
      {needsPassword && (
        <label>
          Password
          <input type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
      )}
      {error && <p className="notice bad">{error}</p>}
      <button className="primary" disabled={props.busy || !ssid || (needsPassword && password.length < 8)}>
        Join network
      </button>
    </form>
  );
}
