"""Optional Chromium scan. No Playwright import at application startup."""
from urllib.parse import urlsplit
import hashlib
from backend.models import MediaItem
from backend.security import parse_url
from .static_extractor import parse_html


def extract(url: str, proxy: str):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []
    found: set[str] = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(proxy={"server": proxy, "bypass": "<-loopback>"}, args=["--disable-quic", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
        try:
            context = browser.new_context(service_workers="block", accept_downloads=False)
            def route_request(route):
                try: parse_url(route.request.url)
                except ValueError: route.abort(); return
                route.continue_()
            context.route("**/*", route_request)
            # Refuse EME access before site scripts execute. A protected player is
            # reported rather than allowed to acquire a browser DRM session.
            context.add_init_script("""
                window.__uvdProtected = false;
                document.addEventListener('encrypted', () => { window.__uvdProtected = true; }, true);
                if (navigator.requestMediaKeySystemAccess) {
                    Object.defineProperty(navigator, 'requestMediaKeySystemAccess', { value: () => {
                        window.__uvdProtected = true;
                        return Promise.reject(new DOMException('Protected playback is unsupported', 'NotSupportedError'));
                    }});
                }
            """)
            context.route_web_socket("**/*", lambda ws: ws.close())
            page = context.new_page()
            page.on("response", lambda r: found.add(r.url) if (
                "video/" in r.headers.get("content-type", "") or
                "mpegurl" in r.headers.get("content-type", "") or
                "dash+xml" in r.headers.get("content-type", "") or
                urlsplit(r.url).path.lower().endswith((".mp4", ".webm", ".m3u8", ".mpd"))) else None)
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.evaluate("document.querySelectorAll('video').forEach(v => {v.muted=true;v.play().catch(()=>{})})")
            page.wait_for_timeout(8000)
            items = parse_html(page.content(), page.url)
            import html
            items += parse_html("".join(f'<video src="{html.escape(x, quote=True)}"></video>' for x in sorted(found)), page.url)
            if page.evaluate("Boolean(window.__uvdProtected)"):
                for item in items: item.drm, item.formats = True, []
                if not items:
                    items.append(MediaItem(id=hashlib.sha256(url.encode()).hexdigest()[:16],
                        title=page.title() or "Protected video", source="sniff", drm=True, download_target=url))
            for item in items: item.source = "sniff"
            return items
        finally:
            browser.close()
