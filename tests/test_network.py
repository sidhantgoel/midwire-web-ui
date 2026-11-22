from __future__ import annotations

from conftest import LOGIN, WRITE, wait_idle

from midwire_web_ui.network import split_terse


def test_split_terse_handles_escaped_colons():
    assert split_terse("wlan0:wifi:connected:midwire-hotspot") == ["wlan0", "wifi", "connected", "midwire-hotspot"]
    assert split_terse("Cafe\\: Free:40:") == ["Cafe: Free", "40", ""]
    assert split_terse("a\\\\b:c") == ["a\\b", "c"]


def test_status_shows_hotspot_and_ethernet(client):
    status = client.get("/api/network").json()
    assert status["available"] is True
    assert status["wifi"]["mode"] == "hotspot"
    assert status["wifi"]["ssid"] == "Midwire-1A2B"
    assert status["wifi"]["addresses"] == ["10.42.0.1/24"]
    assert status["hotspot"] == {"ssid": "Midwire-1A2B"}
    assert status["client"] is None
    assert status["ethernet"] == [
        {"interface": "eth0", "state": "connected", "connection": "midwire-eth-direct",
         "addresses": ["10.42.1.1/24"]}
    ]
    # The hotspot password is never sent to the page.
    assert "initial-pass" not in client.get("/api/network").text


def test_scan_merges_duplicates_and_hides_our_own_hotspot(client):
    assert client.get("/api/network/scan").json() == [
        {"ssid": "HomeNet", "signal": 78, "secured": True},
        {"ssid": "Cafe: Free", "signal": 40, "secured": False},
    ]


def test_rename_hotspot_and_change_its_password(client, env):
    body = {"ssid": "Lab Proxy", "password": "new-hotspot-pass"}
    assert client.put("/api/network/hotspot", json=body, headers=WRITE).status_code == 202
    status = wait_idle(client)
    assert status["last"]["ok"] is True
    assert status["hotspot"]["ssid"] == "Lab Proxy"
    assert env.nm()["connections"]["midwire-hotspot"] == {"ssid": "Lab Proxy", "psk": "new-hotspot-pass", "mode": "ap"}
    # It was active, so it is restarted to apply the change.
    assert env.nmcli_calls()[-1][-3:] == ["connection", "up", "midwire-hotspot"] or \
        ["connection", "up", "midwire-hotspot"] in [c[-3:] for c in env.nmcli_calls()]


def test_rename_hotspot_keeping_the_password(client, env):
    client.put("/api/network/hotspot", json={"ssid": "Renamed"}, headers=WRITE)
    wait_idle(client)
    assert env.nm()["connections"]["midwire-hotspot"]["ssid"] == "Renamed"
    assert env.nm()["connections"]["midwire-hotspot"]["psk"] == "initial-pass"


def test_join_an_existing_network(client, env):
    body = {"ssid": "HomeNet", "password": "home-wifi-pass"}
    assert client.put("/api/network/wifi", json=body, headers=WRITE).status_code == 202
    status = wait_idle(client)
    assert status["last"] == {"time": status["last"]["time"], "ok": True, "message": 'Joined "HomeNet".'}
    assert status["wifi"]["mode"] == "client"
    assert status["wifi"]["ssid"] == "HomeNet"
    assert status["client"] == {"ssid": "HomeNet"}
    profile = env.nm()["connections"]["midwire-wifi"]
    # Higher priority than the hotspot, so it is tried first at boot.
    assert profile["priority"] == "10" and profile["psk"] == "home-wifi-pass"
    assert "midwire-hotspot" in env.nm()["connections"]  # kept as the fallback


def test_a_failed_join_brings_the_hotspot_back(client, env):
    client.put("/api/network/wifi", json={"ssid": "BadNet", "password": "whatever123"}, headers=WRITE)
    status = wait_idle(client)
    assert status["last"]["ok"] is False
    assert "hotspot is back on" in status["last"]["message"]
    assert status["wifi"]["mode"] == "hotspot"
    assert status["client"] is None
    assert "midwire-wifi" not in env.nm()["connections"]


def test_back_to_hotspot_forgets_the_joined_network(client, env):
    client.put("/api/network/wifi", json={"ssid": "HomeNet", "password": "home-wifi-pass"}, headers=WRITE)
    wait_idle(client)
    assert client.delete("/api/network/wifi", headers=WRITE).status_code == 202
    status = wait_idle(client)
    assert status["wifi"]["mode"] == "hotspot"
    assert status["client"] is None
    assert "midwire-wifi" not in env.nm()["connections"]


def test_network_requests_are_validated(client, env):
    bad_hotspot = [
        {"ssid": ""},
        {"ssid": "x" * 33},
        {"ssid": "ok", "password": "short"},
        {"ssid": "ok", "password": "p" * 64},
        {"ssid": "tab\there", "password": "long enough"},
        {"ssid": "ok", "password": "long enough", "band": "a"},
    ]
    for body in bad_hotspot:
        assert client.put("/api/network/hotspot", json=body, headers=WRITE).status_code == 422, body
    assert client.put("/api/network/wifi", json={"ssid": "HomeNet", "password": "short"}, headers=WRITE).status_code == 422
    # Nothing was changed.
    assert not any("modify" in call or "add" in call for call in env.nmcli_calls())


def test_an_ssid_cannot_smuggle_nmcli_options(client, env):
    """The name is one argument to nmcli, never parsed as options or a shell line."""
    body = {"ssid": "--help; reboot", "password": "long enough pw"}
    client.put("/api/network/hotspot", json=body, headers=WRITE)
    wait_idle(client)
    modify = next(c for c in env.nmcli_calls() if "modify" in c)
    assert modify[modify.index("802-11-wireless.ssid") + 1] == "--help; reboot"
    assert env.nm()["connections"]["midwire-hotspot"]["ssid"] == "--help; reboot"


def test_missing_nmcli_is_reported_not_fatal(env):
    from fastapi.testclient import TestClient

    client = TestClient(env.app(nmcli=("/nonexistent/nmcli",)))
    client.post("/api/login", json=LOGIN, headers=WRITE)
    status = client.get("/api/network").json()
    assert status["available"] is False
    assert "not installed" in status["error"]
