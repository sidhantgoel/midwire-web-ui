#!/usr/bin/env python3
"""Stands in for journalctl. Prints a few lines in the style of the unit that
was asked for and exits, or keeps printing when $FAKE_JOURNAL_FOLLOW is set
(local preview)."""

import itertools
import os
import sys
import time

PROXY = [
    "Device is: fe980000.usb",
    "Driver is: fe980000.usb",
    "Device opened successfully",
    "Device speed: High Speed (480Mbps)",
    "Setup USB config successfully",
    "Start for EP0, thread id(4243)",
]
UPDATER = [
    "Refreshing the Midwire package list",
    "midwire-web-ui: 0.2.0 installed, 0.3.0 available",
    "Upgrading midwire-web-ui",
    "Updated 1 package.",
]

updater = any(arg.startswith("midwire-update-") for arg in sys.argv[1:])
tag = "midwire-update[5151]" if updater else "usb-proxy[4242]"


def emit(message: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"{stamp} midwire {tag}: {message}", flush=True)


for line in UPDATER if updater else PROXY:
    emit(line)

if os.environ.get("FAKE_JOURNAL_FOLLOW"):
    try:
        for count in itertools.count(1):
            time.sleep(1)
            if not updater:
                emit(f"EP81(int_in): wrote {4 + count % 5} bytes to host")
    except (KeyboardInterrupt, BrokenPipeError):
        sys.exit(0)
