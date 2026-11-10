"""Normalize yt-dlp metadata without exposing cookies or signed format URLs."""
import hashlib
import os
import shutil
from urllib.parse import urlsplit
from backend.models import MediaFormat, MediaItem
from backend.security import parse_url
from backend.config import MAX_ITEMS, NETWORK_TIMEOUT, MAX_FILE_BYTES


class QuietLogger:
    def debug(self, *_): pass
    def warning(self, *_): pass
    def error(self, *_): pass


def options(proxy: str) -> dict:
    opts = {"proxy": proxy, "socket_timeout": NETWORK_TIMEOUT, "retries": 1,
            "fragment_retries": 1, "extractor_retries": 1, "quiet": True,
            "logger": QuietLogger(), "noplaylist": True, "playlistend": MAX_ITEMS,
            "cachedir": False, "check_formats": False, "max_filesize": MAX_FILE_BYTES,
            "external_downloader": {"default": "native"}, "hls_prefer_native": True,
            "enable_file_urls": False}
    browser = os.getenv("UVD_COOKIE_BROWSER")
    if browser in {"firefox", "chrome", "chromium", "edge", "brave", "opera", "vivaldi", "safari"}:
        opts["cookiesfrombrowser"] = (browser,)
    return opts


def format_selector(selected: str, formats: list[dict], ffmpeg: bool) -> str:
    if selected == "best":
        return "bestvideo*+bestaudio/best" if ffmpeg else "best[vcodec!=none][acodec!=none]"
    fmt = next((f for f in formats if str(f.get("format_id")) == selected), None)
    if not fmt or fmt.get("has_drm") or fmt.get("vcodec") == "none":
        raise ValueError("That quality is no longer available. Scan the page again.")
    if not ffmpeg and fmt.get("acodec") == "none":
        raise ValueError("This quality needs ffmpeg. Choose a combined format.")
    return selected + "+bestaudio/best" if fmt.get("acodec") == "none" else selected


def normalize(info: dict, target: str, source: str = "yt-dlp") -> MediaItem:
    available = info.get("formats") or ([info] if info.get("url") else [])
    video = [f for f in available if f.get("vcodec") != "none"]
    drm = bool(info.get("has_drm") or info.get("_has_drm") or info.get("__has_drm") or (video and all(f.get("has_drm") for f in video)))
    formats = []
    for f in video:
        if f.get("has_drm") or (not shutil.which("ffmpeg") and f.get("acodec") == "none"):
            continue
        formats.append(MediaFormat(format_id=str(f.get("format_id", "direct")),
            resolution=f.get("resolution") or (f"{f['height']}p" if f.get("height") else "Original"),
            height=f.get("height") or 0, fps=f.get("fps"), ext=f.get("ext") or "mp4",
            filesize=f.get("filesize") or f.get("filesize_approx"), bitrate=f.get("tbr") or 0,
            video_only=f.get("acodec") == "none"))
    formats.sort(key=lambda f: (f.height, f.fps or 0, f.bitrate), reverse=True)
    if formats:
        formats[0].note = "Best"
    thumbnail = info.get("thumbnail")
    if thumbnail:
        try: parse_url(thumbnail)
        except ValueError: thumbnail = None
    return MediaItem(id=hashlib.sha256(target.encode()).hexdigest()[:16],
        title=(info.get("title") or urlsplit(target).path.rsplit("/", 1)[-1] or "Untitled video")[:300],
        thumbnail=thumbnail, duration=info.get("duration"), source=source,
        drm=drm, formats=[] if drm else formats, download_target=target)


def extract(url: str, proxy: str, seen_urls: set[str] | None = None) -> list[MediaItem]:
    import yt_dlp
    opts = options(proxy)
    opts.update({"noplaylist": False, "ignoreerrors": True, "allow_unplayable_formats": True})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    result = []
    def walk(entry):
        if not entry or len(result) >= MAX_ITEMS:
            return
        if entry.get("entries") is not None:
            for child in entry["entries"]:
                walk(child)
                if len(result) >= MAX_ITEMS: break
        elif entry.get("formats") or entry.get("url") or entry.get("has_drm"):
            target = entry.get("webpage_url") or entry.get("original_url") or url
            # Direct manifest extraction must retain the manifest as its target.
            if urlsplit(url).path.lower().endswith((".m3u8", ".mpd")):
                target = url
            try: parse_url(target)
            except ValueError: return
            result.append(normalize(entry, target))
            if seen_urls is not None:
                for fmt in entry.get("formats") or [entry]:
                    for key in ("url", "manifest_url"):
                        if fmt.get(key): seen_urls.add(fmt[key])
    walk(info)
    return result
