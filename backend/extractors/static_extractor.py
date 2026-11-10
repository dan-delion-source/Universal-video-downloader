import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import Request as CookieRequest
import httpx
from backend.config import MAX_HTML_BYTES, MAX_ITEMS, NETWORK_TIMEOUT
from backend.models import MediaItem, MediaFormat
from backend.security import parse_url, validate_url

MEDIA = re.compile(r'''(?:https?://|//|/|\./)[^\s<>"'`\\]+?\.(?:mp4|webm|m4v|mov|m3u8|mpd)(?:\?[^\s<>"'`\\]*)?''', re.I)


def protected_manifest(text: str) -> bool:
    # Conservative policy: encrypted HLS (including AES-128) is unsupported.
    return bool(re.search(r'widevine|playready|fairplay|<\s*(?:\w+:)?ContentProtection\b|#EXT-X-(?:SESSION-)?KEY:(?![^\n]*METHOD=NONE)', text, re.I))


def parse_html(html: str, url: str) -> list[MediaItem]:
    from selectolax.parser import HTMLParser
    tree = HTMLParser(html)
    heading = tree.css_first("title")
    title = heading.text(strip=True) if heading else "Video"
    thumb = tree.css_first('meta[property="og:image"]')
    thumbnail = urljoin(url, thumb.attributes.get("content", "")) if thumb else None
    candidates: dict[str, str] = {}
    def add(value, label=title):
        if not isinstance(value, str) or not value.strip(): return
        target = urljoin(url, value.strip().replace("&amp;", "&"))
        try: parse_url(target)
        except ValueError: return
        candidates.setdefault(target, label or title)
    for node in tree.css("video[src], video source[src]"):
        add(node.attributes.get("src"), node.attributes.get("title", title))
    for node in tree.css('meta[property="og:video"],meta[property="og:video:url"],meta[property="og:video:secure_url"],meta[name="twitter:player:stream"],meta[property="twitter:player:stream"]'):
        add(node.attributes.get("content"))
    for node in tree.css("a[href]"):
        value = node.attributes.get("href", "")
        if urlsplit(value).path.lower().endswith((".mp4", ".webm", ".m3u8", ".mpd", ".mov", ".m4v")):
            add(value, node.text(strip=True))
    def walk(obj):
        if isinstance(obj, dict):
            if "contentUrl" in obj: add(obj["contentUrl"], obj.get("name", title))
            for value in obj.values(): walk(value)
        elif isinstance(obj, list):
            for value in obj: walk(value)
    for node in tree.css("script"):
        text = node.text().replace("\\/", "/")
        if node.attributes.get("type") == "application/ld+json":
            try: walk(json.loads(text))
            except (ValueError, RecursionError): pass
        for match in MEDIA.finditer(text): add(match.group())
    return [MediaItem(id=hashlib.sha256(target.encode()).hexdigest()[:16], title=label[:300],
        thumbnail=thumbnail, source="static", formats=[MediaFormat(format_id="best", ext=urlsplit(target).path.rsplit(".", 1)[-1].lower())],
        download_target=target) for target, label in list(candidates.items())[:MAX_ITEMS]]


def fetch_document(url: str, proxy: str, headers: dict | None = None, cookies=None) -> tuple[str, str, str]:
    with httpx.Client(proxy=proxy, timeout=NETWORK_TIMEOUT, trust_env=False, headers=headers) as client:
        for _ in range(6):
            validate_url(url)
            request_headers = dict(headers or {"User-Agent": "Mozilla/5.0 UniversalVideoDownloader/0.1"})
            if cookies is not None:
                # httpx merges request cookies into a fresh jar with a liberal
                # policy. Build this header per hop to preserve host-only scope.
                client.cookies.clear()
                cookie_request = CookieRequest(url)
                cookies.add_cookie_header(cookie_request)
                if cookie_request.has_header("Cookie"):
                    request_headers["Cookie"] = cookie_request.get_header("Cookie")
            with client.stream("GET", url, headers=request_headers) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                kind = response.headers.get("content-type", "").lower()
                if kind.startswith(("video/", "audio/")):
                    return "", url, kind
                parts, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_HTML_BYTES: raise ValueError("Page or manifest exceeds the 4 MB scan limit.")
                    parts.append(chunk)
                return b"".join(parts).decode("utf-8", errors="replace"), url, kind
    raise ValueError("Too many redirects.")


def extract(url: str, proxy: str) -> list[MediaItem]:
    text, final, kind = fetch_document(url, proxy)
    if kind.startswith("video/") or urlsplit(final).path.lower().endswith((".mp4", ".webm", ".m3u8", ".mpd")):
        return [MediaItem(id=hashlib.sha256(final.encode()).hexdigest()[:16],
            title=urlsplit(final).path.rsplit("/", 1)[-1], source="static", drm=protected_manifest(text),
            download_target=final, formats=[MediaFormat(format_id="best")])]
    return parse_html(text, final) if "html" in kind or "<" in text else []
