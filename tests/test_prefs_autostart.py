from __future__ import annotations

import json

from conftest import LOGIN, WRITE
from fastapi.testclient import TestClient

from midwire_web_ui import autostart

RECEIVER = {"device_id": "1-1.2", "udc": "fe980000.usb"}
ON = {"autostart": {"enabled": True}}


def logged_in(env) -> tuple[TestClient, autostart.Autostarter]:
    app = env.app()
    client = TestClient(app)
    client.post("/api/login", json=LOGIN, headers=WRITE)
    return client, app.state.autostarter


def settle(starter) -> None:
    """A new device is acted on after it has been seen twice."""
    starter.tick()
    starter.tick()


def started(env) -> bool:
    return any("restart" in call for call in env.calls())


# --- saved settings ---------------------------------------------------------


def test_preferences_default_and_persist(client, env):
    prefs = client.get("/api/state").json()["preferences"]
    assert prefs["autostart"] == {"enabled": False, "known_only": False}
    assert prefs["profiles"] == {}

    update = {
        "autostart": {"enabled": True, "known_only": True},
        "udc": "fe980000.usb",
        "defaults": {"auto_remap_endpoints": True, "capture": True, "verbose": 1},
    }
    assert client.put("/api/preferences", json=update, headers=WRITE).status_code == 200

    # A fresh app (a reboot) reads the same file.
    again, _ = logged_in(env)
    saved = again.get("/api/state").json()["preferences"]
    assert saved["autostart"] == {"enabled": True, "known_only": True}
    assert saved["udc"] == "fe980000.usb"
    assert saved["defaults"]["auto_remap_endpoints"] is True
    assert json.loads(env.settings.prefs_file.read_text())["defaults"]["verbose"] == 1


def test_preferences_are_validated(client):
    bad = [
        {"autostart": {"enabled": "maybe"}},
        {"defaults": {"iso_batch_size": 500}},
        {"defaults": {"shell": "rm -rf /"}},
        {"profiles": {"046d:c52b": {}}},  # profiles are written by a start, not by the form
    ]
    for body in bad:
        assert client.put("/api/preferences", json=body, headers=WRITE).status_code == 422, body
    assert client.put("/api/preferences", json={"udc": "nope"}, headers=WRITE).status_code == 400
    missing = {"defaults": {"injection_file": "gone.json"}}
    assert client.put("/api/preferences", json=missing, headers=WRITE).status_code == 400


def test_start_remembers_options_per_device(client):
    client.post("/api/start", json={**RECEIVER, "hide_interfaces": [2], "verbose": 1}, headers=WRITE)
    profiles = client.get("/api/state").json()["preferences"]["profiles"]
    assert list(profiles) == ["046d:c52b"]
    assert profiles["046d:c52b"]["hide_interfaces"] == [2]
    assert profiles["046d:c52b"]["verbose"] == 1
    assert "device_id" not in profiles["046d:c52b"]

    after = client.delete("/api/profiles/046d:c52b", headers=WRITE).json()
    assert after["profiles"] == {}


def test_a_damaged_settings_file_is_set_aside(client, env):
    env.settings.prefs_file.write_text("{ not json")
    prefs = client.get("/api/state").json()["preferences"]
    assert prefs["autostart"]["enabled"] is False
    assert env.settings.prefs_file.with_suffix(".json.bad").exists()


# --- auto-start -------------------------------------------------------------


def test_off_by_default(env):
    client, starter = logged_in(env)
    settle(starter)
    env.unplug("1-1.2")
    starter.tick()
    env.plug("1-1.2")
    settle(starter)
    assert not started(env)


def test_starts_a_device_when_it_is_plugged_in(env):
    client, starter = logged_in(env)
    env.unplug("1-1.2")
    env.unplug("1-1.3")
    client.put("/api/preferences", json={**ON, "defaults": {"verbose": 1, "hide_interfaces": [9]}}, headers=WRITE)
    settle(starter)  # boot: only the boot drive and the network adapter are attached
    assert not started(env)

    env.plug("1-1.2")
    starter.tick()
    assert not started(env)  # seen once: still settling
    starter.tick()
    assert started(env)
    # Defaults are used, minus hide_interfaces, which is per device.
    assert env.args() == [
        "--device=fe980000.usb", "--driver=fe980000.usb",
        "--vendor_id=046d", "--product_id=c52b", "-v",
    ]
    last = client.get("/api/state").json()["autostart"]
    assert last["ok"] is True and "Logitech USB Receiver" in last["message"]


def test_uses_the_options_saved_for_that_device(env):
    client, starter = logged_in(env)
    settle(starter)  # boot, with auto-start still off
    client.post("/api/start", json={**RECEIVER, "hide_interfaces": [2]}, headers=WRITE)
    client.post("/api/stop", headers=WRITE)
    (env.state_dir / "calls.log").unlink()
    starter._holdoff_until = 0
    client.put("/api/preferences", json={"autostart": {"enabled": True, "known_only": True}}, headers=WRITE)
    starter.tick()

    # The camera has never been started from the page, so it is ignored.
    env.unplug("1-1.3")
    starter.tick()
    env.plug("1-1.3")
    settle(starter)
    assert not started(env)

    env.unplug("1-1.2")
    starter.tick()
    env.plug("1-1.2")
    settle(starter)
    assert started(env)
    assert "--hide_interface=2" in env.args()


def test_at_boot_one_attached_device_starts(env):
    env.unplug("1-1.3")
    client, starter = logged_in(env)
    client.put("/api/preferences", json=ON, headers=WRITE)
    settle(starter)
    assert started(env)
    assert "--vendor_id=046d" in env.args()


def test_several_devices_at_once_start_nothing(env):
    client, starter = logged_in(env)
    client.put("/api/preferences", json=ON, headers=WRITE)
    settle(starter)  # boot with receiver and camera both attached
    assert not started(env)
    last = client.get("/api/state").json()["autostart"]
    assert last["ok"] is False and "Several devices" in last["message"]


def test_never_picks_the_boot_drive_or_a_network_adapter(env):
    env.unplug("1-1.2")
    env.unplug("1-1.3")
    client, starter = logged_in(env)
    client.put("/api/preferences", json=ON, headers=WRITE)
    settle(starter)
    for dev in ("2-1", "1-1.4"):
        env.unplug(dev)
        starter.tick()
        env.plug(dev)
        settle(starter)
    assert not started(env)


def test_does_not_interrupt_a_running_proxy(env):
    client, starter = logged_in(env)
    client.put("/api/preferences", json=ON, headers=WRITE)
    starter.tick()
    client.post("/api/start", json={"device_id": "1-1.3", "udc": "fe980000.usb"}, headers=WRITE)
    env.unplug("1-1.2")
    starter.tick()
    env.plug("1-1.2")
    settle(starter)
    assert env.calls().count("--no-ask-password restart usb-proxy.service") == 1
    assert "--vendor_id=0c45" in env.args()


def test_a_manual_stop_is_not_undone(env):
    env.unplug("1-1.3")
    client, starter = logged_in(env)
    client.put("/api/preferences", json=ON, headers=WRITE)
    settle(starter)
    assert started(env)

    client.post("/api/stop", headers=WRITE)
    # The device re-enumerates as it is released: that must not restart it.
    env.unplug("1-1.2")
    starter.tick()
    env.plug("1-1.2")
    settle(starter)
    for _ in range(3):
        starter.tick()
    assert env.calls().count("--no-ask-password restart usb-proxy.service") == 1


def test_reports_why_it_could_not_start(env):
    env.unplug("1-1.3")
    client, starter = logged_in(env)
    client.put("/api/preferences", json=ON, headers=WRITE)
    (env.sysfs / "class" / "udc" / "fe980000.usb").rename(env.sysfs / "udc-gone")
    settle(starter)
    assert not started(env)
    assert "No gadget controller" in client.get("/api/state").json()["autostart"]["message"]
