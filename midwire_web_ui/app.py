"""The HTTP API and the static frontend."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__, netinfo, service, updates
from .auth import (
    DEFAULT_PASSWORD,
    MIN_PASSWORD_LENGTH,
    SESSION_COOKIE,
    USERNAME,
    Authenticator,
    Guard,
    LockedOut,
    set_session_cookie,
)
from .autostart import Autostarter
from .config import Settings
from .models import PreferencesUpdate, StartRequest
from .network import HotspotRequest, JoinRequest, Network
from .prefs import PreferenceStore, profile_key
from .usb import list_devices, list_udcs

STATIC_DIR = Path(__file__).parent / "static"

# Log lines are sent in batches: with a fast device usb-proxy prints
# thousands of lines a second, and one event per line would swamp a Pi.
_LOG_BATCH_LINES = 500
_LOG_BATCH_SECONDS = 0.1
_LOG_KEEPALIVE_SECONDS = 15
_LOG_BACKLOG_LINES = "300"

Password = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, Field(max_length=64)]
    password: Annotated[str, Field(max_length=128)]


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current: Annotated[str, Field(max_length=128)]
    new: Password


def create_app(settings: Settings | None = None, *, watch_devices: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    authenticator = Authenticator(settings.password_file)
    store = PreferenceStore(settings.prefs_file)
    autostarter = Autostarter(settings, store)
    network = Network(settings)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        watcher = asyncio.create_task(autostarter.run()) if watch_devices else None
        yield
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

    app = FastAPI(title="Midwire", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(Guard, authenticator=authenticator)
    app.state.autostarter = autostarter
    app.state.network = network
    api = APIRouter(prefix="/api")

    def bad_request(exc: service.RequestError) -> HTTPException:
        return HTTPException(status_code=400, detail=str(exc))

    # --- session: reachable without logging in --------------------------------

    @api.get("/session")
    def session(request: Request) -> dict:
        return {
            "authenticated": authenticator.valid(request.cookies.get(SESSION_COOKIE)),
            # Still admin / admin: the page offers to change it.
            "default_password": authenticator.uses_default_password,
            "username": USERNAME,
            "version": __version__,
        }

    @api.post("/login")
    def login(body: LoginRequest, request: Request, response: Response) -> dict:
        client = request.client.host if request.client else "unknown"
        try:
            token = authenticator.login(body.username, body.password, client)
        except LockedOut as exc:
            raise HTTPException(
                status_code=429, detail=f"Too many wrong passwords. Try again in {exc.seconds} seconds."
            ) from exc
        if token is None:
            raise HTTPException(status_code=401, detail="Wrong user name or password.")
        set_session_cookie(response, token, secure=request.url.scheme == "https")
        return {"ok": True}

    @api.post("/logout")
    def logout(request: Request, response: Response) -> dict:
        authenticator.logout(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/")
        return {"ok": True}

    @api.post("/password")
    def change_password(body: PasswordChange, request: Request, response: Response) -> dict:
        if body.new == DEFAULT_PASSWORD:
            raise HTTPException(status_code=400, detail="Choose something other than the default.")
        if not authenticator.change_password(body.current, body.new):
            raise HTTPException(status_code=400, detail="The current password is wrong.")
        # Changing it logs out every session, so give this browser a new one.
        set_session_cookie(response, authenticator.new_session(), secure=request.url.scheme == "https")
        return {"ok": True}

    # --- the proxy -----------------------------------------------------------

    @api.get("/state")
    def state(request: Request) -> dict:
        """Everything the main page shows, in one call. The page polls this."""
        # The interface this very request came in on. A device that provides
        # it cannot be proxied without cutting the page off.
        server = request.scope.get("server")
        return {
            "page_interface": netinfo.interface_for_address(server[0]) if server else None,
            "raw_gadget": settings.raw_gadget_dev.exists(),
            "udcs": [asdict(u) for u in list_udcs(settings)],
            "devices": [asdict(d) for d in list_devices(settings)],
            "injection_files": service.list_injection_files(settings),
            "status": service.status(settings),
            "captures": service.list_captures(settings),
            "preferences": store.load().model_dump(),
            "autostart": autostarter.last,
        }

    # --- software updates ----------------------------------------------------

    @api.get("/updates")
    def update_status() -> dict:
        return updates.status(settings)

    @api.post("/updates/check", status_code=202)
    def update_check() -> dict:
        try:
            updates.check(settings)
        except service.RequestError as exc:
            raise bad_request(exc) from exc
        return {"started": True}

    @api.post("/updates/install", status_code=202)
    def update_install() -> dict:
        try:
            updates.install(settings)
        except service.RequestError as exc:
            raise bad_request(exc) from exc
        return {"started": True}

    @api.get("/updates/log")
    async def update_log() -> StreamingResponse:
        """Server-sent events: what the updater prints, live."""
        return StreamingResponse(
            _follow_journal(settings, [settings.update_check_unit, settings.update_install_unit]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.post("/start")
    def start(request: StartRequest) -> dict:
        try:
            args, device = service.start(request, settings)
        except service.RequestError as exc:
            raise bad_request(exc) from exc
        # Remember what was used, for next time and for auto-start.
        store.remember(profile_key(device.vendor_id, device.product_id), request.options())
        return {"args": args, "status": service.status(settings)}

    @api.post("/stop")
    def stop() -> dict:
        autostarter.note_manual_stop()
        try:
            service.stop(settings)
        except service.RequestError as exc:
            raise bad_request(exc) from exc
        return {"status": service.status(settings)}

    @api.put("/preferences")
    def save_preferences(update: PreferencesUpdate) -> dict:
        if update.udc is not None and update.udc not in {u.name for u in list_udcs(settings)}:
            raise HTTPException(status_code=400, detail="That gadget controller was not found.")
        if (
            update.defaults.injection_file is not None
            and update.defaults.injection_file not in service.list_injection_files(settings)
        ):
            raise HTTPException(status_code=400, detail="That injection file was not found.")
        return store.update(update).model_dump()

    @api.delete("/profiles/{key}")
    def forget_profile(key: str) -> dict:
        return store.forget(key).model_dump()

    # --- captures ------------------------------------------------------------

    @api.get("/captures/{name}")
    def download_capture(name: str) -> FileResponse:
        try:
            path = service.capture_path(name, settings)
        except service.RequestError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path, media_type="application/vnd.tcpdump.pcap", filename=name)

    @api.delete("/captures/{name}")
    def delete_capture(name: str) -> dict:
        try:
            path = service.capture_path(name, settings)
        except service.RequestError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if service.status(settings).get("capture") == name:
            raise HTTPException(status_code=400, detail="That capture is being written. Stop the proxy first.")
        try:
            path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Could not delete: {exc.strerror}") from exc
        return {"captures": service.list_captures(settings)}

    # --- network -------------------------------------------------------------

    @api.get("/network")
    def network_status() -> dict:
        return network.status()

    @api.get("/network/scan")
    def network_scan() -> list[dict]:
        try:
            return network.scan()
        except service.RequestError as exc:
            raise bad_request(exc) from exc

    # These three answer at once and make the change a moment later, because
    # the change usually cuts the connection the request arrived on.

    @api.put("/network/hotspot", status_code=202)
    def network_hotspot(request: HotspotRequest) -> dict:
        try:
            network.set_hotspot(request)
        except service.RequestError as exc:
            raise bad_request(exc) from exc
        return {"switching": True}

    @api.put("/network/wifi", status_code=202)
    def network_join(request: JoinRequest) -> dict:
        try:
            network.join(request)
        except service.RequestError as exc:
            raise bad_request(exc) from exc
        return {"switching": True}

    @api.delete("/network/wifi", status_code=202)
    def network_use_hotspot() -> dict:
        try:
            network.use_hotspot()
        except service.RequestError as exc:
            raise bad_request(exc) from exc
        return {"switching": True}

    # --- logs ----------------------------------------------------------------

    @api.get("/logs")
    async def logs() -> StreamingResponse:
        """Server-sent events. Each event is a JSON array of journal lines."""
        return StreamingResponse(
            _follow_journal(settings, [settings.unit]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(api)
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


async def _follow_journal(settings: Settings, units: list[str]):
    unit_args = [arg for unit in units for arg in ("-u", unit)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *settings.journalctl,
            *unit_args, "-f", "-n", _LOG_BACKLOG_LINES, "-o", "short-iso", "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        yield f"event: fail\ndata: {json.dumps(f'Could not run journalctl: {exc.strerror}')}\n\n"
        return
    loop = asyncio.get_running_loop()
    try:
        while True:
            try:
                first = await asyncio.wait_for(proc.stdout.readline(), _LOG_KEEPALIVE_SECONDS)
            except asyncio.TimeoutError:
                # A comment line. Writing it is also how a closed connection
                # is noticed while the journal is quiet.
                yield ": keepalive\n\n"
                continue
            if not first:
                break
            batch = [first]
            deadline = loop.time() + _LOG_BATCH_SECONDS
            while len(batch) < _LOG_BATCH_LINES:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), remaining)
                except asyncio.TimeoutError:
                    break
                if not line:
                    break
                batch.append(line)
            lines = [raw.decode(errors="replace").rstrip("\n") for raw in batch]
            yield f"data: {json.dumps(lines)}\n\n"
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 2)
            except asyncio.TimeoutError:
                proc.kill()
