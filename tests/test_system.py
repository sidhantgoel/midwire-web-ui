from __future__ import annotations

import base64

from conftest import WRITE
from fastapi.testclient import TestClient


def public_key(seed: int = 1, comment: str = "me@laptop") -> str:
    name = b"ssh-ed25519"
    blob = len(name).to_bytes(4, "big") + name + (32).to_bytes(4, "big") + bytes([seed]) * 32
    return f"ssh-ed25519 {base64.b64encode(blob).decode()} {comment}".strip()


def strong(client) -> None:
    """Gives the page a real admin password, which the account settings need."""
    response = client.post("/api/password", json={"current": "admin", "new": "a real password"}, headers=WRITE)
    assert response.status_code == 200


def actions(env) -> list[str]:
    return [request["action"] for request in env.helper.requests]


# --- status and the SSH switch ----------------------------------------------


def test_status_shows_ssh_and_login_users(client):
    current = client.get("/api/system").json()
    assert current["supported"] is True
    assert current["ssh"] == {"installed": True, "enabled": False, "running": False}
    assert current["users"] == [{"name": "pi", "has_password": False, "sudo": True, "keys": []}]
    assert current["net_gadget"]["installed"] is True
    # Still on admin / admin.
    assert current["locked"] is True


def test_ssh_can_be_switched_even_with_the_default_admin_password(client, env):
    on = client.put("/api/system/ssh", json={"enabled": True}, headers=WRITE)
    assert on.status_code == 200
    assert on.json()["ssh"]["enabled"] is True and on.json()["ssh"]["running"] is True
    assert {"action": "ssh", "enabled": True} in env.helper.requests

    off = client.put("/api/system/ssh", json={"enabled": False}, headers=WRITE)
    assert off.json()["ssh"]["enabled"] is False


# --- the network link over the USB-C port ------------------------------------


def test_usb_c_network_link_can_be_switched(client, env):
    assert client.get("/api/system").json()["net_gadget"] == {"installed": True, "enabled": True, "active": True}

    off = client.put("/api/system/net-gadget", json={"enabled": False}, headers=WRITE)
    assert off.status_code == 200
    assert off.json()["net_gadget"]["enabled"] is False
    assert {"action": "net-gadget", "enabled": False} in env.helper.requests

    on = client.put("/api/system/net-gadget", json={"enabled": True}, headers=WRITE)
    assert on.json()["net_gadget"]["enabled"] is True
    # No free-form input reaches the helper.
    bad = client.put("/api/system/net-gadget", json={"enabled": True, "address": "1.2.3.4"}, headers=WRITE)
    assert bad.status_code == 422


def test_a_helper_without_the_usb_c_link_reports_none(client, env, monkeypatch):
    monkeypatch.setattr(type(env.helper), "_handle", lambda self, request: {"ssh": dict(self.ssh), "users": []})
    assert client.get("/api/system").json()["net_gadget"] is None


# --- the guard ---------------------------------------------------------------


def test_accounts_are_locked_while_the_admin_password_is_the_default(client, env):
    for path, body in (
        ("/api/system/password", {"user": "pi", "password": "long enough pw"}),
        ("/api/system/keys", {"user": "pi", "key": public_key()}),
        ("/api/system/keys/remove", {"user": "pi", "fingerprint": "SHA256:" + "A" * 43}),
    ):
        response = client.post(path, json=body, headers=WRITE)
        assert response.status_code == 400, path
        assert "Change the admin password first" in response.json()["detail"]
    # Nothing reached the helper except status reads.
    assert set(actions(env)) <= {"status"}


def test_accounts_are_locked_while_the_admin_password_is_empty(client, env):
    client.post("/api/password", json={"current": "admin", "new": ""}, headers=WRITE)
    assert client.get("/api/system").json()["locked"] is True
    response = client.post("/api/system/password", json={"user": "pi", "password": "long enough pw"}, headers=WRITE)
    assert response.status_code == 400
    assert "set-password" not in actions(env)


# --- passwords ---------------------------------------------------------------


def test_set_the_password_of_a_login_user(client, env):
    strong(client)
    response = client.post("/api/system/password", json={"user": "pi", "password": "long enough pw"}, headers=WRITE)
    assert response.status_code == 200, response.text
    assert response.json()["created"] is False
    assert response.json()["users"][0]["has_password"] is True
    assert response.json()["locked"] is False
    assert env.helper.users["pi"]["password"] == "long enough pw"
    # The password is in the request to the helper and nowhere in the answer.
    assert "long enough pw" not in response.text


def test_setting_a_password_creates_the_user_on_a_device_without_one(client, env):
    strong(client)
    env.helper.users.clear()
    assert client.get("/api/system").json()["users"] == []
    response = client.post("/api/system/password", json={"user": "midwire", "password": "long enough pw"},
                           headers=WRITE)
    assert response.status_code == 200
    assert response.json()["created"] is True
    assert [u["name"] for u in response.json()["users"]] == ["midwire"]


def test_the_helpers_refusal_is_shown(client, env):
    strong(client)
    response = client.post("/api/system/password", json={"user": "nobody-here", "password": "long enough pw"},
                           headers=WRITE)
    assert response.status_code == 400
    assert response.json()["detail"] == "There is no login user called nobody-here."


def test_bad_account_requests_never_reach_the_helper(client, env):
    strong(client)
    bad = [
        ("/api/system/password", {"user": "root; reboot", "password": "long enough pw"}),
        ("/api/system/password", {"user": "Pi", "password": "long enough pw"}),
        ("/api/system/password", {"user": "pi", "password": "short"}),
        ("/api/system/password", {"user": "pi", "password": "long enough pw", "shell": "/bin/sh"}),
        ("/api/system/keys", {"user": "../root", "key": public_key()}),
        ("/api/system/keys", {"user": "pi", "key": "x"}),
        ("/api/system/keys/remove", {"user": "pi", "fingerprint": "MD5:aa:bb"}),
    ]
    for path, body in bad:
        assert client.post(path, json=body, headers=WRITE).status_code == 422, body
    assert client.put("/api/system/ssh", json={"enabled": "yes please", "port": 2222}, headers=WRITE).status_code == 422
    assert set(actions(env)) <= {"status"}


# --- keys --------------------------------------------------------------------


def test_add_and_remove_an_ssh_key(client, env):
    strong(client)
    added = client.post("/api/system/keys", json={"user": "pi", "key": public_key()}, headers=WRITE)
    assert added.status_code == 200, added.text
    keys = added.json()["users"][0]["keys"]
    assert len(keys) == 1
    assert keys[0]["type"] == "ssh-ed25519" and keys[0]["comment"] == "me@laptop"
    assert keys[0]["fingerprint"].startswith("SHA256:")

    again = client.post("/api/system/keys", json={"user": "pi", "key": public_key()}, headers=WRITE)
    assert again.status_code == 400 and "already there" in again.json()["detail"]

    removed = client.post("/api/system/keys/remove", json={"user": "pi", "fingerprint": keys[0]["fingerprint"]},
                          headers=WRITE)
    assert removed.status_code == 200
    assert removed.json()["users"][0]["keys"] == []


def test_something_that_is_not_a_key_is_refused(client, env):
    strong(client)
    response = client.post("/api/system/keys", json={"user": "pi", "key": "command=\"rm -rf /\" not-a-key AAAA"},
                           headers=WRITE)
    assert response.status_code == 400
    assert "not an SSH public key" in response.json()["detail"]


# --- devices without the helper, and access ----------------------------------


def test_a_device_without_the_helper_says_so(client, env):
    env.helper.close()
    current = client.get("/api/system").json()
    assert current["supported"] is False
    assert "Updates tab" in current["reason"]
    response = client.put("/api/system/ssh", json={"enabled": True}, headers=WRITE)
    assert response.status_code == 400


def test_system_settings_need_a_login_and_the_csrf_header(client, env):
    assert env.anonymous().get("/api/system").status_code == 401
    assert env.anonymous().put("/api/system/ssh", json={"enabled": True}, headers=WRITE).status_code == 401
    assert client.put("/api/system/ssh", json={"enabled": True}).status_code == 403
    assert "ssh" not in actions(env)


# --- the setup wizard's view -------------------------------------------------


def test_setup_status_reports_what_is_still_default(client, env):
    assert client.get("/api/setup").json() == {"admin_password_default": True, "hotspot_password_default": False}

    # The hotspot has the image's default password.
    env.firstboot_conf.write_text("HOTSPOT_DEFAULT_PASSWORD=initial-pass\n")
    assert client.get("/api/setup").json()["hotspot_password_default"] is True

    strong(client)
    assert client.get("/api/setup").json()["admin_password_default"] is False


def test_changing_the_hotspot_password_clears_the_reminder(client, env):
    from conftest import wait_idle

    env.firstboot_conf.write_text("HOTSPOT_DEFAULT_PASSWORD='initial-pass'\n")
    assert client.get("/api/setup").json()["hotspot_password_default"] is True
    client.put("/api/network/hotspot", json={"ssid": "Midwire-1A2B", "password": "my own password"}, headers=WRITE)
    wait_idle(client)
    assert client.get("/api/setup").json()["hotspot_password_default"] is False


def test_no_default_configured_means_no_reminder(client, env):
    for content in ("HOTSPOT_DEFAULT_PASSWORD=\n", "WIFI_COUNTRY=GB\n"):
        env.firstboot_conf.write_text(content)
        assert client.get("/api/setup").json()["hotspot_password_default"] is False
    env.firstboot_conf.unlink()
    assert client.get("/api/setup").json()["hotspot_password_default"] is False


def test_setup_status_needs_a_login(env):
    assert TestClient(env.app()).get("/api/setup").status_code == 401
