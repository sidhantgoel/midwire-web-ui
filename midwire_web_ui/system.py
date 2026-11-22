"""SSH and login accounts.

The work is done by the root-owned helper in the midwire-base package,
/usr/lib/midwire/system, reached over a local socket that only this
service's user may open. This module sends it one JSON request per
connection and returns its answer. The helper does its own strict checking
of everything it is given; the request shapes below are a first line, not
the only one.
"""

from __future__ import annotations

import json
import socket
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from .config import Settings
from .service import RequestError

_TIMEOUT_SECONDS = 90
_MAX_ANSWER = 256 * 1024

UserName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,30}$")]


class SshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class SystemPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user: UserName
    password: Annotated[str, Field(min_length=8, max_length=128)]


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user: UserName
    key: Annotated[str, Field(min_length=20, max_length=8192)]


class KeyRemoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user: UserName
    fingerprint: Annotated[str, Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")]


class Unsupported(RequestError):
    """The device has no system helper (midwire-base older than 0.3.0)."""


def _call(settings: Settings, request: dict) -> dict:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(_TIMEOUT_SECONDS)
            connection.connect(str(settings.system_socket))
            connection.sendall(json.dumps(request).encode() + b"\n")
            # The helper reads until end of input.
            connection.shutdown(socket.SHUT_WR)
            chunks, size = [], 0
            while size <= _MAX_ANSWER:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        raise Unsupported(
            "This device cannot manage SSH from the page yet. Update Midwire from the Updates tab."
        ) from exc
    except PermissionError as exc:
        raise RequestError("The web UI is not allowed to reach the system helper.") from exc
    except OSError as exc:
        raise RequestError("The system helper did not answer.") from exc

    try:
        answer = json.loads(b"".join(chunks).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise RequestError("The system helper gave an answer that could not be read.") from exc
    if not isinstance(answer, dict):
        raise RequestError("The system helper gave an answer that could not be read.")
    if answer.get("ok") is not True:
        error = answer.get("error")
        raise RequestError(error if isinstance(error, str) and error else "The system helper refused.")
    return answer


def status(settings: Settings) -> dict:
    try:
        answer = _call(settings, {"action": "status"})
    except Unsupported as exc:
        return {"supported": False, "reason": str(exc)}
    except RequestError as exc:
        return {"supported": False, "reason": str(exc)}
    return {"supported": True, "ssh": answer.get("ssh") or {}, "users": answer.get("users") or []}


def set_ssh(settings: Settings, request: SshRequest) -> dict:
    return _call(settings, {"action": "ssh", "enabled": request.enabled})


def set_password(settings: Settings, request: SystemPasswordRequest) -> dict:
    return _call(settings, {"action": "set-password", "user": request.user, "password": request.password})


def add_key(settings: Settings, request: KeyRequest) -> dict:
    return _call(settings, {"action": "add-key", "user": request.user, "key": request.key})


def remove_key(settings: Settings, request: KeyRemoveRequest) -> dict:
    return _call(settings, {"action": "remove-key", "user": request.user, "fingerprint": request.fingerprint})
