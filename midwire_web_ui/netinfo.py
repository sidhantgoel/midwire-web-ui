"""Which network interface a connection to this server arrived on.

Used to tell the user, truthfully, whether proxying a USB device that has a
network interface would cut off the page they are looking at.
"""

from __future__ import annotations

import re
import socket
import struct
from pathlib import Path

_SIOCGIFADDR = 0x8915


def _ipv4_address(name: str) -> str | None:
    import fcntl  # Linux only; imported here so the module loads anywhere

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            packed = fcntl.ioctl(sock.fileno(), _SIOCGIFADDR, struct.pack("256s", name.encode()[:15]))
        except OSError:
            return None  # the interface has no IPv4 address
    return socket.inet_ntoa(packed[20:24])


def interface_for_address(address: str) -> str | None:
    """Name of the interface that has this IPv4 address, or None. The server
    listens on IPv4, so that is the only kind of address it is asked about."""
    try:
        socket.inet_aton(address)
    except OSError:
        return None
    try:
        names = [name for _, name in socket.if_nameindex()]
    except OSError:
        return None
    for name in names:
        try:
            if _ipv4_address(name) == address:
                return name
        except (ImportError, OSError):
            return None
    return None


_INTERFACE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")


def usb_link_interface(state_file: Path) -> str | None:
    """The Pi's interface on the network link over the USB-C cable, while
    that link is up. Usually midwire0. None when the link is down, which
    includes all the time the proxy is running."""
    try:
        lines = state_file.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        name, _, value = line.partition("=")
        if name.strip() == "INTERFACE" and _INTERFACE_NAME.match(value.strip()):
            return value.strip()
    return None
