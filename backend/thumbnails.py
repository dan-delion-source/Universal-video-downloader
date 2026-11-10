"""Bounded image fetching through the same pinned-address proxy as media."""
import base64
from urllib.parse import urljoin
import httpx
from backend.security import guarded_proxy, validate_url


def fetch_thumbnail(url: str):
    with guarded_proxy() as proxy, httpx.Client(proxy=proxy, trust_env=False, timeout=8) as client:
        for _ in range(5):
            validate_url(url)
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                media_type = response.headers.get("content-type", "").split(";")[0]
                if media_type not in {"image/jpeg", "image/png", "image/webp", "image/avif", "image/gif"}:
                    raise ValueError("Unsupported thumbnail type.")
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 2 * 1024 * 1024: raise ValueError("Thumbnail too large.")
                return {"data": base64.b64encode(data).decode(), "media_type": media_type}
    raise ValueError("Too many redirects.")
