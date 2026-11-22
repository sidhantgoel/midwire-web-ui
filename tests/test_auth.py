from __future__ import annotations

from conftest import LOGIN, WRITE

from midwire_web_ui import auth
from midwire_web_ui.auth import SESSION_COOKIE


def login(browser, password: str, username: str = "admin"):
    return browser.post("/api/login", json={"username": username, "password": password}, headers=WRITE)


def test_nothing_answers_without_a_login(env):
    browser = env.anonymous()
    session = browser.get("/api/session").json()
    assert session["authenticated"] is False
    assert session["default_password"] is True
    for path in ("/api/state", "/api/network", "/api/network/scan", "/api/logs", "/api/captures/x.pcap"):
        response = browser.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"] == "login_required"
    assert browser.post("/api/stop", headers=WRITE).status_code == 401
    assert env.calls() == []


def test_a_new_device_logs_in_with_admin_admin(env):
    browser = env.anonymous()
    assert login(browser, "wrong").status_code == 401
    assert login(browser, "admin", username="root").status_code == 401
    assert browser.post("/api/login", json=LOGIN).status_code == 403  # no CSRF header

    response = login(browser, "admin")
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie

    session = browser.get("/api/session").json()
    assert session["authenticated"] is True
    # Still the default: the page offers to change it.
    assert session["default_password"] is True
    assert browser.get("/api/state").status_code == 200


def test_changing_the_default_password(client, env):
    wrong = client.post("/api/password", json={"current": "nope", "new": "a better one"}, headers=WRITE)
    assert wrong.status_code == 400
    same = client.post("/api/password", json={"current": "admin", "new": "admin"}, headers=WRITE)
    assert same.status_code == 400

    ok = client.post("/api/password", json={"current": "admin", "new": "a better one"}, headers=WRITE)
    assert ok.status_code == 200
    assert client.get("/api/session").json()["default_password"] is False
    assert client.get("/api/state").status_code == 200  # this browser stays logged in

    stored = env.settings.password_file.read_text()
    assert stored.startswith("scrypt$") and "a better one" not in stored
    assert env.settings.password_file.stat().st_mode & 0o077 == 0

    # A restart keeps the new password and forgets the default.
    browser = env.anonymous()
    assert login(browser, "admin").status_code == 401
    assert login(browser, "a better one").status_code == 200


def test_an_empty_password_can_be_set(client, env):
    ok = client.post("/api/password", json={"current": "admin", "new": ""}, headers=WRITE)
    assert ok.status_code == 200
    assert client.get("/api/session").json()["default_password"] is False

    browser = env.anonymous()
    assert login(browser, "admin").status_code == 401
    assert login(browser, "").status_code == 200
    # A login is still needed, and the name still has to be right.
    other = env.anonymous()
    assert other.get("/api/state").status_code == 401
    assert login(other, "", username="root").status_code == 401

    back = browser.post("/api/password", json={"current": "", "new": "something else"}, headers=WRITE)
    assert back.status_code == 200


def test_changing_the_password_logs_out_other_browsers(client, env):
    app = env.app()
    from fastapi.testclient import TestClient

    first, second = TestClient(app), TestClient(app)
    assert login(first, "admin").status_code == 200
    assert login(second, "admin").status_code == 200
    first.post("/api/password", json={"current": "admin", "new": "a better one"}, headers=WRITE)
    assert first.get("/api/state").status_code == 200
    assert second.get("/api/state").status_code == 401


def test_logout(client):
    assert client.post("/api/logout", headers=WRITE).status_code == 200
    assert client.get("/api/state").status_code == 401
    assert client.get("/api/session").json()["authenticated"] is False


def test_a_made_up_cookie_is_not_a_session(env):
    browser = env.anonymous()
    browser.cookies.set(SESSION_COOKIE, "not-a-real-token")
    assert browser.get("/api/state").status_code == 401


def test_repeated_wrong_passwords_lock_out(env, monkeypatch):
    monkeypatch.setattr(auth, "_MAX_FAILURES", 3)
    browser = env.anonymous()
    for _ in range(3):
        assert login(browser, "wrong").status_code == 401
    locked = login(browser, "admin")
    assert locked.status_code == 429
    assert "Try again" in locked.json()["detail"]
