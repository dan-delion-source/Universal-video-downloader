"""Download worker. Only this child process owns yt-dlp and its muxing child."""
import json
import os
import shutil
from urllib.parse import urlsplit
import yt_dlp
from backend.config import DOWNLOAD_DIR, MAX_FILE_BYTES
from backend.security import guarded_proxy, validate_url, sanitize_filename
from backend.extractors.ytdlp_extractor import options, format_selector
from backend.manifests import inspect_manifests
from backend.browser_auth import cookie_jar, apply_cookies
from backend.extractors.static_extractor import fetch_document


def emit(**event):
    print(json.dumps(event), flush=True)


def download(payload: dict):
    url = validate_url(payload["url"])
    job_id = payload["job_id"]
    # Separate directory per job prevents collisions even during concurrent runs.
    work = DOWNLOAD_DIR / (".job-" + job_id)
    work.mkdir(parents=True, exist_ok=False)
    final = None
    try:
        with guarded_proxy() as proxy:
            opts = options(proxy)
            browser_auth = payload.get("browser_auth")
            if browser_auth:
                opts["http_headers"] = {key: value for key, value in {
                    "Referer": browser_auth.get("referer"), "User-Agent": browser_auth.get("user_agent")}.items() if value}
            cookie_browser = payload.get("cookie_browser") if not browser_auth else None
            if cookie_browser:
                opts["cookiesfrombrowser"] = (cookie_browser,)
            with yt_dlp.YoutubeDL(opts) as ydl:
                apply_cookies(ydl, browser_auth)
                info = ydl.extract_info(url, download=False)
                if not info or info.get("entries") is not None:
                    raise ValueError("Select an individual video from the scan results.")
                formats = info.get("formats") or [info]
                # External protocols could invoke ffmpeg as a network downloader.
                formats = [f for f in formats if f.get("protocol", "https") in
                    {"http", "https", "m3u8_native", "m3u8", "http_dash_segments"}
                    and urlsplit(f.get("url") or "").scheme in {"http", "https"}]
                if not formats: raise ValueError("No supported HTTP video formats were found.")
                formats = [f for f in formats if not f.get("has_drm")]
                if not formats: raise ValueError("This video is protected and cannot be downloaded.")
                info["formats"] = formats
                if info.get("has_drm") or all(f.get("has_drm") for f in formats):
                    raise ValueError("This video is protected and cannot be downloaded.")
                # Inspect both master and selected HLS variant URLs. Variants need
                # not have a .m3u8 suffix and may carry encryption independently.
                manifests: set[str] = set()
                for fmt in formats:
                    if fmt.get("manifest_url"): manifests.add(fmt["manifest_url"])
                    target = fmt.get("url") or ""
                    protocol = fmt.get("protocol", "")
                    if (protocol.startswith("m3u8") or urlsplit(target).path.lower().endswith((".m3u8", ".mpd"))
                        or (protocol.startswith("http_dash") and not fmt.get("manifest_url"))):
                        manifests.add(target)
                def fetch_manifest(target, proxy_url):
                    return fetch_document(target, proxy_url, headers=opts.get("http_headers"), cookies=cookie_jar(browser_auth))
                inspect_manifests(manifests, proxy, fetch=fetch_manifest)
                selector = format_selector(payload.get("format_id", "best"), formats, bool(shutil.which("ffmpeg")))
            transferred: dict[str, int] = {}
            def hook(data):
                if data["status"] == "downloading":
                    transferred[data.get("filename", "video")] = data.get("downloaded_bytes", 0)
                    if sum(transferred.values()) > MAX_FILE_BYTES:
                        raise ValueError("Download exceeds the 10 GB size limit.")
                    total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                    emit(status="downloading", percent=min(99, data.get("downloaded_bytes", 0) / total * 100) if total else 0,
                        speed=data.get("speed"), eta=data.get("eta"))
                elif data["status"] == "finished":
                    emit(status="merging", percent=99, speed=None, eta=None)
            opts.update({"format": selector, "merge_output_format": "mp4", "noplaylist": True,
                         "outtmpl": str(work / "video.%(ext)s"), "progress_hooks": [hook],
                         "overwrites": False, "restrictfilenames": True})
            emit(status="downloading", percent=0)
            with yt_dlp.YoutubeDL(opts) as ydl:
                apply_cookies(ydl, browser_auth)
                info = ydl.process_ie_result(info, download=True)
            candidates = [p for p in work.iterdir() if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v"}]
            if len(candidates) != 1:
                raise ValueError("No single merged video was produced. Check ffmpeg and the selected format.")
            source = candidates[0]
            if source.stat().st_size > MAX_FILE_BYTES: raise ValueError("Output exceeds the 10 GB size limit.")
            base = sanitize_filename(payload.get("title") or info.get("title") or "video")
            # Exclusive creation reserves a filename across all worker processes.
            for counter in range(10000):
                name = f"{base}{' (' + str(counter) + ')' if counter else ''}{source.suffix}"
                final = DOWNLOAD_DIR / name
                try:
                    # Publish atomically, without copying a multi-GB file or overwriting.
                    os.link(source, final)
                    source.unlink()
                    break
                except FileExistsError:
                    final = None
            if final is None: raise ValueError("Too many files share this title.")
            emit(status="complete", percent=100, filename=final.name, speed=None, eta=None)
    finally:
        shutil.rmtree(work, ignore_errors=True)
