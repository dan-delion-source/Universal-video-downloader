"""One live interactive browser, plus short-lived closed-session download handoffs."""
import asyncio
import base64
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
import importlib.util
import json
import os
import sys
import time
import uuid
from backend.config import ROOT
from backend.jobs import stop_process
from backend.models import MediaItem

IDLE_SECONDS = 15 * 60
MAX_SECONDS = 30 * 60
PUBLIC_FIELDS = {"status", "url", "tabs", "popups", "active_tab", "error", "navigations"}


@dataclass
class BrowserSession:
    id: str
    created: float = field(default_factory=time.monotonic)
    touched: float = field(default_factory=time.monotonic)
    process: object = None
    task: object = None
    state: dict = field(default_factory=lambda: {"status": "starting", "items": [], "tabs": [], "popups": []})
    frame: bytes | None = None
    version: int = 0
    auth: dict = field(default_factory=dict, repr=False)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def accept(self, event: dict):
        for key in PUBLIC_FIELDS:
            if key in event: self.state[key] = event[key]
        if "items" in event:
            self.state["items"] = [MediaItem.model_validate(item).model_dump() for item in event["items"][:40]]
        if "auth" in event: self.auth = event["auth"]
        if event.get("frame"):
            self.frame = base64.b64decode(event["frame"], validate=True)
            self.version += 1

    def public(self):
        return {**deepcopy(self.state), "session_id": self.id, "frame_version": self.version, "has_frame": self.frame is not None}

    def download_auth(self, target: str):
        item = next((item for item in self.state["items"] if item["download_target"] == target), None)
        if item is None: raise ValueError("This video was not detected in that browser session.")
        if item["drm"]: raise ValueError("Protected streams cannot be downloaded.")
        auth = deepcopy(self.auth)
        auth["referer"] = auth.get("referrers", {}).get(target, self.state.get("url", ""))
        auth.pop("referrers", None)
        return auth


class BrowserSessions:
    def __init__(self):
        self.sessions: dict[str, BrowserSession] = {}
        self.lock = asyncio.Lock()

    def get(self, session_id: str):
        session = self.sessions.get(session_id)
        if session is None or time.monotonic() - session.touched > IDLE_SECONDS:
            if session is not None: session.auth.clear()
            raise KeyError("Browser session expired. Open Advanced mode again.")
        session.touched = time.monotonic()
        return session

    def active(self):
        return any(s.state["status"] in {"starting", "ready"} for s in self.sessions.values())

    async def start(self, url: str):
        if importlib.util.find_spec("playwright") is None:
            raise ValueError("Advanced mode needs the browser extra. Run python -m pip install -e '.[browser]' and python -m playwright install chromium, then restart the app.")
        async with self.lock:
            # Keep four recent snapshots for downloads after closing the viewer.
            if self.active(): raise ValueError("A browser session is already open. Close it before opening another.")
            while len(self.sessions) >= 4:
                oldest = next(iter(self.sessions))
                await self.close(oldest)
                self.sessions.pop(oldest, None)
            session = BrowserSession(id=uuid.uuid4().hex)
            self.sessions[session.id] = session
            try:
                session.process = await asyncio.create_subprocess_exec(sys.executable, "-m", "backend.browser_worker", cwd=ROOT,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=os.name != "nt", limit=4 * 1024 * 1024)
                session.process.stdin.write((json.dumps({"url": url}) + "\n").encode())
                await session.process.stdin.drain()
                session.task = asyncio.create_task(self.consume(session))
            except BaseException:
                if session.process is not None: await stop_process(session.process)
                self.sessions.pop(session.id, None)
                raise
            return session

    async def consume(self, session):
        try:
            while True:
                # A process which stops emitting frames is still bounded.
                line = await asyncio.wait_for(session.process.stdout.readline(), 35)
                if not line: break
                if time.monotonic() - session.touched > IDLE_SECONDS or time.monotonic() - session.created > MAX_SECONDS:
                    session.state.update(status="closed", error="Browser session expired. Open Advanced mode again.")
                    if time.monotonic() - session.touched > IDLE_SECONDS: session.auth.clear()
                    break
                session.accept(json.loads(line))
                if session.state["status"] == "error": break
            if session.state["status"] not in {"closed", "error"}:
                session.state.update(status="error", error="The browser session ended. Close the viewer and open it again.")
        except asyncio.CancelledError:
            raise
        except Exception:
            session.state.update(status="error", error="The browser stopped responding. Close the viewer and open it again.")
        finally:
            await stop_process(session.process)

    async def command(self, session_id: str, command: dict):
        session = self.get(session_id)
        if session.state["status"] not in {"starting", "ready"} or session.process.returncode is not None:
            raise ValueError("This browser session has ended. Open Advanced mode again.")
        # Avoid growing stdin buffers if a page takes a long time to respond.
        if session.lock.locked(): raise ValueError("A browser action is in progress. Try again in a moment.")
        async with session.lock:
            session.process.stdin.write((json.dumps(command) + "\n").encode())
            await asyncio.wait_for(session.process.stdin.drain(), 2)

    async def close(self, session_id: str):
        session = self.sessions.get(session_id)
        if session is None: return
        session.state["status"] = "closed"
        if session.task and not session.task.done():
            session.task.cancel()
            with suppress(asyncio.CancelledError): await session.task
        elif session.process is not None:
            await stop_process(session.process)
        session.process = None
        session.task = None
        session.frame = None
        session.state["has_frame"] = False

    async def shutdown(self):
        for session_id in list(self.sessions): await self.close(session_id)
        self.sessions.clear()
