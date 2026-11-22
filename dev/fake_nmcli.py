#!/usr/bin/env python3
"""Stands in for nmcli. Keeps connection profiles and the active Wi-Fi
connection in $FAKE_STATE_DIR/nm.json. Joining a network named "BadNet"
fails, to exercise the fall-back-to-hotspot path."""

import json
import os
import sys
from pathlib import Path

state_dir = Path(os.environ["FAKE_STATE_DIR"])
state_file = state_dir / "nm.json"
DEFAULT = {
    "connections": {"midwire-hotspot": {"ssid": "Midwire-1A2B", "psk": "initial-pass", "mode": "ap"}},
    "wlan": "midwire-hotspot",
}
state = json.loads(state_file.read_text()) if state_file.exists() else DEFAULT


def save() -> None:
    state_file.write_text(json.dumps(state))


def escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


args = sys.argv[1:]
with open(state_dir / "nmcli.log", "a") as log:
    log.write(json.dumps(args) + "\n")

# Drop the global options the app uses.
words = []
skip = False
for i, arg in enumerate(args):
    if skip:
        skip = False
    elif arg in ("-f", "--wait"):
        skip = True
    elif arg != "-t":
        words.append(arg)

conns = state["connections"]

if words[:2] == ["device", "status"]:
    active = state["wlan"]
    print(f"wlan0:wifi:{'connected' if active else 'disconnected'}:{escape(active)}")
    print("eth0:ethernet:connected:midwire-eth-direct")
    print("lo:loopback:unmanaged:")
elif words[:2] == ["device", "show"]:
    if words[2] == "eth0":
        print("IP4.ADDRESS[1]:10.42.1.1/24")
    elif state["wlan"] == "midwire-hotspot":
        print("IP4.ADDRESS[1]:10.42.0.1/24")
    elif state["wlan"]:
        print("IP4.ADDRESS[1]:192.168.1.50/24")
elif words[:3] == ["device", "wifi", "list"]:
    print("HomeNet:78:WPA2")
    print("HomeNet:60:WPA2")
    print("Cafe\\: Free:40:")
    print(":30:WPA2")
    print(f"{escape(conns.get('midwire-hotspot', {}).get('ssid', ''))}:99:WPA2")
elif words[:2] == ["connection", "show"]:
    name = words[2]
    if name not in conns:
        print(f"Error: {name} - no such connection profile.", file=sys.stderr)
        sys.exit(10)
    print(f"802-11-wireless.ssid:{escape(conns[name]['ssid'])}")
elif words[:2] == ["connection", "add"]:
    pairs = dict(zip(words[2::2], words[3::2]))
    conns[pairs["con-name"]] = {
        "ssid": pairs["ssid"],
        "psk": pairs.get("wifi-sec.psk"),
        "mode": pairs.get("802-11-wireless.mode", "infrastructure"),
        "priority": pairs.get("connection.autoconnect-priority"),
    }
    save()
elif words[:2] == ["connection", "modify"]:
    name = words[2]
    if name not in conns:
        print(f"Error: unknown connection '{name}'.", file=sys.stderr)
        sys.exit(10)
    pairs = dict(zip(words[3::2], words[4::2]))
    if "802-11-wireless.ssid" in pairs:
        conns[name]["ssid"] = pairs["802-11-wireless.ssid"]
    if "wifi-sec.psk" in pairs:
        conns[name]["psk"] = pairs["wifi-sec.psk"]
    save()
elif words[:2] == ["connection", "delete"]:
    name = words[2]
    if name not in conns:
        print(f"Error: unknown connection '{name}'.", file=sys.stderr)
        sys.exit(10)
    del conns[name]
    if state["wlan"] == name:
        state["wlan"] = ""
    save()
elif words[:2] == ["connection", "up"]:
    name = words[2]
    if name not in conns:
        print(f"Error: unknown connection '{name}'.", file=sys.stderr)
        sys.exit(10)
    if conns[name]["ssid"] == "BadNet":
        state["wlan"] = ""
        save()
        print("Error: Connection activation failed: Secrets were required, but not provided.",
              file=sys.stderr)
        sys.exit(4)
    state["wlan"] = name
    save()
else:
    print(f"fake nmcli: unsupported call {args}", file=sys.stderr)
    sys.exit(2)
