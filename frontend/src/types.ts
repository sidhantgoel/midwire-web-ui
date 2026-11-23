// Shapes returned by the backend (midwire_web_ui/app.py).

export interface Session {
  authenticated: boolean;
  // Still admin / admin. The page offers to change it.
  default_password: boolean;
  username: string;
  version: string;
}

export interface UsbInterface {
  number: number;
  class_code: number;
  class_name: string;
  name: string | null;
  driver: string | null;
  endpoints_in: number;
  endpoints_out: number;
}

export interface Device {
  id: string;
  bus: number | null;
  address: number | null;
  vendor_id: string;
  product_id: string;
  manufacturer: string | null;
  product: string | null;
  serial: string | null;
  speed: string | null;
  interfaces: UsbInterface[];
  // The drive the system boots from. It cannot be proxied.
  system: boolean;
  // Network interfaces the Pi has brought up on this device.
  network_interfaces: string[];
  warnings: string[];
}

export interface Udc {
  name: string;
  driver: string;
  state: string | null;
}

export interface ProxyStatus {
  state: string;
  result?: string | null;
  exit_status?: number | null;
  pid?: number | null;
  since?: number | null;
  args?: string[];
  capture?: string | null;
  error?: string;
}

export interface ProxyOptions {
  hide_interfaces: number[];
  auto_remap_endpoints: boolean;
  iso_batch_size: number | null;
  injection_file: string | null;
  customized_config: boolean;
  capture: boolean;
  verbose: number;
}

export const DEFAULT_OPTIONS: ProxyOptions = {
  hide_interfaces: [],
  auto_remap_endpoints: false,
  iso_batch_size: null,
  injection_file: null,
  customized_config: false,
  capture: false,
  verbose: 0,
};

export interface Preferences {
  autostart: { enabled: boolean; known_only: boolean };
  udc: string | null;
  defaults: ProxyOptions;
  // Last options used per device, keyed "vendor:product".
  profiles: Record<string, ProxyOptions>;
}

export interface Capture {
  name: string;
  size: number;
  modified: number;
}

export interface Outcome {
  time: number;
  ok: boolean;
  message: string;
}

export interface AppState {
  // The Pi's network interface this browser's connection arrives on.
  page_interface: string | null;
  // The Pi's interface on the network link over the USB-C cable, while that
  // link is up.
  usb_link_interface: string | null;
  raw_gadget: boolean;
  udcs: Udc[];
  devices: Device[];
  injection_files: string[];
  status: ProxyStatus;
  captures: Capture[];
  preferences: Preferences;
  autostart: Outcome | null;
}

export interface NetworkStatus {
  available: boolean;
  error?: string;
  busy: boolean;
  last: Outcome | null;
  wifi?: {
    interface: string;
    present: boolean;
    mode: "hotspot" | "client" | "off";
    state: string | null;
    ssid: string | null;
    addresses: string[];
  };
  hotspot?: { ssid: string | null };
  client?: { ssid: string } | null;
  ethernet?: { interface: string; state: string; connection: string | null; addresses: string[] }[];
}

export interface UpdatePackage {
  name: string;
  installed: string | null;
  available: string | null;
  upgradable: boolean;
}

// From the midwire-base package's updater, by way of /api/updates.
export interface UpdateStatus {
  // False on a device that does not have the updater; `reason` says why.
  supported: boolean;
  reason?: string;
  state?: "idle" | "checking" | "installing";
  checked?: number | null;
  check_error?: string | null;
  packages?: UpdatePackage[];
  update_available?: boolean;
  last_install?: {
    time: number | null;
    ok: boolean;
    message: string;
    upgraded: { name: string; from: string | null; to: string | null }[];
  } | null;
}

export interface SshKey {
  type: string;
  fingerprint: string;
  comment: string;
  // The key line carries options such as command="...", added outside this page.
  restricted: boolean;
}

export interface SystemUser {
  name: string;
  has_password: boolean;
  sudo: boolean;
  keys: SshKey[];
}

// From midwire-base's system helper, by way of /api/system.
export interface SystemStatus {
  // False on a device whose midwire-base has no helper; `reason` says why.
  supported: boolean;
  reason?: string;
  // True while the admin password is the default or empty: passwords and
  // keys cannot be changed until it is a real one.
  locked: boolean;
  ssh?: { installed: boolean; enabled: boolean; running: boolean };
  // The network link over the USB-C port while the proxy is idle. Null on a
  // device whose midwire-base is older than that feature. "active" is false
  // while the proxy has the port.
  net_gadget?: { installed: boolean; enabled: boolean; active: boolean } | null;
  users?: SystemUser[];
}

// What is still on its factory default, for the setup wizard and reminders.
export interface SetupStatus {
  admin_password_default: boolean;
  hotspot_password_default: boolean;
}

export interface WifiNetwork {
  ssid: string;
  signal: number;
  secured: boolean;
}
