"""Local API; all mutations reject cross-origin browser requests."""
import asyncio
import base64
from contextlib import asynccontextmanager
import importlib.util
import json
import os
import shutil
import sys
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from backend.config import DOWNLOAD_DIR, DIST_DIR, SCAN_TIMEOUT, MAX_JOBS
from backend.jobs import JobManager, TERMINAL, create_worker, stop_process
from backend.models import ScanRequest, DownloadRequest, BrowserCommand
from backend.browser_sessions import BrowserSessions
from backend.browser_policy import KEYS
from backend.security import parse_url, safe_file, UnsafeURL

manager = JobManager()
browsers = BrowserSessions()
thumbnail_slots = asyncio.Semaphore(3)
thumbnail_targets: dict[str, str] = {}
update_lock = asyncio.Lock()
scan_lock = asyncio.Lock()
active_scans = 0


@asynccontextmanager
async def lifespan(app):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield
    await browsers.shutdown()
    await manager.close()


app = FastAPI(title="Universal Video Downloader", lifespan=lifespan, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])


@app.middleware("http")
async def local_browser_guard(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != str(request.base_url).rstrip("/")):
            return JSONResponse({"detail": "Cross-origin requests are blocked."}, status_code=403)
        if not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"detail": "Use application/json."}, status_code=415)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    if request.url.path.startswith("/docs"):
        # FastAPI's standard Swagger UI uses CDN assets and one bootstrap script.
        # Keep this exception limited to documentation, away from the app surface.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "img-src 'self' data: https://fastapi.tiangolo.com; "
            "frame-ancestors 'none'; base-uri 'none'")
    return response


@app.get("/api/health")
def health():
    from importlib.metadata import version
    return {"ffmpeg": bool(shutil.which("ffmpeg")), "playwright": importlib.util.find_spec("playwright") is not None,
            "ytdlp_version": version("yt-dlp"), "max_concurrent_jobs": MAX_JOBS}


@app.post("/api/scan")
async def scan(request: ScanRequest):
    global active_scans
    try: parse_url(request.url)
    except UnsafeURL as exc: raise HTTPException(400, str(exc))
    async with scan_lock:
        if active_scans >= 2: raise HTTPException(429, "Two scans are already running. Please wait.")
        if update_lock.locked(): raise HTTPException(409, "Engine update in progress. Try again shortly.")
        active_scans += 1
    process = None
    try:
        process = await create_worker({"action": "scan", "url": request.url})
        output, _ = await asyncio.wait_for(process.communicate(), SCAN_TIMEOUT)
        result = json.loads(output.decode().splitlines()[-1])
        if result.get("error"): raise HTTPException(422, result["error"])
        for item in result.get("items", []):
            if item.get("thumbnail"):
                thumbnail_targets[item["id"]] = item["thumbnail"]
                if len(thumbnail_targets) > 200:
                    thumbnail_targets.pop(next(iter(thumbnail_targets)))
        return result
    except asyncio.TimeoutError: raise HTTPException(504, "Scan timed out after 65 seconds. Try a direct video page.")
    except (ValueError, IndexError): raise HTTPException(502, "The scan worker returned no usable results.")
    finally:
        if process is not None: await stop_process(process)
        active_scans -= 1


@app.post("/api/download")
async def download(request: DownloadRequest):
    try:
        parse_url(request.url)
        if update_lock.locked(): raise HTTPException(409, "Engine update in progress.")
        if request.format_id != "best" and not all(c.isalnum() or c in "_.-" for c in request.format_id):
            raise ValueError("Invalid quality selection.")
        browser = os.getenv("UVD_COOKIE_BROWSER")
        if browser and browser not in {"firefox", "chrome", "chromium", "edge", "brave", "opera", "vivaldi", "safari"}:
            raise ValueError("Unsupported UVD_COOKIE_BROWSER setting.")
        browser_auth = None
        if request.browser_session_id:
            try: browser_auth = browsers.get(request.browser_session_id).download_auth(request.url)
            except KeyError as exc: raise ValueError(str(exc))
        return {"job_id": manager.add(request, browser, browser_auth).id}
    except ValueError as exc: raise HTTPException(400, str(exc))


@app.get("/api/jobs")
async def jobs():
    return {"jobs": [j.model_dump() for j in reversed(list(manager.jobs.values()))]}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str):
    if job_id not in manager.jobs: raise HTTPException(404, "Job not found.")
    await manager.cancel(job_id)
    return manager.jobs[job_id]


@app.get("/api/jobs/{job_id}/events")
async def events(job_id: str, request: Request):
    if job_id not in manager.jobs: raise HTTPException(404, "Job not found.")
    async def stream():
        queue = asyncio.Queue(maxsize=12)
        manager.listeners.setdefault(job_id, set()).add(queue)
        try:
            event = manager.jobs[job_id].model_dump()
            while True:
                yield "data: " + json.dumps(event) + "\n\n"
                if event["status"] in TERMINAL or await request.is_disconnected(): break
                try: event = await asyncio.wait_for(queue.get(), 15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
        finally:
            manager.listeners[job_id].discard(queue)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/files/{filename}")
async def file(filename: str):
    try: path = safe_file(DOWNLOAD_DIR, filename)
    except ValueError: raise HTTPException(400, "Invalid filename.")
    if not path.is_file() or path.suffix.lower() not in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}:
        raise HTTPException(404, "File not found.")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@app.post("/api/update-engine")
async def update_engine():
    if update_lock.locked(): raise HTTPException(409, "An update is already running.")
    async with update_lock:
        if active_scans or browsers.active() or any(j.status not in TERMINAL for j in manager.jobs.values()):
            raise HTTPException(409, "Close the browser viewer and wait for scans and downloads to finish before updating.")
        process = None
        try:
            process = await asyncio.create_subprocess_exec(sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=os.name != "nt")
            await asyncio.wait_for(process.wait(), 120)
            if process.returncode: raise HTTPException(502, "Engine update failed. Run python -m pip install -U yt-dlp in your virtual environment.")
            return {"ytdlp_version": health()["ytdlp_version"]}
        except asyncio.TimeoutError: raise HTTPException(504, "Engine update timed out. Try updating from your terminal.")
        finally:
            if process is not None: await stop_process(process)


@app.post("/api/browser/sessions")
async def open_browser(request: ScanRequest):
    if update_lock.locked(): raise HTTPException(409, "Engine update in progress.")
    try:
        parse_url(request.url)
        session = await browsers.start(request.url)
        return session.public()
    except ValueError as exc: raise HTTPException(400, str(exc))


def browser_session(session_id: str):
    try: return browsers.get(session_id)
    except KeyError: raise HTTPException(404, "Browser session expired. Open Advanced mode again.")


@app.get("/api/browser/sessions/{session_id}")
async def browser_state(session_id: str):
    return browser_session(session_id).public()


@app.get("/api/browser/sessions/{session_id}/frame")
async def browser_frame(session_id: str):
    session = browser_session(session_id)
    if session.frame is None: raise HTTPException(404, "The browser preview is not ready yet.")
    return Response(session.frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/browser/sessions/{session_id}/command")
async def browser_command(session_id: str, command: BrowserCommand):
    browser_session(session_id)
    try:
        if command.action == "navigate": parse_url(command.url)
        if command.action == "key" and command.key not in KEYS: raise ValueError("Unsupported browser key.")
        await browsers.command(session_id, command.model_dump())
        return {"ok": True}
    except (ValueError, OSError, asyncio.TimeoutError) as exc:
        raise HTTPException(400, str(exc) if isinstance(exc, ValueError) else "Browser action failed. Try again.")


@app.post("/api/browser/sessions/{session_id}/close")
async def close_browser(session_id: str):
    await browsers.close(session_id)
    return {"ok": True}


@app.get("/api/thumbnails/{item_id}")
async def thumbnail(item_id: str):
    target = thumbnail_targets.get(item_id)
    if not target: raise HTTPException(404, "Thumbnail not found.")
    process = None
    async with thumbnail_slots:
        try:
            process = await create_worker({"action": "thumbnail", "url": target})
            output, _ = await asyncio.wait_for(process.communicate(), 12)
            data = json.loads(output.decode().splitlines()[-1])
            if process.returncode or "data" not in data: raise ValueError()
            return Response(base64.b64decode(data["data"]), media_type=data["media_type"], headers={"Cache-Control": "private, max-age=3600"})
        except (ValueError, IndexError, asyncio.TimeoutError):
            raise HTTPException(404, "Thumbnail unavailable.")
        finally:
            if process is not None: await stop_process(process)


@app.get("/api/{path:path}", include_in_schema=False)
async def unknown_api(path: str):
    raise HTTPException(404, "API route not found.")

if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="frontend")
else:
    @app.get("/", include_in_schema=False)
    async def frontend_missing():
        return JSONResponse({"detail": "Frontend missing. Run python run.py to build it."}, status_code=503)
