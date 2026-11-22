"""Auto-start rules that depend on what kind of device arrives.

The first of these is the bug this file exists for: a DJI drone presents a
network adapter among its interfaces, the Pi brings up usb0 on it, and
auto-start skipped it every time without saying why.
"""

from __future__ import annotations

from conftest import LOGIN, WRITE
from fastapi.testclient import TestClient

ADAPTER = {"device_id": "1-1.4", "udc": "fe980000.usb"}
CAMERA = {"device_id": "1-1.3", "udc": "fe980000.usb"}
ON = {"autostart": {"enabled": True}}
RESTART = "--no-ask-password restart usb-proxy.service"


def logged_in(env):
    app = env.app()
    client = TestClient(app)
    client.post("/api/login", json=LOGIN, headers=WRITE)
    return client, app.state.autostarter


def settle(starter) -> None:
    starter.tick()
    starter.tick()


def replug(env, starter, dev_id: str) -> None:
    env.unplug(dev_id)
    starter.tick()
    env.plug(dev_id)
    settle(starter)


def restarts(env) -> int:
    return env.calls().count(RESTART)


def last(client) -> dict:
    return client.get("/api/state").json()["autostart"]


def proxy_exits(env) -> None:
    """usb-proxy ends by itself, e.g. because its device was unplugged."""
    (env.state_dir / "unit-state").write_text("inactive ")


def test_a_network_device_started_by_hand_before_is_auto_started(env):
    for known_only in (False, True):
        client, starter = logged_in(env)
        settle(starter)  # boot, auto-start still off
        # Starting it from the page once is the user saying: proxy this.
        client.post("/api/start", json={**ADAPTER, "hide_interfaces": []}, headers=WRITE)
        client.post("/api/stop", headers=WRITE)
        starter._holdoff_until = 0
        before = restarts(env)
        client.put("/api/preferences", json={"autostart": {"enabled": True, "known_only": known_only}},
                   headers=WRITE)
        starter.tick()

        replug(env, starter, "1-1.4")
        assert restarts(env) == before + 1, f"known_only={known_only}"
        assert "--vendor_id=0bda" in env.args()
        assert last(client)["ok"] is True
        client.post("/api/stop", headers=WRITE)


def test_a_network_device_never_started_before_is_held_back_and_says_why(env):
    client, starter = logged_in(env)
    settle(starter)
    client.put("/api/preferences", json=ON, headers=WRITE)
    starter.tick()

    replug(env, starter, "1-1.4")
    assert restarts(env) == 0
    outcome = last(client)
    assert outcome["ok"] is False
    assert "eth1" in outcome["message"]
    assert "Start it once from the Proxy page" in outcome["message"]


def test_a_device_whose_network_interface_is_down_is_just_a_device(env):
    (env.sysfs / "class" / "net" / "eth1" / "flags").write_text("0x1002")
    client, starter = logged_in(env)
    settle(starter)
    client.put("/api/preferences", json=ON, headers=WRITE)
    starter.tick()

    replug(env, starter, "1-1.4")
    assert restarts(env) == 1
    assert "--vendor_id=0bda" in env.args()


def test_in_known_only_mode_an_unknown_device_is_ignored_without_comment(env):
    client, starter = logged_in(env)
    settle(starter)
    client.put("/api/preferences", json={"autostart": {"enabled": True, "known_only": True}}, headers=WRITE)
    starter.tick()
    replug(env, starter, "1-1.2")
    assert restarts(env) == 0
    assert last(client) is None


def test_a_quick_replug_is_noticed(env):
    """Pulled and pushed back in between two looks: the port name never
    disappears, but the kernel gives the device a new address."""
    client, starter = logged_in(env)
    settle(starter)
    client.put("/api/preferences", json=ON, headers=WRITE)
    starter.tick()

    devnum = env.sysfs / "bus" / "usb" / "devices" / "1-1.2" / "devnum"
    devnum.write_text("42\n")
    starter.tick()
    assert restarts(env) == 0  # still settling
    starter.tick()
    assert restarts(env) == 1
    assert "--vendor_id=046d" in env.args()


def test_a_device_that_keeps_coming_back_is_not_restarted_in_a_loop(env):
    client, starter = logged_in(env)
    settle(starter)
    client.put("/api/preferences", json=ON, headers=WRITE)
    starter.tick()
    devnum = env.sysfs / "bus" / "usb" / "devices" / "1-1.2" / "devnum"

    devnum.write_text("42\n")
    settle(starter)
    assert restarts(env) == 1

    # The proxy exits and the device re-enumerates at once.
    proxy_exits(env)
    devnum.write_text("43\n")
    settle(starter)
    assert restarts(env) == 1
    assert "started automatically a moment ago" in last(client)["message"]

    # Later, a real re-plug starts it again.
    starter._last_start.clear()
    devnum.write_text("44\n")
    settle(starter)
    assert restarts(env) == 2


def test_another_device_arriving_while_the_proxy_runs_is_reported(env):
    client, starter = logged_in(env)
    settle(starter)
    client.put("/api/preferences", json=ON, headers=WRITE)
    client.post("/api/start", json=CAMERA, headers=WRITE)
    starter.tick()

    replug(env, starter, "1-1.2")
    assert restarts(env) == 1
    assert "--vendor_id=0c45" in env.args()
    outcome = last(client)
    assert outcome["ok"] is False
    assert "Logitech USB Receiver" in outcome["message"] and "already running" in outcome["message"]


def test_the_proxied_device_re_enumerating_is_not_reported(env):
    client, starter = logged_in(env)
    settle(starter)
    client.put("/api/preferences", json=ON, headers=WRITE)
    client.post("/api/start", json=CAMERA, headers=WRITE)
    starter.tick()

    # usb-proxy resets the device it opens, which can re-enumerate it.
    (env.sysfs / "bus" / "usb" / "devices" / "1-1.3" / "devnum").write_text("77\n")
    settle(starter)
    assert restarts(env) == 1
    assert last(client) is None
