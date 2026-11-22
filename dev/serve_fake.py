#!/usr/bin/env python3
"""Runs the web UI against a fake Pi, for working on the frontend without
hardware:

    python3 dev/serve_fake.py            # http://127.0.0.1:8080, login admin / admin

Needs Linux (the fake sysfs tree uses symlinks). Everything it writes goes
into a temporary folder that is removed on exit.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dev import fake_sysfs  # noqa: E402
from dev.fake_system_helper import FakeSystemHelper  # noqa: E402


def main() -> None:
    import uvicorn

    from midwire_web_ui.app import create_app
    from midwire_web_ui.config import Settings

    with tempfile.TemporaryDirectory(prefix="midwire-fake-") as tmp:
        root = Path(tmp)
        for name in ("state", "run", "captures", "etc", "lib"):
            (root / name).mkdir()
        os.environ["FAKE_STATE_DIR"] = str(root / "state")
        os.environ["FAKE_JOURNAL_FOLLOW"] = "1"
        os.environ["FAKE_UPDATE_STATUS"] = str(root / "lib" / "update.json")
        mounts = fake_sysfs.build(root / "sys")
        (root / "etc" / "config.json").write_text("{}")
        (root / "etc" / "injection.json").write_text("{}")
        (root / "etc" / "mouse-swap.json").write_text("{}")
        (root / "raw-gadget").touch()
        # A device fresh from the image: the hotspot still has the default
        # password (the fake nmcli's is "initial-pass"), and no login user.
        (root / "etc" / "firstboot.conf").write_text("HOTSPOT_DEFAULT_PASSWORD=initial-pass" + chr(10))
        FakeSystemHelper(root / "sys.sock")
        (root / "captures" / "20261122-140000_046d_c52b.pcap").write_bytes(b"\0" * 48_213)

        def fake(name: str) -> tuple[str, str]:
            return (sys.executable, str(REPO / "dev" / f"fake_{name}.py"))

        settings = Settings(
            host=os.environ.get("MIDWIRE_WEBUI_HOST", "127.0.0.1"),
            port=int(os.environ.get("MIDWIRE_WEBUI_PORT", "8080")),
            password_file=root / "lib" / "password",
            prefs_file=root / "lib" / "settings.json",
            sysfs=root / "sys",
            proc_mounts=mounts,
            raw_gadget_dev=root / "raw-gadget",
            args_file=root / "run" / "args",
            captures_dir=root / "captures",
            config_dir=root / "etc",
            unit="usb-proxy.service",
            wifi_interface="wlan0",
            systemctl=fake("systemctl"),
            journalctl=fake("journalctl"),
            nmcli=fake("nmcli"),
            update_status_file=root / "lib" / "update.json",
            system_socket=root / "sys.sock",
            firstboot_conf=root / "etc" / "firstboot.conf",
        )
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
