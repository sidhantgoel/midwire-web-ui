"""Builds a small fake /sys tree that looks like a Raspberry Pi with a few
USB devices attached. Needs a filesystem with symlinks (Linux)."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

UDC = "fe980000.usb"

# (id, vendor, product, class, manufacturer, product name, interfaces)
# interface: (number, alt, class, subclass, protocol, [endpoint addresses], name, driver)
DEVICES = [
    ("1-1", 0x2109, 0x3431, 0x09, "VIA Labs", "USB2.0 Hub", [
        (0, 0, 0x09, 0, 0, [0x81], None, "hub"),
    ]),
    ("1-1.2", 0x046D, 0xC52B, 0x00, "Logitech", "USB Receiver", [
        (0, 0, 0x03, 1, 1, [0x81], None, "usbhid"),
        (1, 0, 0x03, 1, 2, [0x82], None, "usbhid"),
        (2, 0, 0x03, 0, 0, [0x83], None, "usbhid"),
    ]),
    ("1-1.3", 0x0C45, 0x6366, 0xEF, "Sonix Technology", "USB 2.0 Camera", [
        (0, 0, 0x0E, 1, 0, [0x83], "Video Control", "uvcvideo"),
        (1, 0, 0x0E, 2, 0, [], "Video Streaming", "uvcvideo"),
        (1, 1, 0x0E, 2, 0, [0x81], "Video Streaming", "uvcvideo"),
        (2, 0, 0x01, 1, 0, [], "Audio Control", "snd-usb-audio"),
        (3, 0, 0x01, 2, 0, [], "Audio Streaming", "snd-usb-audio"),
        (3, 1, 0x01, 2, 0, [0x84], "Audio Streaming", "snd-usb-audio"),
    ]),
    ("1-1.4", 0x0BDA, 0x8153, 0x00, "Realtek", "USB 10/100/1000 LAN", [
        (0, 0, 0xFF, 0xFF, 0, [0x81, 0x02, 0x83], None, "r8152"),
    ]),
    ("2-1", 0x152D, 0x0578, 0x00, "JMicron", "USB to SATA bridge", [
        (0, 0, 0x08, 6, 0x50, [0x81, 0x02], None, "uas"),
    ]),
]

SYSTEM_DEVICE = "2-1"
NETWORK_DEVICE = "1-1.4"


def descriptors(vendor: int, product: int, dev_class: int, interfaces) -> bytes:
    body = b""
    for number, alt, cls, sub, proto, endpoints, _name, _driver in interfaces:
        body += struct.pack("<9B", 9, 4, number, alt, len(endpoints), cls, sub, proto, 0)
        for address in endpoints:
            body += struct.pack("<BBBBHB", 7, 5, address, 0x03, 64, 10)
    count = len({i[0] for i in interfaces})
    config = struct.pack("<BBHBBBBB", 9, 2, 9 + len(body), count, 1, 0, 0xA0, 50) + body
    device = struct.pack(
        "<BBHBBBBHHHBBBB", 18, 1, 0x0200, dev_class, 0, 0, 64, vendor, product, 0x0100, 1, 2, 3, 1
    )
    return device + config


def _device_dir(root: Path, dev_id: str) -> Path:
    """1-1.2 lives under usb1/1-1/1-1.2, as in real sysfs."""
    bus = dev_id.split("-")[0]
    path = root / "devices" / "platform" / f"usb{bus}"
    parts = dev_id.split(".")
    for depth in range(1, len(parts) + 1):
        path = path / ".".join(parts[:depth])
    return path


def build(root: Path) -> Path:
    """Creates the tree under `root` and returns the fake /proc/mounts file."""
    links = root / "bus" / "usb" / "devices"
    links.mkdir(parents=True)
    drivers = root / "bus" / "usb" / "drivers"

    for number, (dev_id, vendor, product, cls, maker, name, interfaces) in enumerate(DEVICES, 2):
        path = _device_dir(root, dev_id)
        path.mkdir(parents=True)
        (path / "idVendor").write_text(f"{vendor:04x}\n")
        (path / "idProduct").write_text(f"{product:04x}\n")
        (path / "bDeviceClass").write_text(f"{cls:02x}\n")
        (path / "manufacturer").write_text(maker + "\n")
        (path / "product").write_text(name + "\n")
        (path / "serial").write_text(f"SN{number:04d}\n")
        (path / "busnum").write_text(dev_id.split("-")[0] + "\n")
        (path / "devnum").write_text(f"{number}\n")
        (path / "speed").write_text("480\n")
        (path / "bConfigurationValue").write_text("1\n")
        (path / "descriptors").write_bytes(descriptors(vendor, product, cls, interfaces))
        (links / dev_id).symlink_to(path)

        for intf_number, alt, _cls, _sub, _proto, _eps, intf_name, driver in interfaces:
            if alt != 0:
                continue
            intf = path / f"{dev_id}:1.{intf_number}"
            intf.mkdir()
            if intf_name:
                (intf / "interface").write_text(intf_name + "\n")
            (drivers / driver).mkdir(parents=True, exist_ok=True)
            (intf / "driver").symlink_to(drivers / driver)

    # Root hubs, which the app must skip.
    for bus in ("1", "2"):
        (links / f"usb{bus}").symlink_to(root / "devices" / "platform" / f"usb{bus}")

    udc = root / "class" / "udc" / UDC
    udc.mkdir(parents=True)
    (udc / "uevent").write_text(f"USB_UDC_NAME={UDC}\n")
    (udc / "state").write_text("not attached\n")

    # The boot drive: /dev/sda1 and /dev/sda2 sit on device 2-1.
    disk = _device_dir(root, SYSTEM_DEVICE) / f"{SYSTEM_DEVICE}:1.0" / "host0" / "block" / "sda"
    block = root / "class" / "block"
    block.mkdir(parents=True)
    for part in ("sda1", "sda2"):
        (disk / part).mkdir(parents=True)
        (block / part).symlink_to(disk / part)

    # A USB network adapter.
    net = root / "class" / "net" / "eth1"
    net.mkdir(parents=True)
    (net / "device").symlink_to(_device_dir(root, NETWORK_DEVICE) / f"{NETWORK_DEVICE}:1.0")
    # 0x1003 = IFF_UP | IFF_BROADCAST | IFF_MULTICAST: switched on.
    (net / "flags").write_text("0x1003")

    mounts = root.parent / "mounts"
    mounts.write_text(
        "/dev/sda2 / ext4 rw,noatime 0 0\n"
        "/dev/sda1 /boot/firmware vfat rw 0 0\n"
        "proc /proc proc rw 0 0\n"
    )
    return mounts


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
