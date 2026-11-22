"""Starts usb-proxy when a device is plugged in, if the user turned that on.

The web UI service runs from boot, so it does the watching itself: one look
at sysfs a second. A device triggers a start once, when it arrives (or at
boot if it is already attached). Stopping the proxy by hand therefore does
not start it again until the device is re-plugged.

Whenever a device arrives and is not started, the reason is recorded for the
page to show, unless the user's own settings plainly say to ignore it.
"""

from __future__ import annotations

import asyncio
import logging
import time

from . import service
from .config import Settings
from .models import Preferences, ProxyOptions, StartRequest
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
# The same device is not auto-started twice within this time. A device that
# re-enumerates whenever the proxy exits would otherwise restart it forever.
_MIN_SECONDS_BETWEEN_STARTS = 10.0


def label(device: Device) -> str:
    name = " ".join(p for p in (device.manufacturer, device.product) if p)
    return name or f"{device.vendor_id}:{device.product_id}"


def _identity(device: Device) -> str:
    """Port plus the address the kernel assigned. The address changes on
    every enumeration, so a device pulled and pushed back in between two
    looks still counts as newly plugged in."""
    return f"{device.id}#{device.address}"


def _proxied_key(status: dict) -> str | None:
    """vendor:product of the device the running proxy has, from its arguments."""
    values = {}
    for arg in status.get("args") or []:
        name, _, value = arg.partition("=")
        values[name] = value
    if "--vendor_id" in values and "--product_id" in values:
        return profile_key(values["--vendor_id"], values["--product_id"])
    return None


class Autostarter:
    def __init__(self, settings: Settings, store: PreferenceStore):
        self._settings = settings
        self._store = store
        # None until the first look, so devices attached at boot count as new.
        self._known: set[str] | None = None
        self._settling: dict[str, int] = {}
        self._holdoff_until = 0.0
        self._last_start: dict[str, float] = {}
        # Shown in the page: what auto-start last did, or why it did nothing.
        self.last: dict | None = None

    def note_manual_stop(self) -> None:
        self._holdoff_until = time.monotonic() + _HOLDOFF_SECONDS
        self._settling.clear()

    def tick(self) -> None:
        devices = {_identity(d): d for d in list_devices(self._settings)}
        arrived = set(devices) if self._known is None else set(devices) - self._known
        self._known = set(devices)

        prefs = self._store.load()
        if not prefs.autostart.enabled or time.monotonic() < self._holdoff_until:
            self._settling.clear()
            return

        for identity in arrived:
            self._settling[identity] = 0
        ready = []
        for identity in list(self._settling):
            if identity not in devices:
                del self._settling[identity]
                continue
            self._settling[identity] += 1
            if self._settling[identity] >= _SETTLE_TICKS:
                del self._settling[identity]
                ready.append(devices[identity])
        if not ready:
            return

        candidates, reasons = [], []
        for device in ready:
            reason = self._why_not(device, prefs)
            if reason is None:
                candidates.append(device)
            elif reason:
                reasons.append(reason)
        if not candidates:
            if reasons:
                self._record(False, reasons[0])
            return

        status = service.status(self._settings)
        if status.get("state") in ("active", "activating"):
            # The proxied device itself may re-enumerate; that needs no comment.
            running = _proxied_key(status)
            others = [d for d in candidates if profile_key(d.vendor_id, d.product_id) != running]
            if others:
                self._record(False, f"Did not start {label(others[0])}: the proxy is already running.")
            return
        if len(candidates) > 1:
            names = ", ".join(label(d) for d in candidates)
            self._record(False, f"Several devices appeared at once ({names}). Start one from the page.")
            return

        device = candidates[0]
        key = profile_key(device.vendor_id, device.product_id)
        last = self._last_start.get(key)
        if last is not None and time.monotonic() - last < _MIN_SECONDS_BETWEEN_STARTS:
            self._record(
                False,
                f"{label(device)} was started automatically a moment ago and is back already. "
                "Not starting it again so soon. Re-plug it, or start it from the page.",
            )
            return
        self._last_start[key] = time.monotonic()
        self._start(device, prefs)

    def _why_not(self, device: Device, prefs: Preferences) -> str | None:
        """None: start it. An empty string: leave it alone without comment,
        because that is what the settings ask for. Otherwise the reason."""
        if device.system:
            return ""
        started_before = profile_key(device.vendor_id, device.product_id) in prefs.profiles
        if prefs.autostart.known_only and not started_before:
            return ""
        if device.network_interfaces and not started_before:
            # It may be how the user reaches this page, and auto-starting it
            # would lock them out on every boot. Starting it once by hand
            # shows it is meant to be proxied.
            names = ", ".join(device.network_interfaces)
            return (
                f"Did not start {label(device)} automatically: it provides the network interface {names}, "
                "which may be how you reach this page. Start it once from the Proxy page and it will "
                "start automatically from then on."
            )
        return None

    def _start(self, device: Device, prefs: Preferences) -> None:
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
