"""Runtime configuration, read from MIDWIRE_WEBUI_* environment variables.

(The settings a user changes in the page are in prefs.py.) The path and
command settings exist so tests and development can point the app at a fake
sysfs tree and fake systemctl/journalctl/nmcli. On a real install the
defaults are right.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(f"MIDWIRE_WEBUI_{name}", default)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    # Admin password hash. Absent until the default (admin / admin) is changed.
    password_file: Path
    # What the user saved in the page: auto-start, defaults, per-device options.
    prefs_file: Path
    sysfs: Path
    proc_mounts: Path
    raw_gadget_dev: Path
    # Contract with the usb-proxy package: NUL-separated arguments for the
    # next run, read by /usr/lib/usb-proxy/launch.
    args_file: Path
    captures_dir: Path
    # usb-proxy's working directory: injection rule files live here.
    config_dir: Path
    unit: str
    wifi_interface: str
    systemctl: tuple[str, ...]
    journalctl: tuple[str, ...]
    nmcli: tuple[str, ...]
    # HTTPS is served next to HTTP when tls_port is set. 0 turns it off.
    tls_port: int = 0
    tls_cert: Path | None = None
    tls_key: Path | None = None
    # Contract with the midwire-base package: the status file its updater
    # writes, and the two services that run it.
    update_status_file: Path = Path("/var/lib/midwire/update.json")
    update_check_unit: str = "midwire-update-check.service"
    update_install_unit: str = "midwire-update-install.service"
    # midwire-base's helper for SSH and login accounts.
    system_socket: Path = Path("/run/midwire/system.sock")
    # The image's first-boot settings. Read for the hotspot's default
    # password, to tell whether the user has changed it.
    firstboot_conf: Path = Path("/etc/midwire/firstboot.conf")

    @classmethod
    def from_env(cls) -> "Settings":
        state = Path(_env("STATE_DIR", "/var/lib/midwire-web-ui"))
        return cls(
            host=_env("HOST", "127.0.0.1"),
            port=int(_env("PORT", "8080")),
            password_file=Path(_env("PASSWORD_FILE", str(state / "password"))),
            prefs_file=Path(_env("PREFS_FILE", str(state / "settings.json"))),
            sysfs=Path(_env("SYSFS", "/sys")),
            proc_mounts=Path(_env("PROC_MOUNTS", "/proc/mounts")),
            raw_gadget_dev=Path(_env("RAW_GADGET_DEV", "/dev/raw-gadget")),
            args_file=Path(_env("ARGS_FILE", "/run/usb-proxy/args")),
            captures_dir=Path(_env("CAPTURES_DIR", "/var/lib/usb-proxy/captures")),
            config_dir=Path(_env("CONFIG_DIR", "/etc/usb-proxy")),
            unit=_env("UNIT", "usb-proxy.service"),
            wifi_interface=_env("WIFI_INTERFACE", "wlan0"),
            systemctl=tuple(shlex.split(_env("SYSTEMCTL", "systemctl"))),
            journalctl=tuple(shlex.split(_env("JOURNALCTL", "journalctl"))),
            nmcli=tuple(shlex.split(_env("NMCLI", "nmcli"))),
            tls_port=int(_env("TLS_PORT", "0")),
            tls_cert=Path(_env("TLS_CERT", str(state / "tls" / "cert.pem"))),
            tls_key=Path(_env("TLS_KEY", str(state / "tls" / "key.pem"))),
            update_status_file=Path(_env("UPDATE_STATUS_FILE", "/var/lib/midwire/update.json")),
            update_check_unit=_env("UPDATE_CHECK_UNIT", "midwire-update-check.service"),
            update_install_unit=_env("UPDATE_INSTALL_UNIT", "midwire-update-install.service"),
            system_socket=Path(_env("SYSTEM_SOCKET", "/run/midwire/system.sock")),
            firstboot_conf=Path(_env("FIRSTBOOT_CONF", "/etc/midwire/firstboot.conf")),
        )
