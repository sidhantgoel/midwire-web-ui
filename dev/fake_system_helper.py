"""Stands in for midwire-base's system helper: a unix socket that answers the
same requests from memory. For tests and the local preview. The real helper
(and its checking of users and keys) is tested in the midwire repository."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import threading
from pathlib import Path


def fingerprint(blob: str) -> str:
    digest = hashlib.sha256(base64.b64decode(blob)).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class FakeSystemHelper:
    def __init__(self, path: Path, users: list[str] | None = None):
        self.path = path
        self.ssh = {"installed": True, "enabled": False, "running": False}
        self.net_gadget = {"installed": True, "enabled": True, "active": True}
        self.users = {name: {"password": None, "keys": []} for name in (users or [])}
        # Every request received, for tests to look at.
        self.requests: list[dict] = []
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(path))
        self._server.listen(8)
        self._thread = threading.Thread(target=self._serve, name="fake-system-helper", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.close()
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self._server.accept()
            except OSError:
                return
            with connection:
                data = b""
                while chunk := connection.recv(65536):
                    data += chunk
                try:
                    request = json.loads(data.decode())
                    self.requests.append(request)
                    answer = {"ok": True, **self._handle(request)}
                except ValueError as error:
                    answer = {"ok": False, "error": str(error) or "The request is not valid JSON."}
                try:
                    connection.sendall(json.dumps(answer).encode() + b"\n")
                except OSError:
                    pass

    def _status_users(self) -> list[dict]:
        return [
            {"name": name, "has_password": user["password"] is not None, "sudo": True,
             "keys": [{k: key[k] for k in ("type", "fingerprint", "comment", "restricted")} for key in user["keys"]]}
            for name, user in self.users.items()
        ]

    def _handle(self, request: dict) -> dict:
        action = request.get("action")
        if action == "status":
            return {"ssh": dict(self.ssh), "net_gadget": dict(self.net_gadget), "users": self._status_users()}
        if action == "ssh":
            self.ssh["enabled"] = self.ssh["running"] = bool(request["enabled"])
            return {"ssh": dict(self.ssh)}

        if action == "net-gadget":
            self.net_gadget["enabled"] = self.net_gadget["active"] = bool(request["enabled"])
            return {"net_gadget": dict(self.net_gadget)}

        name = request.get("user")
        if action == "set-password":
            created = False
            if name not in self.users:
                if self.users:
                    raise ValueError(f"There is no login user called {name}.")
                self.users[name] = {"password": None, "keys": []}
                created = True
            self.users[name]["password"] = request["password"]
            return {"created": created, "user": name}

        if name not in self.users:
            raise ValueError(f"There is no login user called {name}.")
        keys = self.users[name]["keys"]
        if action == "add-key":
            fields = request["key"].split(None, 2)
            if len(fields) < 2 or not fields[0].startswith(("ssh-", "ecdsa-", "sk-")):
                raise ValueError("That is not an SSH public key. It should start with ssh-ed25519, ssh-rsa or ecdsa-sha2-.")
            entry = {"type": fields[0], "fingerprint": fingerprint(fields[1]),
                     "comment": fields[2] if len(fields) > 2 else "", "restricted": False}
            if any(key["fingerprint"] == entry["fingerprint"] for key in keys):
                raise ValueError("That key is already there.")
            keys.append(entry)
        elif action == "remove-key":
            remaining = [key for key in keys if key["fingerprint"] != request["fingerprint"]]
            if len(remaining) == len(keys):
                raise ValueError("That key is not there any more.")
            self.users[name]["keys"] = remaining
        else:
            raise ValueError("Unknown request.")
        return {"user": name, "keys": self._status_users()[list(self.users).index(name)]["keys"]}
