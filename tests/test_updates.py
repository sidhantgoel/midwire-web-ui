from __future__ import annotations

import json

from conftest import WRITE

CHECK = "--no-ask-password start --no-block midwire-update-check.service"
INSTALL = "--no-ask-password start --no-block midwire-update-install.service"


def status(client) -> dict:
    response = client.get("/api/updates")
    assert response.status_code == 200
    return response.json()


def test_before_any_check(client):
    current = status(client)
    assert current["supported"] is True
    assert current["state"] == "idle"
    assert current["packages"] == [] and current["update_available"] is False
    assert current["checked"] is None and current["last_install"] is None


def test_check_starts_the_check_service_and_reports_what_it_found(client, env):
    assert client.post("/api/updates/check", headers=WRITE).status_code == 202
    assert CHECK in env.calls()

    current = status(client)
    assert current["update_available"] is True
    assert current["check_error"] is None and current["checked"] > 0
    by_name = {p["name"]: p for p in current["packages"]}
    assert list(by_name) == ["midwire-base", "midwire-web-ui", "usb-proxy", "raw-gadget-dkms"]
    assert by_name["midwire-web-ui"] == {
        "name": "midwire-web-ui", "installed": "0.2.0", "available": "0.3.0", "upgradable": True,
    }
    assert by_name["usb-proxy"]["upgradable"] is False


def test_install_starts_the_install_service(client, env):
    client.post("/api/updates/check", headers=WRITE)
    assert client.post("/api/updates/install", headers=WRITE).status_code == 202
    assert INSTALL in env.calls()

    current = status(client)
    assert current["update_available"] is False
    assert current["last_install"]["ok"] is True
    assert current["last_install"]["upgraded"] == [{"name": "midwire-web-ui", "from": "0.2.0", "to": "0.3.0"}]


def test_running_state_comes_from_systemd_not_the_file(client, env):
    # The file says idle (or does not exist); systemd says the unit runs.
    (env.state_dir / "midwire-update-install.service.running").touch()
    assert status(client)["state"] == "installing"
    again = client.post("/api/updates/install", headers=WRITE)
    assert again.status_code == 400 and "already" in again.json()["detail"]
    busy = client.post("/api/updates/check", headers=WRITE)
    assert busy.status_code == 400
    assert INSTALL not in env.calls() and CHECK not in env.calls()

    (env.state_dir / "midwire-update-install.service.running").unlink()
    (env.state_dir / "midwire-update-check.service.running").touch()
    assert status(client)["state"] == "checking"


def test_a_device_without_the_updater_says_so(client, env):
    (env.state_dir / "no-updater").touch()
    current = status(client)
    assert current["supported"] is False
    assert "midwire-base" in current["reason"]
    assert client.post("/api/updates/check", headers=WRITE).status_code == 400
    assert client.post("/api/updates/install", headers=WRITE).status_code == 400
    assert CHECK not in env.calls() and INSTALL not in env.calls()


def test_a_failed_check_is_shown(client, env):
    env.settings.update_status_file.write_text(json.dumps({
        "state": "idle", "checked": 1795360000, "check_error": "Could not reach the Midwire package repository.",
        "packages": [{"name": "midwire-web-ui", "installed": "0.2.0", "available": None, "upgradable": False}],
        "last_install": None,
    }))
    current = status(client)
    assert current["check_error"] == "Could not reach the Midwire package repository."
    assert current["packages"][0]["available"] is None
    assert current["update_available"] is False


def test_a_damaged_status_file_does_not_break_the_page(client, env):
    for junk in ("{ not json", "[1, 2, 3]", json.dumps({"packages": "nope", "last_install": 7, "checked": "x"}),
                 json.dumps({"packages": [{"name": 5}, "x", {"name": "ok", "upgradable": "yes"}]})):
        env.settings.update_status_file.write_text(junk)
        current = status(client)
        assert current["supported"] is True
        assert current["update_available"] is False


def test_denied_by_polkit_is_reported(client, env):
    (env.state_dir / "fail").touch()
    # With every systemctl call denied, even the status cannot be read.
    assert status(client)["supported"] is False
    assert client.post("/api/updates/install", headers=WRITE).status_code == 400


def test_updates_need_a_login_and_the_csrf_header(client, env):
    assert env.anonymous().get("/api/updates").status_code == 401
    assert env.anonymous().post("/api/updates/install", headers=WRITE).status_code == 401
    assert client.post("/api/updates/install").status_code == 403
    assert INSTALL not in env.calls()


def test_no_request_can_name_a_package_or_command(client, env):
    """The endpoints take no input. Whatever is sent, systemctl gets the
    same fixed arguments."""
    body = {"packages": ["evil"], "command": "rm -rf /", "unit": "ssh.service"}
    client.post("/api/updates/install", json=body, headers=WRITE)
    client.post("/api/updates/check?unit=ssh.service", json=body, headers=WRITE)
    starts = [call for call in env.calls() if " start " in f" {call} "]
    assert sorted(starts) == sorted([CHECK, INSTALL])


def test_update_log_streams_the_updater_journal(client):
    with client.stream("GET", "/api/updates/log") as response:
        body = "".join(response.iter_text())
    lines = [line for event in body.split("\n\n") if event.startswith("data: ")
             for line in json.loads(event[len("data: "):])]
    assert any("Upgrading midwire-web-ui" in line for line in lines)
    assert all("usb-proxy[" not in line for line in lines)
