#!/usr/bin/env python3
"""Stands in for systemctl. Keeps unit state in $FAKE_STATE_DIR and logs
every call to calls.log there, so tests can check what the app asked for.

It knows two kinds of unit: the proxy (usb-proxy.service), and the updater's
services (midwire-update-*.service), for which starting one also plays the
part of the updater by writing the status file at $FAKE_UPDATE_STATUS.

Flag files in $FAKE_STATE_DIR change its behaviour:
  fail                 every call is denied
  not-found            the proxy unit is not installed
  no-updater           the updater's units are not installed
  <unit>.running       that updater unit is reported as running
"""

import json
import os
import sys
import time
from pathlib import Path

state_dir = Path(os.environ["FAKE_STATE_DIR"])
state_file = state_dir / "unit-state"
args = sys.argv[1:]
with open(state_dir / "calls.log", "a") as log:
    log.write(" ".join(args) + "\n")

if (state_dir / "fail").exists():
    print("Access denied", file=sys.stderr)
    sys.exit(4)

unit = next((a for a in args if a.endswith(".service")), "")
is_updater = unit.startswith("midwire-update-")

PACKAGES = ["midwire-base", "midwire-web-ui", "usb-proxy", "raw-gadget-dkms"]
INSTALLED = {"midwire-base": "0.2.0", "midwire-web-ui": "0.2.0", "usb-proxy": "0.1.0",
             "raw-gadget-dkms": "2025.12.13+midwire1"}
NEWER = {"midwire-web-ui": "0.3.0"}


def play_updater(install: bool) -> None:
    """Writes what the real updater would after a check or an install."""
    target = os.environ.get("FAKE_UPDATE_STATUS")
    if not target:
        return
    path = Path(target)
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError):
        previous = {}
    status = {"state": "idle", "checked": int(time.time()), "check_error": None,
              "last_install": previous.get("last_install")}
    if install:
        status["packages"] = [
            {"name": n, "installed": NEWER.get(n, INSTALLED[n]), "available": NEWER.get(n, INSTALLED[n]),
             "upgradable": False}
            for n in PACKAGES
        ]
        status["last_install"] = {
            "time": int(time.time()), "ok": True, "message": "Updated 1 package.",
            "upgraded": [{"name": n, "from": INSTALLED[n], "to": v} for n, v in NEWER.items()],
        }
    else:
        status["packages"] = [
            {"name": n, "installed": INSTALLED[n], "available": NEWER.get(n, INSTALLED[n]),
             "upgradable": n in NEWER}
            for n in PACKAGES
        ]
    path.write_text(json.dumps(status))


if "show" in args and is_updater:
    if (state_dir / "no-updater").exists():
        print("LoadState=not-found\nActiveState=inactive")
    else:
        running = (state_dir / f"{unit}.running").exists()
        print(f"LoadState=loaded\nActiveState={'activating' if running else 'inactive'}")
elif "show" in args:
    if (state_dir / "not-found").exists():
        print("LoadState=not-found\nActiveState=inactive\nSubState=dead")
        sys.exit(0)
    state, _, since = (state_file.read_text() if state_file.exists() else "inactive ").partition(" ")
    active = state == "active"
    print("LoadState=loaded")
    print(f"ActiveState={state}")
    print(f"SubState={'running' if active else 'dead'}")
    print("Result=success")
    print("ExecMainStatus=0")
    print(f"MainPID={4242 if active else 0}")
    print(f"ActiveEnterTimestamp={'@' + since if active else ''}")
elif "start" in args and is_updater:
    play_updater(install="install" in unit)
elif "restart" in args:
    state_file.write_text(f"active {int(time.time())}")
elif "stop" in args:
    state_file.write_text("inactive ")
else:
    print(f"fake systemctl: unsupported call {args}", file=sys.stderr)
    sys.exit(1)
