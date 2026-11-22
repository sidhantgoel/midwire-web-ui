from __future__ import annotations

import shutil
import socket
import subprocess

import pytest
from conftest import LOGIN, WRITE
from fastapi.testclient import TestClient

from midwire_web_ui import tls
from midwire_web_ui.tls import ensure_certificate

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl command")


def describe(cert) -> str:
    return subprocess.run(
        ["openssl", "x509", "-noout", "-text", "-in", str(cert)], capture_output=True, text=True, check=True
    ).stdout


@needs_openssl
def test_creates_a_self_signed_certificate(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "midwire")
    cert, key = tmp_path / "tls" / "cert.pem", tmp_path / "tls" / "key.pem"
    ensure_certificate(cert, key)

    assert key.stat().st_mode & 0o077 == 0
    text = describe(cert)
    assert "DNS:midwire.local" in text and "DNS:midwire," in text
    assert "IP Address:10.42.0.1" in text and "IP Address:10.42.1.1" in text
    assert "CA:FALSE" in text
    # The key belongs to the certificate.
    pub_from_cert = subprocess.run(["openssl", "x509", "-noout", "-pubkey", "-in", str(cert)],
                                   capture_output=True, check=True).stdout
    pub_from_key = subprocess.run(["openssl", "pkey", "-pubout", "-in", str(key)],
                                  capture_output=True, check=True).stdout
    assert pub_from_cert == pub_from_key


@needs_openssl
def test_an_odd_hostname_falls_back_to_midwire(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "bad name;rm -rf")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    ensure_certificate(cert, key)
    assert "DNS:midwire.local" in describe(cert)


@needs_openssl
def test_a_valid_certificate_is_kept(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    ensure_certificate(cert, key)
    before = cert.read_bytes(), key.read_bytes()
    ensure_certificate(cert, key)
    assert (cert.read_bytes(), key.read_bytes()) == before


@needs_openssl
def test_a_certificate_about_to_expire_is_renewed(tmp_path, monkeypatch):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    monkeypatch.setattr(tls, "_VALID_DAYS", 1)
    ensure_certificate(cert, key)
    before = cert.read_bytes()
    monkeypatch.setattr(tls, "_VALID_DAYS", 825)
    ensure_certificate(cert, key)
    assert cert.read_bytes() != before
    assert "Not After" in describe(cert)


def test_the_owners_own_certificate_is_never_replaced(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert.write_text("my certificate")
    key.write_text("my key")
    ensure_certificate(cert, key)
    assert cert.read_text() == "my certificate" and key.read_text() == "my key"


def test_session_cookie_is_secure_only_over_https(env):
    over_http = TestClient(env.app()).post("/api/login", json=LOGIN, headers=WRITE)
    assert "secure" not in over_http.headers["set-cookie"].lower()

    https = TestClient(env.app(), base_url="https://midwire.local")
    over_https = https.post("/api/login", json=LOGIN, headers=WRITE)
    assert "secure" in over_https.headers["set-cookie"].lower()
    assert https.get("/api/state").status_code == 200
