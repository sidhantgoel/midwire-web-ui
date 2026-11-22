"""Builds usb-proxy's arguments from a validated request and controls the
systemd unit.

Nothing from the request reaches the command line as free text. Each value is
a bool, a bounded integer, or a key that is looked up in a list this server
built itself (attached devices, UDCs, injection files).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .config import Settings
from .models import StartRequest
from .usb import Device, Udc, list_devices, list_udcs

_CAPTURE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.pcap$")
_SYSTEMCTL_TIMEOUT = 20


class RequestError(Exception):
    """The request is well-formed but cannot be carried out. Shown to the user."""


def list_injection_files(settings: Settings) -> list[str]:
    """Rule files an admin placed in usb-proxy's config directory. They can
    run Lua, so the UI only offers what is already on disk and never uploads."""
    try:
        names = [p.name for p in settings.config_dir.glob("*.json") if p.is_file()]
    except OSError:
        return []
    return sorted(name for name in names if name != "config.json")


def build_args(request: StartRequest, settings: Settings) -> tuple[list[str], Device, Udc]:
    devices = {d.id: d for d in list_devices(settings)}
    udcs = {u.name: u for u in list_udcs(settings)}

    device = devices.get(request.device_id)
    if device is None:
        raise RequestError("That device is no longer attached.")
    if device.system:
        raise RequestError("The system boots from that drive. It cannot be proxied.")
    udc = udcs.get(request.udc)
    if udc is None:
        raise RequestError("That gadget controller was not found.")

    known = {i.number for i in device.interfaces}
    hidden = sorted(set(request.hide_interfaces))
    unknown = [n for n in hidden if n not in known]
    if unknown:
        raise RequestError(f"The device has no interface {unknown[0]}.")
    if known and len(hidden) == len(known):
        raise RequestError("At least one interface must stay visible to the host.")

    args = [
        f"--device={udc.name}",
        f"--driver={udc.driver}",
        f"--vendor_id={device.vendor_id}",
        f"--product_id={device.product_id}",
    ]
    args += ["-v"] * request.verbose
    if request.auto_remap_endpoints:
        args.append("--auto_remap_endpoints")
    args += [f"--hide_interface={n}" for n in hidden]
    if request.iso_batch_size is not None:
        args.append(f"--iso_batch_size={request.iso_batch_size}")
    if request.injection_file is not None:
        if request.injection_file not in list_injection_files(settings):
            raise RequestError("That injection file was not found.")
        args.append(f"--injection_file={settings.config_dir / request.injection_file}")
    if request.customized_config:
        args.append("--enable_customized_config")
    if request.capture:
        name = f"{time.strftime('%Y%m%d-%H%M%S')}_{device.vendor_id}_{device.product_id}.pcap"
        args.append(f"--pcap={settings.captures_dir / name}")
    return args, device, udc


def write_args(args: list[str], settings: Settings) -> None:
    """Replaces the arguments file in one step. /run/usb-proxy is setgid
    usbproxy-ctl, so the service user can read what we write."""
    data = b"".join(arg.encode() + b"\0" for arg in args)
    tmp = settings.args_file.with_name(settings.args_file.name + ".tmp")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o640)
    os.replace(tmp, settings.args_file)


def read_args(settings: Settings) -> list[str]:
    try:
        data = settings.args_file.read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in data.split(b"\0") if part]


def _systemctl(settings: Settings, *args: str) -> subprocess.CompletedProcess:
    if shutil.which(settings.systemctl[0]) is None:
        raise RequestError(f"{settings.systemctl[0]} was not found.")
    try:
        return subprocess.run(
            [*settings.systemctl, *args],
            capture_output=True,
            text=True,
            timeout=_SYSTEMCTL_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise RequestError(f"{settings.systemctl[0]} was not found.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RequestError("systemctl did not answer in time.") from exc


def _control(settings: Settings, verb: str) -> None:
    # --no-ask-password: polkit either allows this user or the call fails.
    result = _systemctl(settings, "--no-ask-password", verb, settings.unit)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit status {result.returncode}"
        raise RequestError(f"systemctl {verb} failed: {detail}")


def start(request: StartRequest, settings: Settings) -> tuple[list[str], Device]:
    args, device, _ = build_args(request, settings)
    try:
        write_args(args, settings)
    except OSError as exc:
        raise RequestError(f"Could not write {settings.args_file}: {exc.strerror}") from exc
    _control(settings, "restart")
    return args, device


def stop(settings: Settings) -> None:
    _control(settings, "stop")


def status(settings: Settings) -> dict:
    props = "ActiveState,SubState,Result,ExecMainStatus,MainPID,ActiveEnterTimestamp,LoadState"
    try:
        result = _systemctl(settings, "show", settings.unit, "--timestamp=unix", "-p", props)
    except RequestError as exc:
        return {"state": "unknown", "error": str(exc)}
    values = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    if result.returncode != 0 or values.get("LoadState") == "not-found":
        return {
            "state": "unknown",
            "error": (result.stderr.strip() or f"{settings.unit} is not installed."),
        }

    state = values.get("ActiveState", "unknown")
    running = state in ("active", "activating", "deactivating")
    since = values.get("ActiveEnterTimestamp", "")
    info = {
        "state": state,
        "sub_state": values.get("SubState"),
        "result": values.get("Result"),
        "exit_status": int(values["ExecMainStatus"]) if values.get("ExecMainStatus", "").isdigit() else None,
        "pid": int(values["MainPID"]) if values.get("MainPID", "0").isdigit() and running else None,
        "since": int(since[1:]) if since.startswith("@") and since[1:].isdigit() and running else None,
        "args": read_args(settings) if running else [],
        "capture": None,
    }
    for arg in info["args"]:
        if arg.startswith("--pcap="):
            info["capture"] = Path(arg.split("=", 1)[1]).name
    return info


def list_captures(settings: Settings) -> list[dict]:
    captures = []
    try:
        entries = list(settings.captures_dir.iterdir())
    except OSError:
        return captures
    for entry in entries:
        if not entry.is_file() or not _CAPTURE_NAME.match(entry.name):
            continue
        stat = entry.stat()
        captures.append({"name": entry.name, "size": stat.st_size, "modified": int(stat.st_mtime)})
    return sorted(captures, key=lambda c: c["modified"], reverse=True)


def capture_path(name: str, settings: Settings) -> Path:
    """Resolves a capture by name. The pattern has no path separators, so the
    result cannot leave the captures directory."""
    if not _CAPTURE_NAME.match(name):
        raise RequestError("Not a capture file name.")
    path = settings.captures_dir / name
    if not path.is_file() or path.is_symlink():
        raise RequestError("That capture does not exist.")
    return path
