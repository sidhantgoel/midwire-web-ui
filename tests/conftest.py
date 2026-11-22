from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dev import fake_sysfs  # noqa: E402
from midwire_web_ui import network  # noqa: E402
from midwire_web_ui.app import create_app  # noqa: E402
from midwire_web_ui.auth import CSRF_HEADER  # noqa: E402
from midwire_web_ui.config import Settings  # noqa: E402

WRITE = {CSRF_HEADER: "1"}
# A new device logs in with admin / admin.
LOGIN = {"username": "admin", "password": "admin"}


def fake(name: str) -> tuple[str, str]:
    return (sys.executable, str(REPO / "dev" / f"fake_{name}.py"))


class Env:
    """A fake Pi: sysfs tree, config and capture folders, and stand-ins for
    systemctl, journalctl and nmcli."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        self.state_dir = tmp_path / "state"
        self.state_dir.mkdir()
        monkeypatch.setenv("FAKE_STATE_DIR", str(self.state_dir))
        # Where the fake systemctl, playing the updater, writes its status.
        monkeypatch.setenv("FAKE_UPDATE_STATUS", str(tmp_path / "lib" / "update.json"))
        # Network changes wait a second for the HTTP response to leave.
        monkeypatch.setattr(network, "_SWITCH_DELAY", 0)

        self.sysfs = tmp_path / "sys"
        mounts = fake_sysfs.build(self.sysfs)
        for name in ("run", "captures", "etc", "lib"):
            (tmp_path / name).mkdir()
        (tmp_path / "etc" / "config.json").write_text("{}")
        (tmp_path / "etc" / "injection.json").write_text("{}")
        (tmp_path / "raw-gadget").touch()

        self.settings = Settings(
            host="127.0.0.1",
            port=8080,
            password_file=tmp_path / "lib" / "password",
            prefs_file=tmp_path / "lib" / "settings.json",
            sysfs=self.sysfs,
            proc_mounts=mounts,
            raw_gadget_dev=tmp_path / "raw-gadget",
            args_file=tmp_path / "run" / "args",
            captures_dir=tmp_path / "captures",
            config_dir=tmp_path / "etc",
            unit="usb-proxy.service",
            wifi_interface="wlan0",
            systemctl=fake("systemctl"),
            journalctl=fake("journalctl"),
            nmcli=fake("nmcli"),
            update_status_file=tmp_path / "lib" / "update.json",
        )

    def app(self, **overrides):
        return create_app(replace(self.settings, **overrides), watch_devices=False)

    def anonymous(self) -> TestClient:
        return TestClient(self.app())

    def calls(self) -> list[str]:
        log = self.state_dir / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    def nmcli_calls(self) -> list[list[str]]:
        log = self.state_dir / "nmcli.log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def nm(self) -> dict:
        return json.loads((self.state_dir / "nm.json").read_text())

    def args(self) -> list[str]:
        data = self.settings.args_file.read_bytes()
        assert data.endswith(b"\0")
        return data[:-1].decode().split("\0")

    def unplug(self, dev_id: str) -> None:
        (self.sysfs / "bus" / "usb" / "devices" / dev_id).rename(self.sysfs / f"unplugged-{dev_id}")

    def plug(self, dev_id: str) -> None:
        (self.sysfs / f"unplugged-{dev_id}").rename(self.sysfs / "bus" / "usb" / "devices" / dev_id)


@pytest.fixture
def env(tmp_path, monkeypatch) -> Env:
    return Env(tmp_path, monkeypatch)


@pytest.fixture
def client(env) -> TestClient:
    """A browser that is logged in."""
    client = env.anonymous()
    assert client.post("/api/login", json=LOGIN, headers=WRITE).status_code == 200
    return client


def wait_idle(client: TestClient, timeout: float = 5.0) -> dict:
    """Waits for a background network change to finish."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get("/api/network").json()
        if not status["busy"]:
            return status
        time.sleep(0.02)
    raise AssertionError("network change did not finish")
