"""Reads USB devices and gadget controllers (UDCs) from sysfs.

Everything the UI offers the user comes from here, and the start request is
validated against the same lists, so usb-proxy never sees a value the system
did not report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings

# "1-1" or "1-1.2.3": a device. Root hubs are "usb1", interfaces "1-1:1.0".
_DEVICE_DIR = re.compile(r"^\d+-\d+(\.\d+)*$")

_DT_CONFIG = 2
_DT_INTERFACE = 4
_DT_ENDPOINT = 5
_CLASS_HUB = 0x09

CLASS_NAMES = {
    0x01: "Audio",
    0x02: "Communications (CDC)",
    0x03: "HID",
    0x05: "Physical",
    0x06: "Image",
    0x07: "Printer",
    0x08: "Mass Storage",
    0x09: "Hub",
    0x0A: "CDC Data",
    0x0B: "Smart Card",
    0x0D: "Content Security",
    0x0E: "Video",
    0x0F: "Personal Healthcare",
    0x10: "Audio/Video",
    0xDC: "Diagnostic",
    0xE0: "Wireless Controller",
    0xEF: "Miscellaneous",
    0xFE: "Application Specific",
    0xFF: "Vendor Specific",
}

# Mount points whose backing drive must never be handed to the proxy:
# usb-proxy detaches the kernel driver from the device it opens.
_SYSTEM_MOUNTS = {"/", "/boot", "/boot/firmware"}


@dataclass
class Interface:
    number: int
    class_code: int
    class_name: str
    subclass: int
    protocol: int
    name: str | None
    driver: str | None
    # Distinct endpoint addresses over all alternate settings. The gadget
    # controller has a fixed number of endpoints, so this is what hiding an
    # interface saves.
    endpoints_in: int
    endpoints_out: int


@dataclass
class Device:
    id: str
    bus: int | None
    address: int | None
    vendor_id: str
    product_id: str
    manufacturer: str | None
    product: str | None
    serial: str | None
    class_code: int
    speed: str | None
    interfaces: list[Interface] = field(default_factory=list)
    # True for the drive the system boots from. The UI disables it and the
    # start request refuses it.
    system: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class Udc:
    name: str
    # raw_gadget wants both: --device is the UDC name, --driver the name the
    # controller driver reports in its uevent.
    driver: str
    state: str | None


def _read(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace").strip() or None
    except OSError:
        return None


def _read_int(path: Path, base: int = 10) -> int | None:
    text = _read(path)
    try:
        return int(text, base) if text is not None else None
    except ValueError:
        return None


def parse_interfaces(descriptors: bytes) -> dict[int, dict]:
    """Walks the raw descriptors sysfs exposes: the 18-byte device descriptor,
    then each configuration. Only the first configuration is reported."""
    interfaces: dict[int, dict] = {}
    offset = 18
    configs_seen = 0
    current: dict | None = None
    while offset + 2 <= len(descriptors):
        length, dtype = descriptors[offset], descriptors[offset + 1]
        if length < 2 or offset + length > len(descriptors):
            break
        body = descriptors[offset : offset + length]
        if dtype == _DT_CONFIG:
            configs_seen += 1
            if configs_seen > 1:
                break
        elif dtype == _DT_INTERFACE and length >= 9:
            number = body[2]
            current = interfaces.setdefault(
                number,
                {"class": body[5], "subclass": body[6], "protocol": body[7], "eps": set()},
            )
            if body[3] == 0:
                current.update({"class": body[5], "subclass": body[6], "protocol": body[7]})
        elif dtype == _DT_ENDPOINT and length >= 7 and current is not None:
            current["eps"].add(body[2])
        offset += length
    return interfaces


def _system_block_paths(settings: Settings) -> list[Path]:
    """sysfs paths of the block devices mounted at /, /boot and /boot/firmware."""
    paths = []
    try:
        lines = settings.proc_mounts.read_text().splitlines()
    except OSError:
        return paths
    for line in lines:
        fields = line.split()
        if len(fields) < 2 or fields[1] not in _SYSTEM_MOUNTS:
            continue
        source = fields[0]
        if not source.startswith("/dev/"):
            continue
        link = settings.sysfs / "class" / "block" / Path(source).name
        if link.exists():
            paths.append(link.resolve())
    return paths


def _network_interfaces(settings: Settings) -> list[tuple[str, Path]]:
    result = []
    net = settings.sysfs / "class" / "net"
    if net.is_dir():
        for entry in sorted(net.iterdir()):
            device = entry / "device"
            if device.exists():
                result.append((entry.name, device.resolve()))
    return result


def list_devices(settings: Settings) -> list[Device]:
    root = settings.sysfs / "bus" / "usb" / "devices"
    if not root.is_dir():
        return []
    system_paths = _system_block_paths(settings)
    net_paths = _network_interfaces(settings)

    devices: list[Device] = []
    for entry in sorted(root.iterdir()):
        if not _DEVICE_DIR.match(entry.name):
            continue
        vendor = _read(entry / "idVendor")
        product = _read(entry / "idProduct")
        if not vendor or not product:
            continue
        class_code = _read_int(entry / "bDeviceClass", 16) or 0
        if class_code == _CLASS_HUB:
            continue

        device = Device(
            id=entry.name,
            bus=_read_int(entry / "busnum"),
            address=_read_int(entry / "devnum"),
            vendor_id=vendor.lower(),
            product_id=product.lower(),
            manufacturer=_read(entry / "manufacturer"),
            product=_read(entry / "product"),
            serial=_read(entry / "serial"),
            class_code=class_code,
            speed=_read(entry / "speed"),
        )

        try:
            parsed = parse_interfaces((entry / "descriptors").read_bytes())
        except OSError:
            parsed = {}
        config = _read(entry / "bConfigurationValue") or "1"
        for number, info in sorted(parsed.items()):
            intf_dir = entry / f"{entry.name}:{config}.{number}"
            driver = intf_dir / "driver"
            device.interfaces.append(
                Interface(
                    number=number,
                    class_code=info["class"],
                    class_name=CLASS_NAMES.get(info["class"], f"Class 0x{info['class']:02x}"),
                    subclass=info["subclass"],
                    protocol=info["protocol"],
                    name=_read(intf_dir / "interface"),
                    driver=driver.resolve().name if driver.exists() else None,
                    endpoints_in=sum(1 for ep in info["eps"] if ep & 0x80),
                    endpoints_out=sum(1 for ep in info["eps"] if not ep & 0x80),
                )
            )

        real = entry.resolve()
        if any(real in block.parents for block in system_paths):
            device.system = True
            device.warnings.append("The system boots from this drive. It cannot be proxied.")
        for name, path in net_paths:
            if real in path.parents:
                device.warnings.append(
                    f"Network interface {name} runs on this device. Proxying it "
                    "disconnects that interface, which may cut off this page."
                )
        devices.append(device)

    # usb-proxy picks a device by vendor and product id only.
    by_ids: dict[tuple[str, str], list[Device]] = {}
    for device in devices:
        by_ids.setdefault((device.vendor_id, device.product_id), []).append(device)
    for group in by_ids.values():
        if len(group) > 1:
            for device in group:
                device.warnings.append(
                    "Another attached device has the same vendor and product id. "
                    "usb-proxy opens whichever it finds first."
                )
    return devices


def list_udcs(settings: Settings) -> list[Udc]:
    root = settings.sysfs / "class" / "udc"
    if not root.is_dir():
        return []
    udcs = []
    for entry in sorted(root.iterdir()):
        driver = entry.name
        for line in (_read(entry / "uevent") or "").splitlines():
            key, _, value = line.partition("=")
            if key == "USB_UDC_NAME" and value:
                driver = value
        udcs.append(Udc(name=entry.name, driver=driver, state=_read(entry / "state")))
    return udcs
