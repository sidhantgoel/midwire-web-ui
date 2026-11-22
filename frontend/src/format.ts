import type { Device, ProxyOptions } from "./types";

export function deviceName(device: Device): string {
  const name = [device.manufacturer, device.product].filter(Boolean).join(" ");
  return name || `${device.vendor_id}:${device.product_id}`;
}

export function profileKey(device: Device): string {
  return `${device.vendor_id}:${device.product_id}`;
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function dateTime(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString();
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.max(0, Math.floor(seconds))} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
}

// One line saying what a saved set of options does.
export function summarize(options: ProxyOptions): string {
  const parts: string[] = [];
  if (options.hide_interfaces.length) parts.push(`hides interface ${options.hide_interfaces.join(", ")}`);
  if (options.capture) parts.push("captures traffic");
  if (options.auto_remap_endpoints) parts.push("remaps endpoints");
  if (options.injection_file) parts.push(`rules: ${options.injection_file}`);
  if (options.customized_config) parts.push("config.json");
  if (options.verbose) parts.push("verbose log");
  if (options.iso_batch_size) parts.push(`iso batch ${options.iso_batch_size}`);
  return parts.length ? parts.join(" · ") : "no special options";
}
