import type { ProxyOptions } from "../types";

interface Props {
  options: ProxyOptions;
  onChange: (options: ProxyOptions) => void;
  injectionFiles: string[];
  disabled?: boolean;
}

// The usb-proxy options that apply to any device. Hiding interfaces is
// per device, so the proxy page adds that itself.
export function OptionFields({ options, onChange, injectionFiles, disabled }: Props) {
  const set = (patch: Partial<ProxyOptions>) => onChange({ ...options, ...patch });

  return (
    <fieldset className="options" disabled={disabled}>
      <label className="check">
        <input type="checkbox" checked={options.capture} onChange={(e) => set({ capture: e.target.checked })} />
        <span>
          Capture traffic to a file
          <small>Saved as a .pcap you can open in Wireshark. Isochronous (audio/video) data is not captured.</small>
        </span>
      </label>
      <label className="check">
        <input type="checkbox" checked={options.auto_remap_endpoints}
          onChange={(e) => set({ auto_remap_endpoints: e.target.checked })} />
        <span>
          Remap endpoints automatically
          <small>Needed when the device uses endpoint numbers the Pi's USB-C port cannot provide.</small>
        </span>
      </label>
      <label>
        Injection rules
        <select value={options.injection_file ?? ""}
          onChange={(e) => set({ injection_file: e.target.value || null })}>
          <option value="">None (pass traffic through unchanged)</option>
          {injectionFiles.map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
        </select>
        <small>Rule files live in /etc/usb-proxy on the device.</small>
      </label>
      <details>
        <summary>Advanced</summary>
        <label>
          Log detail
          <select value={options.verbose} onChange={(e) => set({ verbose: Number(e.target.value) })}>
            <option value={0}>Normal</option>
            <option value={1}>Verbose</option>
            <option value={2}>Very verbose (prints packet data)</option>
          </select>
        </label>
        <label>
          Isochronous packets per transfer
          <input type="number" min={1} max={32} placeholder="Default (8)" value={options.iso_batch_size ?? ""}
            onChange={(e) => set({ iso_batch_size: e.target.value ? Number(e.target.value) : null })} />
        </label>
        <label className="check">
          <input type="checkbox" checked={options.customized_config}
            onChange={(e) => set({ customized_config: e.target.checked })} />
          <span>
            Apply /etc/usb-proxy/config.json
            <small>Device quirks: skip the reset before proxying, small control packet sizes.</small>
          </span>
        </label>
      </details>
    </fieldset>
  );
}
