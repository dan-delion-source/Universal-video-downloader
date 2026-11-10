"""Blocking pipeline; the API runs this in a bounded, killable worker process."""
import importlib.util
from urllib.parse import urlsplit
from backend.config import MAX_ITEMS
from backend.models import MediaItem
from backend.manifests import inspect_manifests, ProtectedStream
from backend.security import guarded_proxy, validate_url
from backend.extractors import static_extractor, ytdlp_extractor


def scan(url: str) -> dict:
    url = validate_url(url)
    warnings: list[str] = []
    results: list[MediaItem] = []
    seen_urls: set[str] = set()
    with guarded_proxy() as proxy:
        try: results.extend(ytdlp_extractor.extract(url, proxy, seen_urls))
        except Exception: warnings.append("The site extractor could not read this page; fallback scanning was attempted.")
        try: results.extend(item for item in static_extractor.extract(url, proxy) if item.download_target not in seen_urls)
        except Exception: warnings.append("The static page scan was unavailable.")
        if not results and importlib.util.find_spec("playwright") is not None:
            try:
                from backend.extractors.sniff_extractor import extract
                results.extend(extract(url, proxy))
            except Exception: warnings.append("Browser scan failed. Check that Playwright Chromium is installed.")
        unique: dict[str, MediaItem] = {}
        for item in results[:MAX_ITEMS * 2]:
            target = item.download_target
            if target in unique: continue
            if urlsplit(target).path.lower().endswith((".m3u8", ".mpd")):
                try:
                    inspect_manifests([target], proxy)
                    expanded = ytdlp_extractor.extract(target, proxy)
                    if expanded:
                        expanded[0].title, expanded[0].source = item.title, item.source
                        item = expanded[0]
                except ProtectedStream:
                    item.drm, item.formats = True, []
                except Exception:
                    warnings.append("A manifest could not be inspected; revalidation is required before download.")
            unique[target] = item
            if len(unique) >= MAX_ITEMS: break
    return {"items": [item.model_dump() for item in unique.values()], "warnings": list(dict.fromkeys(warnings))}
