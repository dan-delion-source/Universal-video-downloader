"""JSON-lines protocol isolates extraction and downloads from the web server."""
import json
import os
import urllib.request
import sys


def main():
    # Force every urllib request, including redirects, through our explicit proxy.
    # Work is isolated in this process, so this cannot affect the API server.
    for key in list(os.environ):
        if key.lower().endswith("_proxy"): os.environ.pop(key, None)
    urllib.request.proxy_bypass = lambda host: False
    payload = json.loads(sys.stdin.readline())
    try:
        if payload["action"] == "scan":
            from backend.scanner import scan
            print(json.dumps(scan(payload["url"])), flush=True)
        elif payload["action"] == "thumbnail":
            from backend.thumbnails import fetch_thumbnail
            print(json.dumps(fetch_thumbnail(payload["url"])), flush=True)
        else:
            from backend.downloader import download
            download(payload)
    except Exception as exc:
        # Never forward extractor errors: they can contain tokens or cookie paths.
        from backend.security import UnsafeURL
        message = str(exc) if isinstance(exc, (UnsafeURL, ValueError)) else "The site could not be processed. Try scanning again or update the engine."
        print(json.dumps({"status": "error", "error": message[:400]}), flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
