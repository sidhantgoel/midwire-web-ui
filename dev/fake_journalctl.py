#!/usr/bin/env python3
"""Stands in for journalctl. Prints a few usb-proxy style lines and exits, or
keeps printing when $FAKE_JOURNAL_FOLLOW is set (local preview)."""

import itertools
import os
import sys
import time

STARTUP = [
    "Device is: fe980000.usb",
    "Driver is: fe980000.usb",
    "Device opened successfully",
    "Device speed: High Speed (480Mbps)",
    "Setup USB config successfully",
    "Start for EP0, thread id(4243)",
]


def emit(message: str) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"{stamp} midwire usb-proxy[4242]: {message}", flush=True)


for line in STARTUP:
    emit(line)

if os.environ.get("FAKE_JOURNAL_FOLLOW"):
    try:
        for count in itertools.count(1):
            time.sleep(1)
            emit(f"EP81(int_in): wrote {4 + count % 5} bytes to host")
    except (KeyboardInterrupt, BrokenPipeError):
        sys.exit(0)
