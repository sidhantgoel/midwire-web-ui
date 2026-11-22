"""Request and settings shapes shared by the API, the settings file and
auto-start. Every field is a bool, a bounded number or a lookup key, so none
of them can carry free text to usb-proxy's command line."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ProxyOptions(BaseModel):
    """The usb-proxy options a user can choose, apart from which device."""

    model_config = ConfigDict(extra="forbid")

    hide_interfaces: list[Annotated[int, Field(ge=0, le=255)]] = []
    auto_remap_endpoints: bool = False
    iso_batch_size: Annotated[int, Field(ge=1, le=32)] | None = None
    # Name of a rules file in usb-proxy's config directory.
    injection_file: Annotated[str, Field(max_length=255)] | None = None
    customized_config: bool = False
    capture: bool = False
    verbose: Annotated[int, Field(ge=0, le=2)] = 0


class StartRequest(ProxyOptions):
    # sysfs id of the device to proxy, e.g. "1-1.2". Vendor and product id
    # are read from sysfs, not taken from the client.
    device_id: Annotated[str, Field(max_length=64)]
    udc: Annotated[str, Field(max_length=255)]

    def options(self) -> ProxyOptions:
        return ProxyOptions(**self.model_dump(exclude={"device_id", "udc"}))


class Autostart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Start usb-proxy when a device is plugged in, and at boot for a device
    # that is already attached.
    enabled: bool = False
    # Only for devices started from the page before (they have saved options).
    known_only: bool = False


class PreferencesUpdate(BaseModel):
    """What the settings form may change. Saved device options are written
    by a start, not by this."""

    model_config = ConfigDict(extra="forbid")

    autostart: Autostart = Autostart()
    # Gadget controller to use for auto-start. None: use the only one there is.
    udc: Annotated[str, Field(max_length=255)] | None = None
    # Options for a device that has none saved. hide_interfaces is ignored
    # here: interface numbers mean nothing without a specific device.
    defaults: ProxyOptions = ProxyOptions()


class Preferences(PreferencesUpdate):
    # Last options used per device, keyed "vendor:product", e.g. "046d:c52b".
    profiles: dict[str, ProxyOptions] = {}
