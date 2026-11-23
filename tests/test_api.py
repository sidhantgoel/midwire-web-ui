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


def test_boot_drive_is_flagged_and_network_interfaces_are_listed(client):
    found = devices(client)
    assert found["2-1"]["system"] is True
    assert found["1-1.2"]["system"] is False
    assert found["1-1.4"]["network_interfaces"] == ["eth1"]
    assert found["1-1.2"]["network_interfaces"] == []
    assert found["1-1.2"]["warnings"] == []


def test_a_network_interface_that_is_down_does_not_count(client, env):
    # What the Midwire image does to USB network interfaces: leaves them down.
    (env.sysfs / "class" / "net" / "eth1" / "flags").write_text("0x1002")
    assert devices(client)["1-1.4"]["network_interfaces"] == []


def test_state_names_the_interface_the_page_arrived_on(client, monkeypatch):
    from midwire_web_ui import netinfo

    # The test client's "server" is not an address of any interface.
    assert client.get("/api/state").json()["page_interface"] is None
    monkeypatch.setattr(netinfo, "interface_for_address", lambda address: "eth1")
    assert client.get("/api/state").json()["page_interface"] == "eth1"


def test_interface_lookup_copes_with_anything():
    from midwire_web_ui.netinfo import interface_for_address

    assert interface_for_address("testserver") is None
    assert interface_for_address("203.0.113.77") is None  # nobody's address
    assert interface_for_address("127.0.0.1") == "lo"


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


def test_delete_all_captures(client, env):
    for name in ("20261122-140000_046d_c52b.pcap", "20261123-090000_2ca3_0020.pcap"):
        (env.settings.captures_dir / name).write_bytes(b"x")
    (env.settings.captures_dir / "notes.txt").write_text("not a capture")
    assert client.delete("/api/captures").status_code == 403  # no CSRF header

    response = client.delete("/api/captures", headers=WRITE)
    assert response.status_code == 200
    assert response.json() == {"deleted": 2, "kept": None, "captures": []}
    # Only captures go. Anything else in the folder is left alone.
    assert [p.name for p in env.settings.captures_dir.iterdir()] == ["notes.txt"]
    assert client.delete("/api/captures", headers=WRITE).json()["deleted"] == 0


def test_delete_all_keeps_the_capture_being_written(client, env):
    started = client.post("/api/start", json={**RECEIVER, "capture": True}, headers=WRITE)
    current = started.json()["status"]["capture"]
    (env.settings.captures_dir / current).write_bytes(b"live")
    (env.settings.captures_dir / "20261122-140000_046d_c52b.pcap").write_bytes(b"old")

    response = client.delete("/api/captures", headers=WRITE)
    assert response.json()["deleted"] == 1 and response.json()["kept"] == current
    assert [c["name"] for c in response.json()["captures"]] == [current]
    assert (env.settings.captures_dir / current).read_bytes() == b"live"


def test_delete_all_removes_a_symlink_not_its_target(client, env):
    outside = env.settings.captures_dir.parent / "precious.pcap"
    outside.write_text("precious")
    (env.settings.captures_dir / "link.pcap").symlink_to(outside)
    assert client.delete("/api/captures", headers=WRITE).json()["deleted"] == 1
    assert outside.read_text() == "precious"
    assert not (env.settings.captures_dir / "link.pcap").exists()


def test_state_names_the_usb_link_interface_while_the_link_is_up(client, env):
    assert client.get("/api/state").json()["usb_link_interface"] is None
    env.usb_link_state.write_text("INTERFACE=usb0" + chr(10))
    assert client.get("/api/state").json()["usb_link_interface"] == "usb0"
    for junk in ("INTERFACE=../../etc/passwd", "INTERFACE=", "garbage", "INTERFACE=name with spaces"):
        env.usb_link_state.write_text(junk + chr(10))
        assert client.get("/api/state").json()["usb_link_interface"] is None, junk


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
