"""Wi-Fi settings, through NetworkManager's nmcli.

The image ships a hotspot profile, `midwire-hotspot`. Joining an existing
network creates `midwire-wifi` with a higher autoconnect priority, so at boot
NetworkManager tries that network first and falls back to the hotspot when it
is out of range. Going back to hotspot mode deletes `midwire-wifi`.

Changing Wi-Fi usually cuts the connection the request came in on, so changes
run in the background after the response has gone out, and the outcome is
kept for the page to show once the user is connected again.

Passwords are passed to nmcli as arguments, which other local processes could
read from /proc for a moment. The appliance has no other local users.
"""

from __future__ import annotations

import hmac
import logging
import shutil
import subprocess
import threading
import time
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import Settings
from .service import RequestError

log = logging.getLogger(__name__)

HOTSPOT = "midwire-hotspot"
CLIENT = "midwire-wifi"

_NMCLI_TIMEOUT = 20
_CONNECT_WAIT = "30"
# Time for the HTTP response to leave before the Wi-Fi link changes.
_SWITCH_DELAY = 1.0
_QUOTES = "'" + '"'


def _check_ssid(value: str) -> str:
    if not value or len(value.encode()) > 32:
        raise ValueError("A network name is 1 to 32 bytes long.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("A network name cannot contain control characters.")
    return value


def _check_passphrase(value: str | None) -> str | None:
    if value is None:
        return None
    if not 8 <= len(value) <= 63 or not all(32 <= ord(ch) < 127 for ch in value):
        raise ValueError("A Wi-Fi password is 8 to 63 printable ASCII characters.")
    return value


class HotspotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ssid: Annotated[str, Field(max_length=64)]
    # None keeps the current password.
    password: Annotated[str, Field(max_length=64)] | None = None

    _ssid = field_validator("ssid")(_check_ssid)
    _password = field_validator("password")(_check_passphrase)


class JoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ssid: Annotated[str, Field(max_length=64)]
    # None for an open network.
    password: Annotated[str, Field(max_length=64)] | None = None

    _ssid = field_validator("ssid")(_check_ssid)
    _password = field_validator("password")(_check_passphrase)


def split_terse(line: str) -> list[str]:
    """Splits one line of `nmcli -t` output: fields are separated by ':',
    and a literal ':' or '\\' inside a field is backslash-escaped."""
    fields, current, escaped = [], [], False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


class Network:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = threading.Lock()
        self._busy = False
        # Outcome of the last change, for the page to show after reconnecting.
        self.last: dict | None = None

    # --- nmcli ---------------------------------------------------------------

    def _run(self, *args: str, timeout: int = _NMCLI_TIMEOUT) -> subprocess.CompletedProcess:
        if shutil.which(self._settings.nmcli[0]) is None:
            raise RequestError("NetworkManager (nmcli) is not installed.")
        try:
            return subprocess.run(
                [*self._settings.nmcli, *args], capture_output=True, text=True, timeout=timeout
            )
        except FileNotFoundError as exc:
            raise RequestError("NetworkManager (nmcli) is not installed.") from exc
        except subprocess.TimeoutExpired as exc:
            raise RequestError("NetworkManager did not answer in time.") from exc

    def _must(self, *args: str, timeout: int = _NMCLI_TIMEOUT) -> str:
        result = self._run(*args, timeout=timeout)
        if result.returncode != 0:
            raise RequestError((result.stderr or result.stdout).strip() or "nmcli failed.")
        return result.stdout

    def _profile_ssid(self, name: str) -> str | None:
        result = self._run("-t", "-f", "802-11-wireless.ssid", "connection", "show", name)
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            fields = split_terse(line)
            if len(fields) == 2:
                return fields[1]
        return None

    def _addresses(self, device: str) -> list[str]:
        result = self._run("-t", "-f", "IP4.ADDRESS", "device", "show", device)
        if result.returncode != 0:
            return []
        return [f[1] for f in map(split_terse, result.stdout.splitlines()) if len(f) == 2 and f[1]]

    def hotspot_uses_default_password(self) -> bool:
        """True while the hotspot still has the password every new device
        starts with. Compares the real password with the image's default, so
        it is right however the password was changed."""
        default = ""
        try:
            for line in self._settings.firstboot_conf.read_text().splitlines():
                name, _, value = line.partition("=")
                if name.strip() == "HOTSPOT_DEFAULT_PASSWORD":
                    default = value.strip().strip(_QUOTES)
        except OSError:
            return False
        if not default:
            return False
        try:
            # -s: include secrets. Allowed for this user by the polkit rule.
            result = self._run("-s", "-g", "802-11-wireless-security.psk", "connection", "show", HOTSPOT)
        except RequestError:
            return False
        return result.returncode == 0 and hmac.compare_digest(result.stdout.strip().encode(), default.encode())

    # --- reading -------------------------------------------------------------

    def status(self) -> dict:
        # Read first. If a change is under way, what follows may be a
        # half-way picture, and the page must know to ask again.
        busy = self._busy
        try:
            listing = self._must("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        except RequestError as exc:
            return {"available": False, "error": str(exc), "busy": busy, "last": self.last}

        wifi = {"interface": self._settings.wifi_interface, "present": False, "mode": "off",
                "state": None, "ssid": None, "addresses": []}
        ethernet = []
        for line in listing.splitlines():
            fields = split_terse(line)
            if len(fields) != 4:
                continue
            device, kind, state, connection = fields
            if kind == "wifi" and device == wifi["interface"]:
                wifi.update(present=True, state=state, addresses=self._addresses(device))
                if connection == HOTSPOT:
                    wifi["mode"] = "hotspot"
                elif connection:
                    wifi["mode"] = "client"
                if connection:
                    wifi["ssid"] = self._profile_ssid(connection)
            elif kind == "ethernet":
                ethernet.append({"interface": device, "state": state,
                                 "connection": connection or None,
                                 "addresses": self._addresses(device)})

        client_ssid = self._profile_ssid(CLIENT)
        return {
            "available": True,
            "busy": busy,
            "last": self.last,
            "wifi": wifi,
            "hotspot": {"ssid": self._profile_ssid(HOTSPOT)},
            # Set while the Pi is meant to join a network instead of hosting one.
            "client": {"ssid": client_ssid} if client_ssid is not None else None,
            "ethernet": ethernet,
        }

    def scan(self) -> list[dict]:
        output = self._must(
            "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list",
            "ifname", self._settings.wifi_interface, "--rescan", "auto", timeout=30,
        )
        best: dict[str, dict] = {}
        for line in output.splitlines():
            fields = split_terse(line)
            if len(fields) != 3 or not fields[0]:
                continue
            ssid, signal, security = fields
            entry = {"ssid": ssid, "signal": int(signal) if signal.isdigit() else 0,
                     "secured": security not in ("", "--")}
            if ssid not in best or entry["signal"] > best[ssid]["signal"]:
                best[ssid] = entry
        own = self._profile_ssid(HOTSPOT)
        return sorted((e for e in best.values() if e["ssid"] != own),
                      key=lambda e: e["signal"], reverse=True)

    # --- changing ------------------------------------------------------------

    def set_hotspot(self, request: HotspotRequest) -> None:
        """Renames the hotspot and/or changes its password."""
        if self._profile_ssid(HOTSPOT) is None and request.password is None:
            raise RequestError("The hotspot has no password yet. Enter one.")
        self._begin(lambda: self._apply_hotspot(request))

    def join(self, request: JoinRequest) -> None:
        """Leaves hotspot mode and joins an existing network. If that fails
        the hotspot comes back, so the page stays reachable."""
        self._begin(lambda: self._apply_join(request))

    def use_hotspot(self) -> None:
        """Forgets the joined network and goes back to hosting the hotspot."""
        if self._profile_ssid(HOTSPOT) is None:
            raise RequestError("No hotspot is set up.")
        self._begin(self._apply_use_hotspot)

    def _begin(self, work) -> None:
        with self._lock:
            if self._busy:
                raise RequestError("Another network change is still running.")
            self._busy = True

        def run() -> None:
            time.sleep(_SWITCH_DELAY)
            try:
                message = work()
                self._record(True, message)
            except RequestError as exc:
                self._record(False, str(exc))
            except Exception:
                log.exception("network change failed")
                self._record(False, "The network change failed unexpectedly. See the service log.")
            finally:
                self._busy = False

        threading.Thread(target=run, name="network-change", daemon=True).start()

    def _record(self, ok: bool, message: str) -> None:
        log.info("network: %s", message)
        self.last = {"time": int(time.time()), "ok": ok, "message": message}

    def _hotspot_active(self) -> bool:
        listing = self._must("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        return any(split_terse(line)[-1] == HOTSPOT for line in listing.splitlines())

    def _apply_hotspot(self, request: HotspotRequest) -> str:
        iface = self._settings.wifi_interface
        if self._profile_ssid(HOTSPOT) is None:
            self._must(
                "connection", "add", "type", "wifi", "ifname", iface, "con-name", HOTSPOT,
                "autoconnect", "yes", "connection.autoconnect-priority", "-10",
                "ssid", request.ssid, "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
                "ipv4.method", "shared", "ipv6.method", "ignore",
                "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", request.password,
            )
            was_active = False
        else:
            was_active = self._hotspot_active()
            changes = ["802-11-wireless.ssid", request.ssid]
            if request.password is not None:
                changes += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", request.password]
            self._must("connection", "modify", HOTSPOT, *changes)
        if was_active or self._profile_ssid(CLIENT) is None:
            # Restart it so the new name and password take effect.
            self._must("--wait", _CONNECT_WAIT, "connection", "up", HOTSPOT, timeout=45)
            return f"The hotspot is now \"{request.ssid}\". Reconnect to it."
        return f"Saved. The hotspot will be \"{request.ssid}\" the next time it is used."

    def _apply_join(self, request: JoinRequest) -> str:
        iface = self._settings.wifi_interface
        self._run("connection", "delete", CLIENT)
        add = ["connection", "add", "type", "wifi", "ifname", iface, "con-name", CLIENT,
               "autoconnect", "yes", "connection.autoconnect-priority", "10", "ssid", request.ssid]
        if request.password is not None:
            add += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", request.password]
        self._must(*add)
        result = self._run("--wait", _CONNECT_WAIT, "connection", "up", CLIENT, timeout=45)
        if result.returncode == 0:
            return f"Joined \"{request.ssid}\"."
        reason = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no reason given"]
        self._run("connection", "delete", CLIENT)
        if self._profile_ssid(HOTSPOT) is not None:
            self._run("--wait", _CONNECT_WAIT, "connection", "up", HOTSPOT, timeout=45)
            raise RequestError(f"Could not join \"{request.ssid}\" ({reason[0]}). The hotspot is back on.")
        raise RequestError(f"Could not join \"{request.ssid}\" ({reason[0]}).")

    def _apply_use_hotspot(self) -> str:
        self._run("connection", "delete", CLIENT)
        self._must("--wait", _CONNECT_WAIT, "connection", "up", HOTSPOT, timeout=45)
        return "The hotspot is on."
