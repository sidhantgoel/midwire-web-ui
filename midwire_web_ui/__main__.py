"""Command line: `midwire-web-ui serve` and `midwire-web-ui set-password`."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys

from .auth import USERNAME, hash_password
from .config import Settings


def serve(settings: Settings) -> int:
    import uvicorn

    from .app import create_app
    from .tls import CertificateError, ensure_certificate

    # uvicorn sets up only its own loggers. Send ours (auto-start decisions,
    # network changes) to the journal as well.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")

    app = create_app(settings)
    configs = [uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info")]
    if settings.tls_port:
        try:
            ensure_certificate(settings.tls_cert, settings.tls_key)
        except CertificateError as exc:
            # HTTP alone is better than no page at all.
            print(f"HTTPS is off: {exc}", file=sys.stderr)
        else:
            configs.append(
                uvicorn.Config(
                    app, host=settings.host, port=settings.tls_port, log_level="info",
                    ssl_certfile=str(settings.tls_cert), ssl_keyfile=str(settings.tls_key),
                    # Both listeners share one app. Its startup work (the
                    # device watcher) must run once, so only the first runs it.
                    lifespan="off",
                )
            )

    async def run() -> None:
        await asyncio.gather(*(uvicorn.Server(config).serve() for config in configs))

    asyncio.run(run())
    return 0


def set_password(settings: Settings) -> int:
    """Recovery for a forgotten password. Normally it is changed in the page."""
    if sys.stdin.isatty():
        password = getpass.getpass(f"New password for '{USERNAME}': ")
        if password != getpass.getpass("Repeat: "):
            print("The passwords do not match.", file=sys.stderr)
            return 1
    else:
        # Non-interactive: one line on stdin.
        password = sys.stdin.readline().rstrip("\n")
    path = settings.password_file
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(hash_password(password) + "\n")
    # Run with sudo, this would leave a root-owned file the service cannot
    # read. Hand it to whoever owns the state directory (the service user).
    owner = path.parent.stat()
    if hasattr(os, "chown") and os.geteuid() == 0:
        os.chown(path, owner.st_uid, owner.st_gid)
    print(f"Password saved to {path}. Restart midwire-web-ui.service to log out existing sessions.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="midwire-web-ui", description="Midwire web UI")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="run the web server (default)")
    commands.add_parser("set-password", help=f"reset the password for '{USERNAME}'")
    args = parser.parse_args()

    settings = Settings.from_env()
    if args.command == "set-password":
        return set_password(settings)
    return serve(settings)


if __name__ == "__main__":
    sys.exit(main())
