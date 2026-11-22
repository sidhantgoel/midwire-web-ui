#!/usr/bin/env python3
"""Stands in for systemctl. Keeps the unit state in $FAKE_STATE_DIR and logs
every call to calls.log there, so tests can check what the app asked for."""

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

if "show" in args:
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
elif "restart" in args:
    state_file.write_text(f"active {int(time.time())}")
elif "stop" in args:
    state_file.write_text("inactive ")
else:
    print(f"fake systemctl: unsupported call {args}", file=sys.stderr)
    sys.exit(1)
