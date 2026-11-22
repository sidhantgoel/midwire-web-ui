"""Starts usb-proxy when a device is plugged in, if the user turned that on.

The web UI service runs from boot, so it does the watching itself: one look
at sysfs a second. A device triggers a start once, when it arrives (or at
boot if it is already attached). Stopping the proxy by hand therefore does
not start it again until the device is re-plugged.
"""

from __future__ import annotations

import asyncio
import logging
import time

from . import service
from .config import Settings
from .models import ProxyOptions, StartRequest
from .prefs import PreferenceStore, profile_key
from .usb import Device, list_devices, list_udcs

log = logging.getLogger(__name__)

POLL_SECONDS = 1.0
# A new device must be seen on this many looks in a row, so it has finished
# enumerating before usb-proxy opens it.
_SETTLE_TICKS = 2
# After a stop from the page, ignore arrivals for a moment: releasing a
# device can make it re-enumerate, which looks like a fresh plug-in.
_HOLDOFF_SECONDS = 5.0


def label(device: Device) -> str:
    name = " ".join(p for p in (device.manufacturer, device.product) if p)
    return name or f"{device.vendor_id}:{device.product_id}"


class Autostarter:
    def __init__(self, settings: Settings, store: PreferenceStore):
        self._settings = settings
        self._store = store
        # None until the first look, so devices attached at boot count as new.
        self._known: set[str] | None = None
        self._settling: dict[str, int] = {}
        self._holdoff_until = 0.0
        # Shown in the page: what auto-start last did, or why it did nothing.
        self.last: dict | None = None

    def note_manual_stop(self) -> None:
        self._holdoff_until = time.monotonic() + _HOLDOFF_SECONDS
        self._settling.clear()

    def tick(self) -> None:
        devices = {d.id: d for d in list_devices(self._settings)}
        arrived = set(devices) if self._known is None else set(devices) - self._known
        self._known = set(devices)

        prefs = self._store.load()
        if not prefs.autostart.enabled or time.monotonic() < self._holdoff_until:
            self._settling.clear()
            return

        for dev_id in arrived:
            self._settling[dev_id] = 0
        ready = []
        for dev_id in list(self._settling):
            if dev_id not in devices:
                del self._settling[dev_id]
                continue
            self._settling[dev_id] += 1
            if self._settling[dev_id] >= _SETTLE_TICKS:
                del self._settling[dev_id]
                ready.append(devices[dev_id])
        if not ready:
            return

        candidates = [d for d in ready if self._eligible(d, prefs)]
        if not candidates:
            return
        if service.status(self._settings).get("state") in ("active", "activating"):
            return
        if len(candidates) > 1:
            names = ", ".join(label(d) for d in candidates)
            self._record(False, f"Several devices appeared at once ({names}). Start one from the page.")
            return
        self._start(candidates[0], prefs)

    def _eligible(self, device: Device, prefs) -> bool:
        if device.system:
            return False
        # Never grab a network adapter unasked: it may be how the user
        # reaches this page.
        if any("Network interface" in w for w in device.warnings):
            return False
        if prefs.autostart.known_only:
            return profile_key(device.vendor_id, device.product_id) in prefs.profiles
        return True

    def _start(self, device: Device, prefs) -> None:
        udcs = [u.name for u in list_udcs(self._settings)]
        if prefs.udc in udcs:
            udc = prefs.udc
        elif len(udcs) == 1:
            udc = udcs[0]
        else:
            reason = "No gadget controller found." if not udcs else "Choose a gadget controller in Settings."
            self._record(False, f"Did not start {label(device)}: {reason}")
            return

        saved = prefs.profiles.get(profile_key(device.vendor_id, device.product_id))
        # Defaults apply to any device, so interface numbers in them mean nothing.
        options = saved or ProxyOptions(**prefs.defaults.model_dump(exclude={"hide_interfaces"}))
        request = StartRequest(device_id=device.id, udc=udc, **options.model_dump())
        try:
            service.start(request, self._settings)
        except service.RequestError as exc:
            self._record(False, f"Could not start {label(device)}: {exc}")
            return
        self._record(True, f"Started {label(device)} automatically.")

    def _record(self, ok: bool, message: str) -> None:
        log.info("auto-start: %s", message)
        self.last = {"time": int(time.time()), "ok": ok, "message": message}

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:  # keep watching whatever one look ran into
                log.exception("auto-start check failed")
            await asyncio.sleep(POLL_SECONDS)
