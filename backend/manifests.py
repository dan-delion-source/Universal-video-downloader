"""Bounded inspection of HLS/DASH, including extensionless HLS variants."""
import re
from collections.abc import Callable, Iterable
from urllib.parse import urljoin
from backend.extractors.static_extractor import fetch_document, protected_manifest


class ProtectedStream(ValueError):
    pass


def playlist_children(text: str, base: str) -> list[str]:
    children = []
    next_is_playlist = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line: continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            next_is_playlist = True
        elif line.startswith(("#EXT-X-MEDIA:", "#EXT-X-I-FRAME-STREAM-INF:", "#EXT-X-RENDITION-REPORT:")):
            match = re.search(r'(?:^|,)\s*URI="([^"]+)"', line.split(":", 1)[1])
            if match: children.append(urljoin(base, match[1]))
        elif not line.startswith("#") and next_is_playlist:
            children.append(urljoin(base, line))
            next_is_playlist = False
    return list(dict.fromkeys(children))


def inspect_manifests(targets: Iterable[str], proxy: str,
                      fetch: Callable = fetch_document) -> None:
    visited: set[str] = set()
    def inspect(target: str, depth: int = 0):
        if target in visited: return
        if depth > 3 or len(visited) >= 40:
            raise ValueError("Manifest exceeds the safe inspection limit.")
        visited.add(target)
        text, final_url, _ = fetch(target, proxy)
        if protected_manifest(text):
            raise ProtectedStream("Encrypted or DRM-protected streams are unsupported.")
        if "#EXTM3U" in text:
            for child in playlist_children(text, final_url): inspect(child, depth + 1)
    for target in targets:
        if target: inspect(target)
