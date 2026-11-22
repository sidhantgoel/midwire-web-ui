# midwire-web-ui

The web UI for [Midwire](https://github.com/sidhantgoel/midwire), a Raspberry Pi image that turns a Pi 4 or 5 into a USB proxy. It drives [usb-proxy](https://github.com/sidhantgoel/usb-proxy) through the systemd unit that package installs.

What it does:

- **Proxy.** Lists the USB devices on the Pi's host ports, lets you hide interfaces and pick options, then starts and stops `usb-proxy.service`. Shows the proxy's log live and serves the `.pcap` captures it writes.
- **Settings.** Saved across reboots: start the proxy automatically when a device is plugged in, default options, and the options last used for each device. When auto-start leaves an arriving device alone, the Proxy page says why.
- **Network.** Rename the Wi-Fi hotspot or change its password, or join an existing Wi-Fi network instead. If joining fails, the hotspot comes back.

A new install logs in with `admin` / `admin`. The page offers to change the password after the first login and shows a reminder until it is changed. An empty password is allowed. If the password is lost, run `sudo midwire-web-ui set-password` on the device.

## How it is built

| Part | Where | Notes |
|---|---|---|
| Backend | `midwire_web_ui/` | FastAPI. Runs on the Python packages Debian trixie ships, so the `.deb` needs nothing from PyPI. |
| Frontend | `frontend/` | React and TypeScript, built with Vite into `midwire_web_ui/static/`. Nothing from Node runs on the Pi. |
| Packaging | `debian/`, `packaging/` | An arch-independent `.deb` with the service, its user and a polkit rule. |

The backend never passes free text to `usb-proxy`. A start request names a device and a gadget controller by the ids the server itself read from sysfs, plus booleans and bounded numbers; the server builds the arguments and writes them to `/run/usb-proxy/args`, which the `usb-proxy` package's launcher reads.

## Development

Run the tests (Linux; the fake sysfs tree uses symlinks):

```
pip install fastapi uvicorn httpx pytest
python3 -m pytest
```

Preview the UI without a Pi. `dev/serve_fake.py` serves the built frontend against a fake sysfs tree and stand-ins for `systemctl`, `journalctl` and `nmcli`:

```
cd frontend && npm ci && npm run build && cd ..
python3 dev/serve_fake.py        # http://127.0.0.1:8080, admin / admin
```

For frontend work with hot reload, keep that running and start `npm run dev` in `frontend/`. Vite proxies `/api` to port 8080.

## Building the package

```
cd frontend && npm ci && npm run build && cd ..
sudo apt install build-essential devscripts equivs
sudo mk-build-deps --install --remove debian/control
dpkg-buildpackage -b -us -uc
```

GitHub Actions does the same on every push, and attaches the `.deb` to the release when you push a `v<version>` tag that matches `debian/changelog`.

## What the package sets up

| Path | Purpose |
|---|---|
| `/etc/midwire-web-ui/webui.env` | Listen address and ports (default: HTTP on 80, HTTPS on 443) |
| `/var/lib/midwire-web-ui/` | Admin password hash, saved settings, and the HTTPS certificate in `tls/` |
| `midwire-web-ui` user | Runs the service. Member of `usbproxy-ctl` (may start and stop the proxy) and `systemd-journal` (may read its log) |
| polkit rule | Lets that user change NetworkManager connections |

Runtime configuration is read from `MIDWIRE_WEBUI_*` environment variables; see `midwire_web_ui/config.py`.

## HTTPS

The service listens on HTTP and HTTPS at once. The Pi has no public name, so on first start it creates a self-signed certificate for `<hostname>.local` and the image's fixed addresses (`10.42.0.1`, `10.42.1.1`). Browsers show a warning for it once. It is renewed automatically before it expires.

To use your own certificate, replace `cert.pem` and `key.pem` in `/var/lib/midwire-web-ui/tls/` and delete `cert.pem.self-signed`; a certificate without that marker is never touched.

## Network profiles

The Network page edits NetworkManager profiles by name, which the Midwire image creates:

- `midwire-hotspot`: the Wi-Fi access point, with a low autoconnect priority (-10) so it is the fallback.
- `midwire-wifi`: created when you join an existing network, with a higher autoconnect priority than the hotspot. At power-on NetworkManager tries it first and falls back to the hotspot when that network is out of range.

## License

MIT. See [LICENSE](LICENSE).
