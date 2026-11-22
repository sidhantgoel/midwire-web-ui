"""Admin password, login sessions and the request guard.

A new device logs in with admin / admin. The page offers to change that
right after the first login and keeps a reminder up until it is changed.
Every API call needs a session cookie from a login. The static frontend is
always served; it holds no data.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

USERNAME = "admin"
# In force until a password file exists, i.e. until the user changes it.
DEFAULT_PASSWORD = "admin"
SESSION_COOKIE = "midwire_session"
SESSION_SECONDS = 7 * 24 * 3600
# An empty password is allowed: the owner may run this on a closed bench network.
MIN_PASSWORD_LENGTH = 0

# Browsers cannot add this header to a cross-site request without a CORS
# preflight, which this app never approves. With the SameSite=Strict cookie
# this blocks CSRF.
CSRF_HEADER = "x-midwire"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Reachable without a session: they are how a session is obtained.
OPEN_PATHS = {"/api/session", "/api/login", "/api/logout"}

# After this many wrong passwords in a row from one address, that address
# waits before it may try again.
_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 30

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.strip().split("$")
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return hmac.compare_digest(digest, expected)


class LockedOut(Exception):
    def __init__(self, seconds: int):
        self.seconds = seconds


class Authenticator:
    def __init__(self, password_file: Path):
        self._password_file = password_file
        self._lock = threading.Lock()
        # Sessions live in memory: restarting the service logs everyone out.
        self._sessions: dict[str, float] = {}
        self._failures: dict[str, tuple[int, float]] = {}

    def stored_hash(self) -> str | None:
        try:
            return self._password_file.read_text().strip() or None
        except OSError:
            return None

    @property
    def uses_default_password(self) -> bool:
        return self.stored_hash() is None

    def _matches(self, password: str) -> bool:
        stored = self.stored_hash()
        if stored is None:
            return hmac.compare_digest(password.encode(), DEFAULT_PASSWORD.encode())
        return verify_password(password, stored)

    def change_password(self, current: str, new: str) -> bool:
        if not self._matches(current):
            return False
        self._password_file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._write(new)
            self._sessions.clear()
        return True

    def _write(self, password: str) -> None:
        tmp = self._password_file.with_name(self._password_file.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(hash_password(password) + "\n")
        os.replace(tmp, self._password_file)

    def login(self, username: str, password: str, client: str) -> str | None:
        """Returns a session token, or None for a wrong name or password."""
        now = time.monotonic()
        with self._lock:
            failures, locked_until = self._failures.get(client, (0, 0.0))
            if locked_until > now:
                raise LockedOut(int(locked_until - now) + 1)
        name_ok = hmac.compare_digest(username.encode(), USERNAME.encode())
        if not (self._matches(password) and name_ok):
            with self._lock:
                failures += 1
                until = now + _LOCKOUT_SECONDS if failures >= _MAX_FAILURES else 0.0
                if len(self._failures) > 1000:
                    self._failures.clear()
                self._failures[client] = (0 if until else failures, until)
            return None
        with self._lock:
            self._failures.pop(client, None)
        return self.new_session()

    def new_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            now = time.time()
            self._sessions = {t: exp for t, exp in self._sessions.items() if exp > now}
            self._sessions[token] = now + SESSION_SECONDS
        return token

    def logout(self, token: str | None) -> None:
        with self._lock:
            self._sessions.pop(token or "", None)

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            expires = self._sessions.get(token)
            if expires is None or expires <= time.time():
                self._sessions.pop(token, None)
                return False
            return True


def set_session_cookie(response, token: str, *, secure: bool) -> None:
    # `secure` only for a login made over HTTPS: the device also serves plain
    # HTTP, and a secure cookie would never be sent back there.
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite="strict",
        path="/", secure=secure,
    )


class Guard:
    """ASGI middleware in front of everything under /api/."""

    def __init__(self, app, authenticator: Authenticator):
        self.app = app
        self.authenticator = authenticator

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        denied = self._check(request)
        if denied is not None:
            await denied(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _check(self, request: Request) -> JSONResponse | None:
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"detail": "Missing X-Midwire header"}, status_code=403)
        if request.url.path in OPEN_PATHS:
            return None
        if not self.authenticator.valid(request.cookies.get(SESSION_COOKIE)):
            return JSONResponse({"detail": "login_required"}, status_code=401)
        return None
