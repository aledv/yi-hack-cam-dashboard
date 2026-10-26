import asyncio
import json
import logging
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()  # allow running locally without --env-file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("camera-app")

# httpx logs every single outbound HTTP request at INFO level (camera
# status polls, notifier calls, etc.) -- useful while debugging, just
# noise day-to-day. Our own logger.info/warning calls stay untouched.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

import auth
import cameras
import config
import events
import i18n
import mqtt_listener
import notifier
import recordings
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["t"] = i18n.t
templates.env.globals["i18n"] = i18n
t = i18n.t

LANG_COOKIE = "lang"


@app.middleware("http")
async def language(request: Request, call_next):
    """Language of this request: the browser's choice (cookie) or the LANGUAGE default."""
    i18n.set_language(request.cookies.get(LANG_COOKIE))
    return await call_next(request)


# asyncio only holds a weak reference to tasks created with create_task --
# without keeping our own reference here, the scan task can get garbage
# collected mid-run and silently stop indexing.
_background_tasks: set[asyncio.Task] = set()


def _spawn_full_scan(cams: list[dict]):
    task = asyncio.create_task(asyncio.to_thread(recordings.full_scan, cams))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


@app.on_event("startup")
async def startup():
    events.set_loop(asyncio.get_running_loop())
    recordings.init_db()
    config.start_config_watcher()
    cams = config.get_cameras()
    recordings.start_recordings_watcher(cams)
    mqtt_listener.start_mqtt_listener()
    _spawn_full_scan(cams)

    # Connectivity check, logged so it's visible via `docker logs camera-app`.
    # MQTT's own connect/disconnect callbacks log their outcome separately
    # (the handshake happens asynchronously on the listener thread, so we
    # can't synchronously confirm it here) -- this just double-checks
    # shortly after startup and logs the notifier reachability directly.
    async def _log_connectivity():
        await asyncio.sleep(2)
        logger.info(f"Notification channels: {', '.join(notifier.enabled_channels()) or 'none'}")
        if mqtt_listener.MQTT_HOST:
            logger.info(f"MQTT connected: {'yes' if mqtt_listener.is_connected() else 'NO (see the log above)'}")

    task = asyncio.create_task(_log_connectivity())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _grid_cols(n: int) -> int:
    """1 camera -> 1 col (fullscreen), otherwise roughly a square grid."""
    if n <= 1:
        return 1
    return math.ceil(math.sqrt(n))


# ---------- language ----------


@app.get("/lang/{code}")
def set_language(request: Request, code: str):
    """EN/IT switch in the top bar: remembers the choice in a cookie and goes back."""
    back = request.headers.get("referer", "/")
    path = urlsplit(back)
    # only local pages, never an external URL
    target = (path.path or "/") + (f"?{path.query}" if path.query else "")
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    resp = RedirectResponse(target, status_code=303)
    if code in i18n.LANGUAGES:
        resp.set_cookie(LANG_COOKIE, code, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


# ---------- auth ----------


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if auth.is_logged_in(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if auth.verify_credentials(username, password):
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            auth.SESSION_COOKIE,
            auth.create_session_cookie(),
            max_age=auth.SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return resp
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": t("invalid_credentials")}, status_code=401
    )


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


@app.get("/events")
async def sse_events(request: Request):
    redirect = auth.require_login(request)
    if redirect:
        return redirect

    q = events.subscribe()

    async def gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            events.unsubscribe(q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            # Nginx (and proxies built on it, often in front of this app in HTTPS
            # deployments) buffers proxied responses by default, which
            # defeats a long-lived SSE stream: events sit in nginx's
            # buffer instead of reaching the browser as they happen.
            # This header tells nginx to disable buffering for this
            # response specifically, without needing any reverse-proxy
            # config changes.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


# ---------- pages ----------


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    cams = config.get_cameras()
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "cameras": cams,
            "cols": _grid_cols(len(cams)),
            "mediamtx_base": os.environ.get("MEDIAMTX_PUBLIC_BASE", "").rstrip("/"),
        },
    )


@app.get("/recordings", response_class=HTMLResponse)
def recordings_page(request: Request, camera: str | None = None, page: int = 1, period: str = "recent"):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    result = recordings.list_recordings_page(camera, page=page, only_recent=(period != "all"))
    return templates.TemplateResponse(
        "recordings.html",
        {
            "request": request,
            "recordings": result["items"],
            "cameras": config.get_cameras(),
            "selected_camera": camera,
            "page": result["page"],
            "total_pages": result["total_pages"],
            "period": period,
        },
    )


@app.get("/recordings/list", response_class=HTMLResponse)
def recordings_list_partial(request: Request, camera: str | None = None, page: int = 1, period: str = "recent"):
    """Same data as /recordings but just the grid+pagination fragment --
    polled every 20s by HTMX from page 1 so new recordings (triggered by
    an MQTT motion event) show up without a manual refresh."""
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    result = recordings.list_recordings_page(camera, page=page, only_recent=(period != "all"))
    return templates.TemplateResponse(
        "_recordings_list.html",
        {
            "request": request,
            "recordings": result["items"],
            "selected_camera": camera,
            "page": result["page"],
            "total_pages": result["total_pages"],
            "period": period,
        },
    )


@app.get("/cameras", response_class=HTMLResponse)
def cameras_page(request: Request):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    cams = config.get_cameras()
    settings_map = {cam["name"]: recordings.get_camera_settings(cam["name"]) for cam in cams}
    return templates.TemplateResponse(
        "cameras.html",
        {
            "request": request,
            "cameras": cams,
            "settings_map": settings_map,
            "channels": [(c, notifier.CHANNEL_LABELS[c]) for c in notifier.enabled_channels()],
        },
    )


@app.get("/api/system/status", response_class=HTMLResponse)
async def system_status(request: Request):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        "_system_status.html",
        {
            "request": request,
            "channels": [notifier.CHANNEL_LABELS[c] for c in notifier.enabled_channels()],
            "mqtt_enabled": bool(mqtt_listener.MQTT_HOST),
            "mqtt_ok": mqtt_listener.is_connected(),
        },
    )


@app.post("/api/notify/test", response_class=HTMLResponse)
async def test_notify(request: Request, channel: str = Form(...)):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    label = notifier.CHANNEL_LABELS.get(channel, "?")
    ok = await notifier.send_async(channel, t("notify_test"))
    css_class = "ok" if ok else "error"
    text = t("sent_via", channel=label) if ok else t("send_error", channel=label)
    return HTMLResponse(f'<span class="test-feedback {css_class}">{text}</span>')


# ---------- recording file/thumbnail serving ----------
# Only paths present in the recordings index are served, so a crafted
# ?path= can't be used to read arbitrary files on the container.


def _lookup_recording(path: str) -> dict | None:
    for rec in recordings.list_recordings():
        if rec["path"] == path:
            return rec
    return None


@app.get("/recordings/file")
def recording_file(request: Request, path: str):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    rec = _lookup_recording(path)
    if not rec:
        return HTMLResponse(t("not_found"), status_code=404)
    return FileResponse(rec["path"], media_type="video/mp4")


@app.get("/recordings/view", response_class=HTMLResponse)
def recording_view(request: Request, path: str, back: str = "/recordings"):
    """Video player page with prev/next arrows to the older/newer recording
    of the same camera, so on the phone you don't have to go back to the
    grid after each clip."""
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    nb = recordings.neighbors(path)
    if not nb:
        return HTMLResponse(t("not_found"), status_code=404)
    # only local pages, never an external URL
    if not (back == "/" or back.startswith("/recordings")) or back.startswith("//"):
        back = "/recordings"
    return templates.TemplateResponse(
        "recording_view.html",
        {"request": request, "rec": nb["rec"], "prev": nb["prev"], "next": nb["next"], "back": back},
    )


@app.get("/recordings/thumb")
def recording_thumb(request: Request, path: str):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    rec = _lookup_recording(path)
    if not rec:
        return HTMLResponse(t("not_found"), status_code=404)
    thumb = rec["thumbnail"]
    # The DB can point at a thumbnail file that's since been deleted (e.g.
    # data/ wiped/restored without the DB) -- regenerate rather than
    # handing a stale path to FileResponse, which raises an unhandled
    # 500 if the file doesn't actually exist on disk.
    if not thumb or not Path(thumb).exists():
        thumb = recordings.ensure_thumbnail(rec["path"])
    if not thumb:
        return HTMLResponse(t("not_found"), status_code=404)
    return FileResponse(thumb, media_type="image/jpeg")


@app.get("/recordings/download")
def recording_download(request: Request, path: str):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    rec = _lookup_recording(path)
    if not rec:
        return HTMLResponse(t("not_found"), status_code=404)
    return FileResponse(rec["path"], media_type="video/mp4", filename=Path(rec["path"]).name)


@app.post("/api/rescan")
async def rescan(request: Request):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    _spawn_full_scan(config.get_cameras())
    return {"status": "scan started"}


@app.post("/api/cameras/{name}/test-motion", response_class=HTMLResponse)
async def test_motion(request: Request, name: str):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    cam = config.get_camera(name)
    if not cam:
        return HTMLResponse(t("camera_not_found"), status_code=404)
    ok = mqtt_listener.publish_test_event(cam)
    css_class = "ok" if ok else "error"
    text = t("event_published") if ok else t("mqtt_missing")
    return HTMLResponse(f'<span class="test-feedback {css_class}">{text}</span>')


# ---------- actions (HTMX) ----------


async def _camera_state(cam: dict) -> tuple[bool | None, dict | None]:
    """ON/OFF switch and status.json of a camera, queried in parallel."""

    async def none():
        return None

    info_url = cameras.info_url_for(cam)
    return await asyncio.gather(
        cameras.camera_status(cam["status_url"]) if cam.get("status_url") else none(),
        cameras.camera_info(info_url) if info_url else none(),
    )


@app.get("/api/cameras/{name}/status", response_class=HTMLResponse)
async def camera_status(request: Request, name: str):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    cam = config.get_camera(name)
    if not cam:
        return HTMLResponse(t("camera_not_found"), status_code=404)
    is_on, info = await _camera_state(cam)
    return templates.TemplateResponse(
        "_camera_toggle.html",
        {
            "request": request,
            "camera": cam,
            "is_on": is_on,
            "info": info,
            "online": is_on is not None or info is not None,
            "show_info": True,
        },
    )


@app.get("/api/motion")
def motion_today(request: Request, since: float):
    """Motion events since `since` (the browser's local midnight, epoch seconds)
    per camera, for the counters on the Live page."""
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    return recordings.motion_events_since(since)


@app.get("/api/cameras/{name}/power-status")
async def camera_power_status(request: Request, name: str):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    cam = config.get_camera(name)
    if not cam:
        return HTMLResponse(t("camera_not_found"), status_code=404)
    is_on = await cameras.camera_status(cam["status_url"]) if cam.get("status_url") else None
    # online: False only when the camera has a status endpoint and it didn't answer
    return {"is_on": is_on, "online": is_on is not None or not cam.get("status_url")}


@app.post("/api/cameras/{name}/notify-prefs")
async def update_notify_prefs(
    request: Request,
    name: str,
    notify: str | None = Form(None),
):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    # Unchecked checkboxes aren't sent at all by the browser, so presence
    # of the field (any value) means "checked".
    recordings.set_camera_settings(name, notify=notify is not None)
    return HTMLResponse(status_code=204)


@app.post("/api/cameras/{name}/toggle", response_class=HTMLResponse)
async def toggle_camera(request: Request, name: str, state: str = Form(...)):
    redirect = auth.require_login(request)
    if redirect:
        return redirect
    cam = config.get_camera(name)
    if not cam:
        return HTMLResponse(t("camera_not_found"), status_code=404)

    url = cam["on_url"] if state == "on" else cam["off_url"]
    ok = await cameras.camera_power(url)

    if ok and recordings.get_camera_settings(name)["notify"] and notifier.enabled_channels():
        await notifier.notify(t("notify_power", camera=name, state=state.upper()))

    return templates.TemplateResponse(
        "_camera_toggle.html",
        {
            "request": request,
            "camera": cam,
            "is_on": (state == "on") if ok else None,
        },
    )
