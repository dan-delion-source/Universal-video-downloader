"""Interactive Chromium in an isolated process, controlled via JSON lines.

Only screenshots and normalized metadata reach the web UI. Remote scripts never
execute in the local app's origin. All browser traffic uses the SSRF guard proxy.
"""
import asyncio
import base64
from contextlib import suppress
import hashlib
import html
import json
import os
from pathlib import Path
import sys
import uuid
from urllib.parse import urlsplit, urljoin
from backend.browser_policy import WIDTH, HEIGHT, KEYS, TabPolicy, NavigationPolicy, media_response
from backend.config import MAX_ITEMS, MAX_HTML_BYTES
from backend.models import MediaItem, MediaFormat
from backend.security import guarded_proxy, parse_url
from backend.extractors.static_extractor import protected_manifest

DRM_SCRIPT = """
window.__uvdProtected = false;
document.addEventListener('encrypted', () => { window.__uvdProtected = true; }, true);
if (navigator.requestMediaKeySystemAccess) {
  Object.defineProperty(navigator, 'requestMediaKeySystemAccess', { value: () => {
    window.__uvdProtected = true;
    return Promise.reject(new DOMException('Protected playback is unsupported', 'NotSupportedError'));
  }});
}
"""


def emit(event):
    print(json.dumps(event), flush=True)


class InteractiveBrowser:
    def __init__(self, context):
        self.context = context
        self.policy = TabPolicy()
        self.navigation = NavigationPolicy()
        self.navigation_requests = {}
        self.replays = {}
        self.popup_requests = {}
        self.pages = {}
        self.page_ids = {}
        self.items: dict[str, MediaItem] = {}
        self.referrers = {}
        self.protected_pages = set()
        self.documents = {}
        self.running = True
        self.error = None
        self.initial = True
        self.tasks = set()

    def background(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        def finished(t):
            self.tasks.discard(t)
            if not t.cancelled(): t.exception()  # Consume failures from closed/aborted pages.
        task.add_done_callback(finished)

    def register(self, page):
        if page in self.page_ids: return self.page_ids[page]
        tab_id = uuid.uuid4().hex
        try: self.policy.add(tab_id, initial=self.initial)
        except ValueError:
            self.background(page.close())
            return None
        self.initial = False
        self.pages[tab_id], self.page_ids[page] = page, tab_id
        page.on("dialog", lambda dialog: self.background(dialog.dismiss()))
        page.on("close", lambda: self.closed(tab_id, page))
        page.on("framenavigated", lambda frame: self.navigated(tab_id, page, frame))
        self.documents[tab_id] = 0
        return tab_id

    def navigated(self, tab_id, page, frame):
        if frame == page.main_frame:
            self.protected_pages.discard(tab_id)
            self.documents[tab_id] = self.documents.get(tab_id, 0) + 1

    def closed(self, tab_id, page):
        self.policy.remove(tab_id)
        self.navigation.remove_tab(tab_id)
        self.navigation_requests = {key: value for key, value in self.navigation_requests.items() if key in self.navigation.pending}
        self.replays.pop(tab_id, None)
        self.popup_requests.pop(tab_id, None)
        self.documents.pop(tab_id, None)
        self.protected_pages.discard(tab_id)
        self.pages.pop(tab_id, None)
        self.page_ids.pop(page, None)

    def proposed_navigation(self, source, payload):
        page = source.get("page")
        tab_id = self.page_ids.get(page)
        if not tab_id or self.policy.tabs[tab_id]["pending"]: return
        try:
            self.navigation.propose(tab_id, payload["url"],
                "popup" if payload.get("kind") == "popup" else "navigate")
        except (ValueError, KeyError, TypeError):
            pass

    @staticmethod
    def request_details(request):
        body = getattr(request, "post_data_buffer", None)
        if body is not None and len(body) > 1024 * 1024:
            raise ValueError("This form is too large for the browser viewer.")
        headers = getattr(request, "headers", {})
        return {"method": getattr(request, "method", "GET"), "body": body,
                "headers": {key: value for key, value in headers.items() if key.lower() in {"content-type", "origin", "referer"}}}

    def propose_request(self, tab_id, url, details):
        intent_id = self.navigation.propose(tab_id, url)
        if intent_id: self.navigation_requests.setdefault(intent_id, details)

    async def route(self, route):
        try:
            parse_url(route.request.url)
            page = route.request.frame.page
            tab_id = self.register(page)
            if not tab_id or self.policy.tabs[tab_id]["pending"]:
                # Native/form popups which bypass the JS guard stay hidden too.
                if tab_id and route.request.is_navigation_request():
                    self.policy.navigation(tab_id, route.request.url)
                    self.popup_requests.setdefault(tab_id, self.request_details(route.request))
                await route.fulfill(status=204, body="")
                return
            if route.request.is_navigation_request() and route.request.frame == page.main_frame:
                details = self.request_details(route.request)
                if not self.navigation.consume(tab_id, route.request.url):
                    self.propose_request(tab_id, route.request.url, details)
                    # 204 keeps the current document, including the active player.
                    await route.fulfill(status=204, body="")
                    return
                details = self.replays.pop(tab_id, None) or details
                self.policy.navigation(tab_id, route.request.url)
                # A direct media document is represented by a player instead of
                # buffering its entire file through the document-fetch API.
                if details["method"] == "GET" and media_response(route.request.url, ""):
                    await route.fulfill(status=200, content_type="text/html", body=
                        '<!doctype html><title>Video preview</title><video controls autoplay style="width:100%;height:90vh" src="'
                        + html.escape(route.request.url, quote=True) + '"></video>')
                    return
                kwargs = {"max_redirects": 0, "timeout": 15000}
                # Replaying a form preserves its private body and content type.
                # Browser cookies come from this fresh request, never a saved Cookie header.
                if details["method"] != getattr(route.request, "method", "GET") or details["body"] is not None:
                    kwargs["method"] = details["method"]
                    kwargs["post_data"] = details["body"]
                    kwargs["headers"] = {**getattr(route.request, "headers", {}), **details["headers"]}
                response = await route.fetch(**kwargs)
                try:
                    location = response.headers.get("location")
                    if response.status in {301, 302, 303, 307, 308} and location:
                        target = urljoin(route.request.url, location)
                        redirected = dict(details)
                        if response.status == 303 or (response.status in {301, 302} and details["method"] == "POST"):
                            redirected = {"method": "GET", "body": None, "headers": {}}
                        self.propose_request(tab_id, target, redirected)
                        await route.fulfill(status=204, body="")
                    else:
                        await route.fulfill(response=response)
                finally:
                    await response.dispose()
                return
            await route.continue_()
        except Exception:
            with suppress(Exception): await route.abort()

    def add_media(self, url, title, page_id, drm=False, referer=None):
        try: parse_url(url)
        except ValueError: return
        if url not in self.items and len(self.items) >= MAX_ITEMS: return
        existing = self.items.get(url)
        if existing:
            if referer: self.referrers[url] = referer
            if drm: existing.drm, existing.formats = True, []
            return
        ext = urlsplit(url).path.rsplit(".", 1)[-1].lower()
        self.items[url] = MediaItem(id=hashlib.sha256(url.encode()).hexdigest()[:16],
            title=(title or "Detected video")[:300], source="sniff", drm=drm,
            formats=[] if drm else [MediaFormat(format_id="best", ext=ext if ext in {"mp4", "webm", "mov", "m4v"} else "mp4")],
            download_target=url, page_url=self.policy.tabs.get(page_id, {}).get("url"))
        self.referrers[url] = referer or self.policy.tabs.get(page_id, {}).get("url", url)

    async def response(self, response):
        try:
            page_id = self.page_ids.get(response.request.frame.page)
            if not page_id or self.policy.tabs[page_id]["pending"]: return
            kind = response.headers.get("content-type", "").lower()
            if response.status not in {200, 206} or not media_response(response.url, kind): return
            tab = self.policy.tabs[page_id]
            drm = page_id in self.protected_pages
            self.add_media(response.url, tab["title"], page_id, drm, response.request.headers.get("referer"))
            # Inspect already-buffered, declared-small manifests without loading
            # arbitrary media bodies into Python memory. Download rechecks all manifests.
            size = int(response.headers.get("content-length", "0") or 0)
            is_manifest = "mpegurl" in kind or "dash+xml" in kind or urlsplit(response.url).path.endswith((".m3u8", ".mpd"))
            if is_manifest and 0 < size <= MAX_HTML_BYTES:
                body = await asyncio.wait_for(response.body(), 8)
                if len(body) <= MAX_HTML_BYTES and protected_manifest(body.decode("utf-8", errors="replace")):
                    self.items[response.url].drm, self.items[response.url].formats = True, []
        except Exception:
            pass

    async def navigate(self, page, url, replay=None):
        parse_url(url)
        tab_id = self.page_ids[page]
        self.navigation.grant(tab_id, url)
        if replay: self.replays[tab_id] = replay
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            self.error = None
        except Exception:
            self.error = "This page did not finish loading. You can still interact with the preview or try another URL."
        finally:
            self.navigation.revoke(tab_id)
            self.replays.pop(tab_id, None)

    async def resolve_navigation(self, intent_id, follow):
        intent = self.navigation.resolve(intent_id)
        replay = self.navigation_requests.pop(intent_id, None)
        if not follow: return
        page = self.pages.get(intent["source_tab"])
        if page is None: return
        if intent["kind"] == "popup":
            if len(self.policy.tabs) >= 5:
                raise ValueError("Close a tab before opening another.")
            page = await self.context.new_page()
            tab_id = self.register(page)
            self.policy.navigation(tab_id, intent["url"])
            self.policy.activate(tab_id)
        else:
            self.policy.activate(intent["source_tab"])
        await self.navigate(page, intent["url"], replay=replay)

    async def go_back(self, page):
        # Query Chromium's actual previous URL so Back authorizes exactly one
        # destination, without giving an ad script a temporary navigation bypass.
        cdp = await self.context.new_cdp_session(page)
        try:
            history = await cdp.send("Page.getNavigationHistory")
            index = history["currentIndex"]
            if index <= 0: return
            target = history["entries"][index - 1]["url"]
            parse_url(target)
            self.navigation.grant(self.page_ids[page], target)
            await page.go_back(wait_until="domcontentloaded", timeout=15000)
        finally:
            self.navigation.revoke(self.page_ids[page])
            await cdp.detach()

    async def commands(self):
        while self.running:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line: self.running = False; return
            try:
                cmd = json.loads(line)
                action = cmd["action"]
                self.error = None
                page = self.pages.get(self.policy.active)
                if action == "close": self.running = False; return
                if action in {"follow_navigation", "dismiss_navigation"}:
                    await self.resolve_navigation(cmd["navigation_id"], action == "follow_navigation")
                    continue
                if action in {"stay", "activate", "close_tab"}:
                    tab_id = cmd["tab_id"]
                    tab = self.policy.tabs[tab_id]
                    if action in {"stay", "close_tab"}:
                        if action == "stay" and not tab["pending"]: raise ValueError()
                        await self.pages[tab_id].close()
                    else:
                        was_pending, target = tab["pending"], tab["url"]
                        self.policy.activate(tab_id)
                        if was_pending:
                            replay = self.popup_requests.pop(tab_id, None)
                            if replay: await self.navigate(self.pages[tab_id], target, replay=replay)
                            else: await self.navigate(self.pages[tab_id], target)
                    continue
                if page is None: raise ValueError()
                if action == "navigate": await self.navigate(page, cmd["url"])
                elif action == "back":
                    with suppress(Exception): await self.go_back(page)
                elif action == "reload":
                    tab_id = self.page_ids[page]
                    self.navigation.grant(tab_id, page.url)
                    try: await page.reload(wait_until="domcontentloaded", timeout=15000)
                    finally: self.navigation.revoke(tab_id)
                elif action == "click":
                    await page.mouse.click(max(0, min(WIDTH - 1, cmd["x"])), max(0, min(HEIGHT - 1, cmd["y"])))
                elif action == "scroll": await page.mouse.wheel(0, max(-1000, min(1000, cmd["delta"])))
                elif action == "type": await page.keyboard.insert_text(cmd["text"][:2000])
                elif action == "key" and cmd["key"] in KEYS: await page.keyboard.press(cmd["key"])
            except Exception:
                self.error = "That browser action could not complete. Try again or reload the page."

    async def snapshots(self):
        tick = 0
        while self.running:
            page_id = self.policy.active
            document_revision = self.documents.get(page_id)
            page = self.pages.get(page_id)
            frame = None
            try:
                if page:
                    tab = self.policy.tabs[page_id]
                    tab["title"] = (await asyncio.wait_for(page.title(), 2))[:300] or "Video page"
                    for item in self.items.values():
                        if item.page_url == tab["url"] and item.title in {"New tab", "Video page", "Detected video"}:
                            item.title = tab["title"]
                    # Only propagate actual HTTP navigations; aborted popups stay blank.
                    if page.url.startswith(("http://", "https://")): tab["url"] = page.url
                    if tick % 3 == 0:
                        for remote_frame in page.frames[:20]:
                            with suppress(Exception):
                                if await asyncio.wait_for(remote_frame.evaluate("Boolean(window.__uvdProtected)"), 1):
                                    self.protected_pages.add(page_id) if self.documents.get(page_id) == document_revision else None
                        # Bounded DOM inspection avoids moving huge HTML documents over IPC.
                        dom = await page.evaluate("""() => ({
                            videos: [...document.querySelectorAll('video')].slice(0, 40).map(v => ({src:v.currentSrc || v.src, duration:Number.isFinite(v.duration)?v.duration:null})),
                            sources: [...document.querySelectorAll('video source[src]')].slice(0, 40).map(v=>v.src)
                        })""")
                        for video in dom["videos"]:
                            self.add_media(video["src"], tab["title"], page_id, page_id in self.protected_pages)
                            if video["src"] in self.items: self.items[video["src"]].duration = video["duration"]
                        for url in dom["sources"]: self.add_media(url, tab["title"], page_id)
                    if page_id in self.protected_pages:
                        for target, item in self.items.items():
                            if item.page_url == tab["url"]: item.drm, item.formats = True, []
                    frame = await page.screenshot(type="jpeg", quality=65, timeout=3000)
                if self.policy.active != page_id or self.documents.get(page_id) != document_revision:
                    await asyncio.sleep(0.1)
                    continue
                state = {"status": "ready", **self.policy.snapshot(), "navigations": self.navigation.snapshot(),
                    "url": self.policy.tabs.get(self.policy.active, {}).get("url", ""),
                    "items": [item.model_dump() for item in self.items.values()], "error": self.error}
                if frame: state["frame"] = base64.b64encode(frame).decode()
                # Kept private by the parent; never returned in state responses.
                state["auth"] = {"cookies": await self.context.cookies(), "referrers": self.referrers,
                                 "user_agent": await page.evaluate("navigator.userAgent") if page else ""}
                emit(state)
            except Exception:
                # Navigation can destroy an execution context between two awaits.
                # Keep reporting pending tabs even while a page is loading.
                emit({"status": "ready", **self.policy.snapshot(), "navigations": self.navigation.snapshot(), "items": [i.model_dump() for i in self.items.values()], "error": self.error})
            tick += 1
            await asyncio.sleep(0.8)

    async def run(self, url):
        self.context.on("page", self.register)
        self.context.on("response", lambda response: self.background(self.response(response)))
        await self.context.route("**/*", self.route)
        async def close_socket(ws): await ws.close()
        await self.context.route_web_socket("**/*", close_socket)
        await self.context.expose_binding("__uvdRequestNavigation", self.proposed_navigation)
        await self.context.add_init_script(Path(__file__).with_name("browser_navigation.js").read_text())
        await self.context.add_init_script(DRM_SCRIPT)
        page = await self.context.new_page()
        self.register(page)
        ticker = asyncio.create_task(self.snapshots())
        try:
            await self.navigate(page, url)
            await self.commands()
        finally:
            self.running = False
            ticker.cancel()
            for task in list(self.tasks): task.cancel()
            await asyncio.gather(ticker, *self.tasks, return_exceptions=True)


async def main():
    for key in list(os.environ):
        if key.lower().endswith("_proxy"): os.environ.pop(key, None)
    payload = json.loads(sys.stdin.readline())
    try:
        from playwright.async_api import async_playwright
        with guarded_proxy() as proxy:
            async with async_playwright() as p:
                browser = await p.chromium.launch(proxy={"server": proxy, "bypass": "<-loopback>"},
                    args=["--mute-audio", "--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
                try:
                    context = await browser.new_context(viewport={"width": WIDTH, "height": HEIGHT},
                        service_workers="block", accept_downloads=False)
                    await InteractiveBrowser(context).run(payload["url"])
                finally:
                    await browser.close()
    except Exception:
        emit({"status": "error", "error": "Browser unavailable. Install the browser extra and Chromium: python -m pip install -e '.[browser]' then python -m playwright install chromium."})


if __name__ == "__main__":
    asyncio.run(main())
