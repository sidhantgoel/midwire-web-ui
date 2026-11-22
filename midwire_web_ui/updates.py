"""Software updates.

The work is done by the midwire-base package: a root-owned program that
upgrades Midwire's own packages from its signed apt repository, run by two
systemd services. This module only starts those services (polkit allows the
web UI's user exactly that) and reports what the program wrote to its status
file. The web UI never names a package or runs apt itself.
"""

from __future__ import annotations

import json

from .config import Settings
from .service import RequestError, _systemctl

_STATES = {"idle", "checking", "installing"}


def _text(value, limit: int = 300) -> str | None:
    return value[:limit] if isinstance(value, str) else None


def _number(value) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _read_status(settings: Settings) -> dict | None:
    try:
        data = json.loads(settings.update_status_file.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _packages(data: dict) -> list[dict]:
    packages = []
    for entry in data.get("packages") or []:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            packages.append({
                "name": entry["name"][:100],
                "installed": _text(entry.get("installed"), 100),
                "available": _text(entry.get("available"), 100),
                "upgradable": entry.get("upgradable") is True,
            })
    return packages


def update_available(settings: Settings) -> bool:
    """Cheap: reads the status file only. For the badge in the page header."""
    data = _read_status(settings)
    return bool(data) and any(p["upgradable"] for p in _packages(data))


def _unit_state(settings: Settings, unit: str) -> tuple[bool, bool]:
    """(installed, running) for one of the updater's services."""
    result = _systemctl(settings, "show", unit, "-p", "LoadState,ActiveState")
    if result.returncode != 0:
        # A unit that does not exist still answers (LoadState=not-found), so
        # this is systemd itself refusing or failing.
        raise RequestError((result.stderr or result.stdout).strip() or "systemctl failed.")
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return values.get("LoadState") == "loaded", values.get("ActiveState") in ("active", "activating")


def status(settings: Settings) -> dict:
    try:
        check_installed, checking = _unit_state(settings, settings.update_check_unit)
        install_installed, installing = _unit_state(settings, settings.update_install_unit)
    except RequestError as exc:
        return {"supported": False, "reason": str(exc)}
    if not (check_installed and install_installed):
        return {
            "supported": False,
            "reason": "This device has no updater yet. It comes with the midwire-base package.",
        }

    data = _read_status(settings) or {}
    packages = _packages(data)
    # systemd knows for certain whether the program is running. The file's
    # own "state" could be stale if the program was killed.
    state = "installing" if installing else "checking" if checking else "idle"

    last = data.get("last_install")
    last_install = None
    if isinstance(last, dict):
        last_install = {
            "time": _number(last.get("time")),
            "ok": last.get("ok") is True,
            "message": _text(last.get("message")) or "",
            "upgraded": [
                {"name": _text(u.get("name"), 100), "from": _text(u.get("from"), 100), "to": _text(u.get("to"), 100)}
                for u in last.get("upgraded") or []
                if isinstance(u, dict)
            ],
        }

    return {
        "supported": True,
        "state": state,
        "checked": _number(data.get("checked")),
        "check_error": _text(data.get("check_error")),
        "packages": packages,
        "update_available": any(p["upgradable"] for p in packages),
        "last_install": last_install,
    }


def _start(settings: Settings, unit: str) -> None:
    # --no-block: answer the browser now. Progress comes from the status
    # file and the journal.
    result = _systemctl(settings, "--no-ask-password", "start", "--no-block", unit)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit status {result.returncode}"
        raise RequestError(f"Could not start the updater: {detail}")


def check(settings: Settings) -> None:
    current = status(settings)
    if not current["supported"]:
        raise RequestError(current["reason"])
    if current["state"] != "idle":
        raise RequestError("The updater is already running.")
    _start(settings, settings.update_check_unit)


def install(settings: Settings) -> None:
    current = status(settings)
    if not current["supported"]:
        raise RequestError(current["reason"])
    if current["state"] == "installing":
        raise RequestError("An update is already being installed.")
    _start(settings, settings.update_install_unit)
