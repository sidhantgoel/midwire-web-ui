"""The HTTPS certificate.

The device has no public name, so no certificate authority will vouch for
it. On first start the service makes a self-signed certificate of its own,
which browsers accept after a one-time warning. To use a real certificate
instead, put it and its key at the configured paths; a certificate this
module did not create is never replaced.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Browsers refuse server certificates valid for longer than this.
_VALID_DAYS = 825
_RENEW_WHEN_SECONDS_LEFT = 30 * 24 * 3600
# The image's fixed addresses: hotspot, and Ethernet straight to a computer.
_FIXED_ADDRESSES = ("10.42.0.1", "10.42.1.1", "127.0.0.1")


class CertificateError(Exception):
    pass


def _marker(cert: Path) -> Path:
    """Exists next to a certificate this module generated."""
    return cert.with_name(cert.name + ".self-signed")


def _hostname() -> str:
    name = socket.gethostname().split(".")[0]
    return name if re.fullmatch(r"[A-Za-z0-9-]{1,63}", name) else "midwire"


def _expiring(cert: Path) -> bool:
    result = subprocess.run(
        ["openssl", "x509", "-checkend", str(_RENEW_WHEN_SECONDS_LEFT), "-noout", "-in", str(cert)],
        capture_output=True,
    )
    return result.returncode != 0


def ensure_certificate(cert: Path, key: Path) -> None:
    """Makes sure a certificate and key exist, creating or renewing a
    self-signed pair when needed."""
    have_both = cert.is_file() and key.is_file()
    if have_both and not _marker(cert).exists():
        return  # the owner's own certificate
    if shutil.which("openssl") is None:
        if have_both:
            return
        raise CertificateError("openssl is not installed, so no HTTPS certificate can be created.")
    if have_both and not _expiring(cert):
        return

    host = _hostname()
    names = [f"DNS:{host}.local", f"DNS:{host}", "DNS:localhost"]
    names += [f"IP:{address}" for address in _FIXED_ADDRESSES]
    cert.parent.mkdir(parents=True, exist_ok=True)
    key.parent.mkdir(parents=True, exist_ok=True)
    # Create the key file private before openssl writes into it.
    os.close(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
    result = subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-nodes", "-keyout", str(key), "-out", str(cert), "-days", str(_VALID_DAYS),
            "-subj", f"/CN={host}.local",
            "-addext", "subjectAltName=" + ",".join(names),
            "-addext", "basicConstraints=critical,CA:FALSE",
            "-addext", "keyUsage=digitalSignature",
            "-addext", "extendedKeyUsage=serverAuth",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CertificateError(f"openssl could not create a certificate: {result.stderr.strip()}")
    os.chmod(key, 0o600)
    _marker(cert).touch()
    log.info("created a self-signed HTTPS certificate for %s.local at %s", host, cert)
