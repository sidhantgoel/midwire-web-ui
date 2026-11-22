from __future__ import annotations

import json
import re

from conftest import WRITE

RECEIVER = {"device_id": "1-1.2", "udc": "fe980000.usb"}
CAMERA = {"device_id": "1-1.3", "udc": "fe980000.usb"}


def devices(client) -> dict:
    return {d["id"]: d for d in client.get("/api/state").json()["devices"]}


# --- what the page is shown -------------------------------------------------


def test_state_lists_devices_without_hubs(client):
    state = client.get("/api/state").json()
    assert [d["id"] for d in state["devices"]] == ["1-1.2", "1-1.3", "1-1.4", "2-1"]
    assert state["udcs"] == [{"name": "fe980000.usb", "driver": "fe980000.usb", "state": "not attached"}]
    assert state["raw_gadget"] is True
    assert state["injection_files"] == ["injection.json"]
    assert state["status"]["state"] == "inactive"


def test_device_details_come_from_sysfs(client):
    receiver = devices(client)["1-1.2"]
    assert (receiver["vendor_id"], receiver["product_id"]) == ("046d", "c52b")
    assert receiver["manufacturer"] == "Logitech"
    assert [i["number"] for i in receiver["interfaces"]] == [0, 1, 2]
    assert receiver["interfaces"][0]["class_name"] == "HID"
    assert receiver["interfaces"][0]["driver"] == "usbhid"


def test_endpoints_are_counted_over_all_alternate_settings(client):
    camera = {i["number"]: i for i in devices(client)["1-1.3"]["interfaces"]}
    # Interface 1 has no endpoints in alt 0 and one IN endpoint in alt 1.
    assert camera[1]["endpoints_in"] == 1
    assert camera[1]["name"] == "Video Streaming"
    assert camera[2]["endpoints_in"] == 0


def test_boot_drive_is_flagged_and_network_adapter_warns(client):
    found = devices(client)
    assert found["2-1"]["system"] is True
    assert found["1-1.2"]["system"] is False
    assert any("eth1" in w for w in found["1-1.4"]["warnings"])
    assert found["1-1.2"]["warnings"] == []


# --- starting and stopping --------------------------------------------------


def test_start_writes_args_and_restarts_the_unit(client, env):
    response = client.post("/api/start", json=RECEIVER, headers=WRITE)
    assert response.status_code == 200, response.text
    assert env.args() == [
        "--device=fe980000.usb",
        "--driver=fe980000.usb",
        "--vendor_id=046d",
        "--product_id=c52b",
    ]
    assert "--no-ask-password restart usb-proxy.service" in env.calls()
    assert response.json()["status"]["state"] == "active"
    assert response.json()["status"]["args"] == env.args()


def test_start_with_every_option(client, env):
    request = {
        **CAMERA,
        "hide_interfaces": [3, 2, 3],
        "auto_remap_endpoints": True,
        "iso_batch_size": 16,
        "injection_file": "injection.json",
        "customized_config": True,
        "capture": True,
        "verbose": 2,
    }
    response = client.post("/api/start", json=request, headers=WRITE)
    assert response.status_code == 200, response.text
    args = env.args()
    assert args[:4] == [
        "--device=fe980000.usb",
        "--driver=fe980000.usb",
        "--vendor_id=0c45",
        "--product_id=6366",
    ]
    assert args[4:11] == [
        "-v",
        "-v",
        "--auto_remap_endpoints",
        "--hide_interface=2",
        "--hide_interface=3",
        "--iso_batch_size=16",
        f"--injection_file={env.settings.config_dir / 'injection.json'}",
    ]
    assert args[11] == "--enable_customized_config"
    assert re.fullmatch(
        re.escape(f"--pcap={env.settings.captures_dir}/") + r"\d{8}-\d{6}_0c45_6366\.pcap", args[12]
    )
    assert response.json()["status"]["capture"].endswith("_0c45_6366.pcap")


def test_stop(client, env):
    client.post("/api/start", json=RECEIVER, headers=WRITE)
    response = client.post("/api/stop", headers=WRITE)
    assert response.status_code == 200
    assert response.json()["status"]["state"] == "inactive"
    assert response.json()["status"]["args"] == []
    assert "--no-ask-password stop usb-proxy.service" in env.calls()


def rejected(client, env, request, status=400) -> str:
    response = client.post("/api/start", json=request, headers=WRITE)
    assert response.status_code == status, response.text
    assert not env.settings.args_file.exists()
    assert not any("restart" in call for call in env.calls())
    return json.dumps(response.json())


def test_start_refuses_the_boot_drive(client, env):
    assert "boots from" in rejected(client, env, {"device_id": "2-1", "udc": "fe980000.usb"})


def test_start_refuses_what_sysfs_does_not_list(client, env):
    assert "no longer attached" in rejected(client, env, {**RECEIVER, "device_id": "9-9"})
    assert "controller" in rejected(client, env, {**RECEIVER, "udc": "dummy_udc.0"})
    assert "injection file" in rejected(client, env, {**RECEIVER, "injection_file": "../config.json"})
    assert "injection file" in rejected(client, env, {**RECEIVER, "injection_file": "config.json"})
    # A hub is filtered out of the device list, so it cannot be picked either.
    assert "no longer attached" in rejected(client, env, {**RECEIVER, "device_id": "1-1"})


def test_start_checks_hidden_interfaces(client, env):
    assert "no interface 7" in rejected(client, env, {**RECEIVER, "hide_interfaces": [7]})
    assert "At least one" in rejected(client, env, {**RECEIVER, "hide_interfaces": [0, 1, 2]})


def test_start_rejects_malformed_requests(client, env):
    rejected(client, env, {**RECEIVER, "iso_batch_size": 99}, status=422)
    rejected(client, env, {**RECEIVER, "verbose": 5}, status=422)
    rejected(client, env, {**RECEIVER, "extra_args": ["--pcap=/etc/passwd"]}, status=422)
    rejected(client, env, {**RECEIVER, "hide_interfaces": ["0; rm -rf /"]}, status=422)
    rejected(client, env, {"udc": "fe980000.usb"}, status=422)


def test_systemctl_failure_is_reported(client, env):
    (env.state_dir / "fail").touch()
    response = client.post("/api/start", json=RECEIVER, headers=WRITE)
    assert response.status_code == 400
    assert "Access denied" in response.json()["detail"]


def test_unit_not_installed(client, env):
    (env.state_dir / "not-found").touch()
    status = client.get("/api/state").json()["status"]
    assert status["state"] == "unknown"
    assert "not installed" in status["error"]


# --- captures ---------------------------------------------------------------


def test_captures_list_download_delete(client, env):
    capture = env.settings.captures_dir / "20261122-140000_046d_c52b.pcap"
    capture.write_bytes(b"\xd4\xc3\xb2\xa1pcap")
    (env.settings.captures_dir / "notes.txt").write_text("not a capture")

    listed = client.get("/api/state").json()["captures"]
    assert [c["name"] for c in listed] == [capture.name]
    assert listed[0]["size"] == 8

    download = client.get(f"/api/captures/{capture.name}")
    assert download.status_code == 200
    assert download.content == b"\xd4\xc3\xb2\xa1pcap"
    assert capture.name in download.headers["content-disposition"]

    assert client.delete(f"/api/captures/{capture.name}", headers=WRITE).status_code == 200
    assert not capture.exists()


def test_capture_names_cannot_leave_the_folder(client, env):
    secret = env.settings.captures_dir.parent / "secret.pcap"
    secret.write_text("secret")
    for name in ("..%2Fsecret.pcap", "%2e%2e%2fsecret.pcap", "notes.txt", ".hidden.pcap"):
        assert client.get(f"/api/captures/{name}").status_code == 404, name
        # A name with a slash in it never reaches the captures route. With the
        # built frontend present, the static file handler answers 405 instead.
        assert client.delete(f"/api/captures/{name}", headers=WRITE).status_code in (404, 405), name
        assert secret.read_text() == "secret"
    link = env.settings.captures_dir / "link.pcap"
    link.symlink_to(secret)
    assert client.get("/api/captures/link.pcap").status_code == 404
    assert secret.exists()


def test_capture_in_use_cannot_be_deleted(client, env):
    response = client.post("/api/start", json={**RECEIVER, "capture": True}, headers=WRITE)
    name = response.json()["status"]["capture"]
    (env.settings.captures_dir / name).write_bytes(b"x")
    assert client.delete(f"/api/captures/{name}", headers=WRITE).status_code == 400
    client.post("/api/stop", headers=WRITE)
    assert client.delete(f"/api/captures/{name}", headers=WRITE).status_code == 200


# --- logs -------------------------------------------------------------------


def test_logs_stream_journal_lines(client):
    with client.stream("GET", "/api/logs") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    lines = [
        line
        for event in body.split("\n\n")
        if event.startswith("data: ")
        for line in json.loads(event[len("data: "):])
    ]
    assert len(lines) == 6
    assert lines[2].endswith("usb-proxy[4242]: Device opened successfully")


# --- access control ---------------------------------------------------------


def test_writes_need_the_csrf_header(client, env):
    assert client.post("/api/start", json=RECEIVER).status_code == 403
    assert client.post("/api/stop").status_code == 403
    assert env.calls() == []
