# Universal Video Downloader

A small local web app for discovering videos on a webpage, choosing a quality, and downloading video with audio. Runs on your computer with FastAPI and a built Preact interface. No database, Docker, accounts, or cloud service.

Run these from the project folder using **Python 3.10+**:

```sh
# First time only: create .venv, install the app + Advanced mode, and install Chromium
python setup_app.py

# Every time you want to use the app
python run.py
```

On Linux/macOS, use `python3` instead of `python` if that is your Python command. On Windows, `py` also works if your Python installation provides that launcher. **No manual environment activation is needed.** The runner automatically selects this project's `.venv`, including when you launch it from another folder or have another environment active.

Open **http://127.0.0.1:8000**. The launcher opens your browser after the server is ready. Stop with Ctrl+C. Stop and restart the runner after code updates; ordinary restarts do not require setup again.

## Install

`setup_app.py` creates or reuses the local virtual environment, installs Python dependencies, installs Playwright and Chromium for Advanced mode, and checks dependency imports. It uses the included production frontend; **Node is not required for normal use**. If the built frontend is absent, setup builds it using npm when available. The script does not install system packages as administrator.

Setup needs an internet connection. Running it again is safe: it reuses the environment and installed browser files. Rerun it after project dependency changes, if the environment is removed, or if an installation was interrupted. Browsing and downloading do not require repeating setup.

For a smaller install without Advanced mode or browser scanning:

```sh
python setup_app.py --basic
```

To add Advanced mode later, run `python setup_app.py` without `--basic`. Chromium may require additional OS libraries; see the optional browser section below. On Debian/Ubuntu, install `python3-venv` if creating the environment fails. On Arch, Python and pip should be available through your package manager.

Manual virtual-environment installation remains possible, but is not required by these scripts.

### ffmpeg

Install the **system binary**, not a Python package:

```sh
# Debian / Ubuntu
sudo apt install ffmpeg

# Arch Linux
sudo pacman -S ffmpeg

# macOS with Homebrew
brew install ffmpeg
```

On Windows, get a Windows build linked from [ffmpeg.org](https://ffmpeg.org/download.html), extract it, and add its `bin` directory to your user PATH. Reopen your terminal. Verify on every platform with:

```sh
ffmpeg -version
```

Without ffmpeg the app still runs, but offers only formats that already contain video and audio. Some sites have no such format, and cannot be downloaded until ffmpeg is installed. When available, ffmpeg merges separate streams; the requested merge container is MP4. Already-combined streams retain their original container.

### Optional browser scanner

The default `python setup_app.py` installs Playwright and Chromium for Advanced mode and JavaScript-heavy page scanning. If you originally chose `--basic`, rerun setup without that flag to add them. Playwright remains an optional Python extra and is imported lazily; normal scanning works without it.

Chromium also needs platform libraries. On supported Linux distributions, Playwright can install missing OS dependencies using `.venv/bin/python -m playwright install --with-deps chromium` (may request administrator access). The setup script reports failed browser installation steps; it does not silently install system packages. The health response reports whether the Python package is installed, rather than certifying Chromium can launch.

## Use

1. Paste a public webpage, video, playlist, or direct media URL and choose **Find videos**.
2. Review the results. Select **Best available** or a specific quality on each card.
3. Choose **Download video**, or **Download all (best)** for several videos.
4. Follow progress and cancel individual jobs if needed.
5. When complete, choose **Save file** to save a copy through your browser. The original is already in `downloads/`.

Use the **Downloads** tab to follow jobs after scanning another page. The queue runs two downloads at a time. Files are published atomically and duplicate titles get a numeric suffix.

**Universal describes the pipeline, not a guarantee of support for every URL or every video.** Sites can require sign-in, restrict access, change their players, use expiring URLs, or protect their streams. The app does not bypass these restrictions. Extractor limitations may prevent discovery even with the browser extra.

### Engine updates and optional cookies

**Update engine** runs `python -m pip install --upgrade yt-dlp` inside the interpreter running the app. It waits until no scans/downloads are active, returns the installed version, and new worker processes use the updated code. A virtual environment and internet access are required. It only updates yt-dlp, not the entire app. You can also run:

```sh
python -m pip install -U yt-dlp
```

For your own signed-in browser session, optionally set `UVD_COOKIE_BROWSER` before starting. For example:

```sh
# Linux / macOS
UVD_COOKIE_BROWSER=firefox python run.py
```

```powershell
# Windows PowerShell
$env:UVD_COOKIE_BROWSER = 'firefox'
python run.py
```

Supported names: `firefox`, `chrome`, `chromium`, `edge`, `brave`, `opera`, `vivaldi`, `safari` (availability depends on your OS and yt-dlp). This uses yt-dlp's `cookiesfrombrowser` in the site extractor and downloader. Static HTML and optional Chromium scanning do not share your browser profile. No cookie upload, cookie logging, or cookie value display is implemented.

## How it works

- A killable scan process runs yt-dlp and a static HTML scan, merges results, and deduplicates original URLs and media URLs already identified by yt-dlp. Static scanning collects video/source tags, Open Graph and Twitter stream metadata, JSON-LD `contentUrl`, direct links, and inline-script media URLs.
- If neither returns a result and Playwright is installed, a headless browser attempts playback and observes media responses for eight seconds.
- Direct HLS/DASH manifests are inspected and passed to yt-dlp for quality metadata. Recognized DRM and encrypted HLS/DASH manifests are marked protected. Encrypted HLS, including AES-128, is conservatively unsupported even when it is not a commercial DRM system.
- Downloads re-extract metadata, filter supported HTTP formats, inspect manifests, and select either `bestvideo*+bestaudio/best` or the requested format plus audio if needed. ffmpeg performs local merging.
- Each download runs in its own subprocess. Cancelling terminates the process tree, including ffmpeg, and cleans the job's staging directory. Progress uses bounded SSE queues with an initial status snapshot, keepalives, and reconnect support.
- History is in memory (up to 100 recent jobs, with active subscribers retained). It resets when the server restarts. Completed files remain in `downloads/`; delete unwanted files there yourself. A hard crash can leave hidden `.job-*` staging folders; remove these only after stopping the app.

### Network and file boundaries

The launcher accepts loopback binding only. The API rejects foreign Host headers, cross-origin browser mutations, and mutation requests without JSON. It does not enable CORS. Browser thumbnails are fetched through the backend instead of loading remote image URLs directly.

Only HTTP/HTTPS on ports 80/443 are supported. Hostnames are resolved and private, loopback, link-local, multicast, reserved, and translation address ranges are rejected. All worker HTTP traffic uses a local validation proxy which connects to the exact public IP it checked; redirected/subresource/manifest requests are checked on connection too. Worker proxy-bypass environment variables are removed. Optional Chromium uses the same proxy, blocks service workers and WebSockets, and disables QUIC and non-proxied WebRTC traffic. External network download protocols are excluded; ffmpeg is used for local muxing.

Every network operation has a timeout. Scan processes have a 65-second deadline; downloads have a two-hour deadline. Defaults: 40 results, two concurrent scans, two concurrent downloads, 40 queued/active jobs, 4 MB HTML/manifest responses, 2 MB thumbnails, 10 GB download/output limit. Constants live in `backend/config.py`.

Files are served only from the top level of `downloads/`, with safe names and video extensions. Path traversal, hidden staging directories, and symlink targets are rejected. This remains a trusted, single-user local tool; do not expose it through a public reverse proxy.

## API

Interactive reference: **http://127.0.0.1:8000/docs**. FastAPI’s standard Swagger documentation loads its UI assets from a CDN; the main app and its fonts are served locally. The schema is also available at `/openapi.json`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/scan` | `{url}` → `{items, warnings}` |
| POST | `/api/download` | `{url, format_id: "best", title}` → `{job_id}` |
| GET | `/api/jobs/{id}/events` | SSE status, percentage, speed in bytes/s, ETA in seconds, filename, error |
| GET | `/api/jobs` | `{jobs}` with recent jobs, newest first |
| POST | `/api/jobs/{id}/cancel` | Cancel job; send `{}` as JSON |
| GET | `/api/files/{filename}` | Save a completed file |
| GET | `/api/health` | ffmpeg, Playwright package, yt-dlp version, concurrency |
| POST | `/api/update-engine` | Upgrade yt-dlp; send `{}` as JSON |
| GET | `/api/thumbnails/{item_id}` | Guarded, size-limited thumbnail for a scan result |

Normalized items include `id`, `title`, `thumbnail`, `duration`, `source`, `drm`, `formats`, and `download_target`. Each format includes `format_id`, `resolution`, `fps`, `ext`, `filesize`, `note`, plus sorting metadata `height`, `bitrate`, `video_only`. Unavailable metadata is null or a documented display fallback; approximate sizes originate from yt-dlp. Bitrates are in kbps. Format IDs are revalidated against current metadata at download time.

## Develop and test

For rebuilding the UI only, install Node.js **20.19+ or 22.12+** (or newer supported versions):

```sh
cd frontend
npm ci
npm run build
cd ..
python run.py
```

`run.py` does this automatically if `frontend/dist/index.html` is absent and npm is available. If Node is unavailable it prints explicit build instructions. Commit the resulting `frontend/dist/` so normal users need only Python. The build uses no remote fonts or UI library. Manrope is self-hosted with its font license in `frontend/public/fonts/OFL.txt`.

For frontend development, run `python run.py` in one terminal and `cd frontend && npm run dev` in another. Vite proxies `/api` to port 8000. API requests remain same-origin from the browser's perspective. The production app uses the single FastAPI server.

```sh
python -m pip install -e '.[test]'
python -m pytest
```

Tests cover URL/SSRF policy, mixed DNS answers, DNS pinning, path handling, filename sanitizing, HTML fixtures, redirects, protected manifests, quality selection, missing ffmpeg, queue limits, cancellation, concurrency, bounded subscriber queues, and API/SSE behavior. Tests use mocked network responses and do not download real videos.

Build-environment verification is recorded in [VALIDATION.md](VALIDATION.md). For an actual end-to-end check, start the app outside a restricted sandbox, inspect `/api/health`, scan a public video you own or have permission to save, download it, verify both video and audio play, and exercise cancellation and browser reconnection. Repeat with ffmpeg unavailable and with the optional browser extra installed. Offline tests do not prove site compatibility or actual browser behavior.

## Troubleshooting

- **Missing dependencies:** activate the environment and run `python -m pip install -e .` with the same Python used for `run.py`.
- **Cannot access the local server:** keep the terminal open, check port 8000, and use the printed URL. Change the port with `UVD_PORT=8001 python run.py` (PowerShell: set `$env:UVD_PORT`). `UVD_NO_BROWSER=1` suppresses browser opening. `UVD_HOST` can be `127.0.0.1` or `localhost`.
- **No videos found:** use an individual video page or direct link, try updating the engine, or install the optional browser scanner. Dynamic-page capture does not interact with login screens or consent dialogs.
- **Quality unavailable / expired link:** scan again. Signed links and available formats can change between extraction and download.
- **Protected content:** DRM is unsupported. No decryption keys, CDM integration, or DRM removal is provided.
- **Engine update failed:** run the pip command directly in the virtual environment. Check internet access and write permissions. Restart after a manually interrupted update.
- **Browser scan failed:** run `python -m playwright install chromium`; resolve OS dependencies reported by Playwright. The base app works without it.
- **Private address / nonstandard port rejected:** local network servers and unusual ports are intentionally excluded by the SSRF policy.
- **Large playlist / slow scan:** discovery is bounded to 40 items and 65 seconds. Scan smaller playlists or individual pages.
- **Filename collision:** the app adds `(1)`, `(2)`, etc. Files are never overwritten.

## Legal notice

Download only content you own or have permission to save. Respect applicable law, copyright, and the source site's terms. DRM-protected content is unsupported and the app does not attempt to bypass DRM.

## Advanced browser mode

For pages where overlays or new tabs get in the way of playing a video:

1. Run `python setup_app.py` once. The default setup includes the browser extra and Chromium. If you previously used `--basic`, rerun setup without that flag.

2. Restart `python run.py`. Enable **Advanced mode**, paste a URL, and click **View**. You can also choose **View page** on a result card.
3. A compact interactive browser viewer appears. Click the preview to close page overlays or press the player's Play button. You can type into a focused page field, paste text, navigate with the address bar, go back, reload, or use the scroll controls. **Focus next field** sends Tab to the remote page; normal Tab moves between the app's own controls.
4. When a page opens another tab, a prompt appears **below the preview**. **Stay** closes the new tab and keeps the original page. **Go to new tab** permits its navigation and switches the viewer. New-tab navigation is paused until you choose Go. Approved tabs remain available in the tab strip; at most five tabs are kept.
5. HTTP video and manifest responses are detected automatically. Detected media appears below the viewer with **Download video**, live job progress, and **Save file**. It also stays in the main results when the viewer closes. Ad videos can appear too; choose the video you want.

The viewer is a periodically refreshed, silent preview of an isolated Chromium session. It can respond more slowly than a normal browser. Third-party page scripts run inside Chromium, not in the downloader UI. There is no iframe-based embedding and no general-purpose ad blocker; you interact with the page's controls yourself. Some sites block automated browsers, and players exposing only media fragments, blob URLs without an accessible HTTP source, or protected content may not produce a downloadable video.

The live browser requires Playwright and its Chromium installation; regular scanning still works without them. The viewer does not import your existing browser profile. Its session cookies and the originating request's referrer are passed privately to download workers so authenticated media URLs can work. Cookies remain in memory, are scoped by domain/path/TLS, and are omitted from public API responses and logs. Closing the viewer stops its browser process, while recent detected-media handoffs remain available for up to 15 minutes of inactivity. At most four recent session snapshots are kept; restarting the app clears them. Already queued downloads retain their own handoff and can finish after the viewer closes.

One interactive browser runs at a time. A live session expires after 30 minutes, or after 15 minutes without app interaction/polling. All browser traffic uses the existing public-address-only proxy; service workers, WebSockets, QUIC, and non-proxied WebRTC are disabled. Recognized encrypted streams and DRM remain unsupported.

Advanced-mode API additions:

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/browser/sessions` | `{url}` opens a browser session |
| GET | `/api/browser/sessions/{id}` | Public state, tabs, pending popups, and detected items; no cookies |
| GET | `/api/browser/sessions/{id}/frame` | Current JPEG preview |
| POST | `/api/browser/sessions/{id}/command` | Navigate, click, type, scroll, back, reload, stay, activate, or close a tab |
| POST | `/api/browser/sessions/{id}/close` | Close the viewer's browser process |

`POST /api/download` accepts an optional `browser_session_id`. The server only permits targets previously detected in that session and rejects items marked protected. The private cookie/referrer handoff does not pass through the browser UI. Advanced results include `page_url` for returning to the originating page; initial quality selection is Best available, with available formats re-extracted by the download worker.

### Choosing whether to follow a link

The viewer keeps the current page until you choose a pending destination. A website's new-window request shows **Open a new tab?** with **Stay here / Go to new tab**. A request to replace the current page shows **Leave this page?** with **Stay here / Continue**. The destination hostname and URL are displayed below the preview. Clicking Stay dismisses that request; clicking Go/Continue approves that destination once. Server redirects to another destination ask again. The address bar, Back, and Reload are explicit app controls and do not need an extra prompt for their requested URL.

After updating the code, stop and restart `python run.py`, then refresh the app so the rebuilt frontend and new browser worker are both loaded. Existing viewer sessions must be reopened to receive the new pre-document popup guard.
