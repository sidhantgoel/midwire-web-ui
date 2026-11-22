import { useCallback, useEffect, useMemo, useState } from "react";

import { api, message } from "../api";
import { LogPanel } from "../components/LogPanel";
import { OptionFields } from "../components/OptionFields";
import { dateTime, deviceName, duration, fileSize, profileKey } from "../format";
import { DEFAULT_OPTIONS, type AppState, type Device, type ProxyOptions } from "../types";

const POLL_MS = 2000;
const RUNNING = ["active", "activating", "deactivating"];

export function ProxyPage() {
  const [state, setState] = useState<AppState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [udc, setUdc] = useState<string | null>(null);
  const [options, setOptions] = useState<ProxyOptions>(DEFAULT_OPTIONS);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setState(await api.get<AppState>("/state"));
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

  const device = useMemo(
    () => state?.devices.find((d) => d.id === selected) ?? null,
    [state, selected],
  );
  // The picked device was unplugged.
  useEffect(() => {
    if (state && selected && !device) setSelected(null);
  }, [state, selected, device]);

  if (!state) {
    return error ? <p className="notice bad">{error}</p> : <p className="muted">Loading…</p>;
  }

  const running = RUNNING.includes(state.status.state);
  const chosenUdc = udc && state.udcs.some((u) => u.name === udc) ? udc : (state.udcs[0]?.name ?? null);

  const pick = (d: Device) => {
    setSelected(d.id);
    setActionError(null);
    // Start from what was used for this device last time, else the defaults.
    const saved = state.preferences.profiles[profileKey(d)];
    setOptions(saved ?? { ...state.preferences.defaults, hide_interfaces: [] });
  };

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setActionError(null);
    try {
      await work();
    } catch (err) {
      setActionError(message(err));
    } finally {
      await load();
      setBusy(false);
    }
  };

  const start = () =>
    act(() => api.post("/start", { device_id: selected, udc: chosenUdc, ...options }));
  const stop = () => act(() => api.post("/stop"));
  const removeCapture = (name: string) =>
    act(() => api.delete(`/captures/${encodeURIComponent(name)}`));

  const toggleHidden = (number: number) => {
    const hidden = options.hide_interfaces.includes(number)
      ? options.hide_interfaces.filter((n) => n !== number)
      : [...options.hide_interfaces, number].sort((a, b) => a - b);
    setOptions({ ...options, hide_interfaces: hidden });
  };

  const proxied = running ? findProxied(state) : null;
  const allHidden = device ? device.interfaces.length > 0 && options.hide_interfaces.length >= device.interfaces.length : false;

  return (
    <>
      {error && <p className="notice bad">Lost contact with the device: {error}</p>}
      {!state.raw_gadget && (
        <p className="notice bad">
          The raw_gadget kernel module is not loaded, so the proxy cannot start. Run{" "}
          <code>sudo modprobe raw_gadget</code> on the device.
        </p>
      )}
      {state.udcs.length === 0 && (
        <p className="notice bad">
          No USB gadget controller was found. Check that <code>dtoverlay=dwc2,dr_mode=peripheral</code> is in{" "}
          <code>/boot/firmware/config.txt</code>, then reboot.
        </p>
      )}
      {state.status.error && <p className="notice bad">{state.status.error}</p>}

      <section className="card">
        <div className="card-head">
          <h2>Proxy</h2>
          <span className={running ? "badge on" : "badge"}>{running ? "Running" : "Stopped"}</span>
          <span className="spacer" />
          {running && (
            <button className="danger" disabled={busy} onClick={() => void stop()}>
              Stop
            </button>
          )}
        </div>
        {running ? (
          <dl className="facts">
            <dt>Device</dt>
            <dd>{proxied ?? "Unknown device"}</dd>
            {state.status.since != null && (
              <>
                <dt>Running for</dt>
                <dd>{duration(Date.now() / 1000 - state.status.since)}</dd>
              </>
            )}
            {state.status.capture && (
              <>
                <dt>Capturing to</dt>
                <dd>{state.status.capture}</dd>
              </>
            )}
            <dt>Command</dt>
            <dd><code>usb-proxy {(state.status.args ?? []).join(" ")}</code></dd>
          </dl>
        ) : (
          <p className="muted">
            {state.status.result && state.status.result !== "success"
              ? `The last run ended with an error (${state.status.result}). See the log below.`
              : "Pick a device below and start the proxy."}
          </p>
        )}
        {state.autostart && (
          <p className={state.autostart.ok ? "notice" : "notice warn"}>
            Auto-start, {dateTime(state.autostart.time)}: {state.autostart.message}
          </p>
        )}
        {actionError && <p className="notice bad">{actionError}</p>}
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Devices on the Pi's USB ports</h2>
        </div>
        {state.devices.length === 0 && <p className="muted">Nothing is plugged in.</p>}
        <ul className="devices">
          {state.devices.map((d) => (
            <li key={d.id}>
              <label className={d.id === selected ? "device selected" : "device"}>
                <input type="radio" name="device" checked={d.id === selected} disabled={d.system || running}
                  onChange={() => pick(d)} />
                <span className="device-body">
                  <strong>{deviceName(d)}</strong>
                  <span className="muted small">
                    {d.vendor_id}:{d.product_id} · bus {d.bus} device {d.address} ·{" "}
                    {d.interfaces.map((i) => i.class_name).filter((v, i, a) => a.indexOf(v) === i).join(", ") || "no interfaces"}
                  </span>
                  {d.warnings.map((w) => (
                    <span key={w} className={d.system ? "notice bad small" : "notice warn small"}>{w}</span>
                  ))}
                  {d.network_interfaces.map((name) =>
                    name === state.page_interface ? (
                      // Only this case can lock the user out, so only this one warns.
                      <span key={name} className="notice bad small">
                        You are reaching this page through {name}, which runs on this device. Proxying it will
                        disconnect you. Connect over Wi-Fi or the Pi's own Ethernet port first.
                      </span>
                    ) : (
                      <span key={name} className="muted small">
                        The Pi also uses this device as network interface {name}. That goes away while it is
                        proxied; this page is not affected.
                      </span>
                    ),
                  )}
                </span>
              </label>
            </li>
          ))}
        </ul>
      </section>

      {device && !running && (
        <section className="card">
          <div className="card-head">
            <h2>Options for {deviceName(device)}</h2>
          </div>

          {state.udcs.length > 1 && (
            <label>
              Gadget controller
              <select value={chosenUdc ?? ""} onChange={(e) => setUdc(e.target.value)}>
                {state.udcs.map((u) => (
                  <option key={u.name} value={u.name}>{u.name}</option>
                ))}
              </select>
            </label>
          )}

          <h3>Interfaces</h3>
          <p className="muted small">
            The Pi's USB-C port has a limited number of endpoints. If the device needs more than it has, hide the
            interfaces you do not need from the host.
          </p>
          <table className="interfaces">
            <thead>
              <tr><th>#</th><th>Type</th><th>Endpoints</th><th>Hide from host</th></tr>
            </thead>
            <tbody>
              {device.interfaces.map((i) => (
                <tr key={i.number} className={options.hide_interfaces.includes(i.number) ? "hidden-row" : ""}>
                  <td>{i.number}</td>
                  <td>{i.name ? `${i.class_name} (${i.name})` : i.class_name}</td>
                  <td>{i.endpoints_in} in, {i.endpoints_out} out</td>
                  <td>
                    <input type="checkbox" aria-label={`Hide interface ${i.number}`}
                      checked={options.hide_interfaces.includes(i.number)} onChange={() => toggleHidden(i.number)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {allHidden && <p className="notice bad small">At least one interface must stay visible.</p>}

          <OptionFields options={options} onChange={setOptions} injectionFiles={state.injection_files} />

          <button className="primary" disabled={busy || !chosenUdc || !state.raw_gadget || allHidden}
            onClick={() => void start()}>
            Start proxy
          </button>
        </section>
      )}

      <LogPanel />

      <section className="card">
        <div className="card-head">
          <h2>Captures</h2>
        </div>
        {state.captures.length === 0 ? (
          <p className="muted">No captures yet. Tick "Capture traffic to a file" before starting.</p>
        ) : (
          <table>
            <thead>
              <tr><th>File</th><th>Size</th><th>Last written</th><th /></tr>
            </thead>
            <tbody>
              {state.captures.map((c) => (
                <tr key={c.name}>
                  <td>{c.name}</td>
                  <td>{fileSize(c.size)}</td>
                  <td>{dateTime(c.modified)}</td>
                  <td className="row-actions">
                    <a className="button" href={`/api/captures/${encodeURIComponent(c.name)}`} download>
                      Download
                    </a>
                    <button className="quiet" disabled={busy || state.status.capture === c.name}
                      title={state.status.capture === c.name ? "Being written. Stop the proxy first." : undefined}
                      onClick={() => void removeCapture(c.name)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

// Works out which attached device the running proxy has, from its arguments.
function findProxied(state: AppState): string | null {
  const arg = (name: string) =>
    state.status.args?.find((a) => a.startsWith(`--${name}=`))?.split("=")[1] ?? null;
  const vendor = arg("vendor_id");
  const product = arg("product_id");
  if (!vendor || !product) return null;
  const match = state.devices.find((d) => d.vendor_id === vendor && d.product_id === product);
  return match ? `${deviceName(match)} (${vendor}:${product})` : `${vendor}:${product}`;
}
