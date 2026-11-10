# Build verification

Performed in the restricted build workspace on 2026-10-25.

## Passed

- Production Preact/Vite build: `npm run build --prefix frontend`.
- Built JavaScript: approximately **11.49 KB gzipped**, below the 60 KB target. CSS: approximately 3.82 KB gzipped. The self-hosted font is a separate asset.
- Python syntax compilation: `python -m compileall -q backend tests run.py`.
- **70 offline tests**: security (44), format selection/normalization (8), job queue/cancellation/concurrency (3), protected manifests and redirect validation (9), recursive HLS inspection and long-title regression tests (6).
- Startup without installed dependencies: `python run.py` prints the missing modules and the exact install command, then exits with status 1.
- Independent read-only review caught two defects, both fixed and confirmed: inconsistent long-title limits, and encryption in extensionless HLS child playlists escaping inspection.
- Frontend detector inspection found one progress-bar width transition; changed it to a transform transition.

The available pytest and httpx installations from other local environments were used read-only via PYTHONPATH for the offline tests. No files in those projects were changed. Frontend packages were recovered from local npm cache into this project's node_modules; a production build and package lock are included.

## Not verified here

- The complete Python dependency install. PyPI DNS resolution was unavailable. FastAPI, uvicorn, yt-dlp, and selectolax were absent from this project's environment.
- Two selectolax HTML-fixture tests and eight FastAPI API/SSE tests are authored but could not run without those dependencies.
- An actual HTTP server, live extraction, real downloads/muxing, SSE over a socket, actual process-tree cancellation with ffmpeg, or an engine upgrade. Socket creation is blocked by the sandbox (`Operation not permitted`).
- Desktop/mobile browser interaction and screenshot review. The available Playwright installation had no matching Chromium executable; downloading one also requires network access.
- Optional Python Playwright/Chromium capture, browser-cookie extraction, and Windows/macOS runtime behavior.

Install the project dependencies in a normal virtual environment, run the full pytest suite, then follow the end-to-end checks in README.md. These limitations concern available verification; they are not claims that these features passed or failed in actual use.

## Advanced browser update — 2026-10-26

Implemented an optional interactive Chromium viewer, paused popup navigation with Stay/Go decisions, automatic network/DOM video discovery, a private cookie/referrer handoff for downloads, session cleanup/deadlines, and the responsive advanced-mode UI.

- Production frontend build passed: about **14.00 KB gzipped JavaScript**, below the original 60 KB target.
- **95 tests passed** using this project's installed Python dependencies and pytest loaded read-only from an existing local environment. This includes all 72 non-TestClient baseline tests (the two HTML fixture tests now run with installed selectolax), plus 23 advanced-browser policy, lifecycle, cookie, worker-routing, and in-process ASGI API tests.
- Browser-specific checks cover first-popup request blocking, explicit Go activation, Stay preserving the original page, fragment filtering, private state redaction, cookie domain/path/TLS scope and redirects, expired sessions, cleanup, protected-state reset after navigation, embedded-player referrer capture, and session-bound download validation.
- Python syntax compilation passed. The frontend mechanical detector reported no findings for this update.
- Read-only finish review found a sticky per-tab DRM flag; document-navigation reset and regression tests address it. Cookie tests also exposed httpx relaxing host-only cookie policy during jar merging; per-request, per-redirect cookie headers now preserve the strict policy.

Unverified in this sandbox:

- Real Chromium session startup, page interaction, media capture from real sites, popup behavior in a running browser, real file downloads, and desktop/mobile screenshots. Installing the optional Playwright package was unavailable; a system-browser launch attempt was also blocked by the sandbox.
- The eight pre-existing synchronous TestClient API tests could not run here: the cross-thread ASGI portal stalled under this sandbox. A bounded diagnostic timed out. The new advanced API tests use asynchronous in-process ASGI transport and passed; this does not prove a live HTTP server works.

To verify locally, install the browser extra and Chromium, start the app, and use a public page you control with a video, an overlay, and a link opening a new tab. Confirm Stay preserves the original page, Go loads the selected destination, a played video appears automatically, its download works, and closing the viewer terminates its browser. Repeat with multiple tabs, a protected player followed by a clear page, and with Playwright absent. No claim of real-site compatibility or screenshot review is made here.

## Navigation consent fix — 2026-10-26

The user reported unwanted automatic tab/page changes. The prior implementation paused newly registered tabs but still allowed an approved tab's page scripts to replace its current document. It also allowed server redirects through ordinary `route.continue_()`.

Changes:

- A pre-document script converts `window.open` and new-window anchor clicks into proposals; the application creates a new tab only after Go. Native/form popup fallbacks remain paused.
- Page-initiated main-document navigations return HTTP 204 to retain the current document and produce a destination prompt below the viewer. Stay removes the proposal without navigating.
- App-requested initial loads, address-bar navigation, Back, Reload, and approved proposals receive an exact, single-use destination permit. Approval does not grant later ad navigation.
- Main-document responses use `route.fetch(max_redirects=0)`. A Location redirect creates its own proposal; the next destination is not fetched automatically. Known direct media URLs use a video-player wrapper instead of buffering their full files as documents.
- Form methods/bodies (up to 1 MB) are retained privately for approved replay; they never enter public proposal state. Redirect method changes follow 301/302/303 versus 307/308 behavior.

Verification: **103 Python tests and 4 Node JavaScript tests passed**, Python compilation passed, and the production frontend build passed (about 14.12 KB gzipped JS). Regression cases cover no native window creation from scripted open, target-blank anchors, preserving the current page on Stay, exact one-use permits, explicit creation on Go, server redirects requiring fresh consent, and private POST replay. Read-only review confirmed the redirect and form-replay fixes. Actual Chromium/site interaction and screenshots remain unverified under the same sandbox restrictions described above.

## Setup and run scripts — 2026-10-26

Added `setup_app.py` for one-time local-venv dependency setup (including Playwright/Chromium by default, with `--basic` available). Updated `run.py` to re-execute with this checkout's `.venv` automatically, so activation is unnecessary.

Python compilation and `setup_app.py --help` passed. Executed the launcher against a temporary fake interpreter from another working directory, including a project path containing spaces; interpreter/argument selection and missing-setup messaging passed. Mocked setup orchestration verified environment creation/reuse, local-environment pip use, browser installation commands, and basic mode. These checks did not install packages or download Chromium; full setup still needs network access in the user's terminal.
