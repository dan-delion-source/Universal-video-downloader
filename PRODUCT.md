# Universal Video Downloader
<!-- impeccable:product-schema 1 -->

## Platform
web, served locally on loopback.

## Stack
Python 3.10+, FastAPI, uvicorn, yt-dlp, httpx, selectolax, Pydantic; Preact, Vite, plain CSS. System ffmpeg; optional Playwright. No Docker, database, accounts, or cloud hosting.

## Purpose and users
A single user pastes a webpage or video link, reviews discovered videos and formats, and saves permitted content locally. Production runs with `python run.py` after installation. Node is required only to rebuild missing frontend output.

## Requirements supplied by the user
Merge site extraction and static scan results; use an optional browser fallback when neither finds videos. Offer quality selection, best-quality batch downloads, live SSE progress, cancellation, and file saving. Detect protected streams without bypassing them. Keep dependencies small and JavaScript under 60 KB gzipped. Support responsive light/dark themes and keyboard access.

## Constraints
Reject private and reserved network destinations, including redirects; sanitize paths; cap work and apply deadlines. Download history is in memory and completed files remain in downloads/. Site compatibility and content availability depend on upstream sites; do not promise every video is accessible.

## Advanced browser addition (2026-10-26)
The user requested a compact interactive viewer for pages with obstructing ads and popup tabs, Stay/Go to new tab decisions beneath it, and automatic media detection with download actions. The optional Playwright extra provides an isolated Chromium session; normal scanning stays available without it. This is an interactive page viewer with controlled popup navigation, not an ad-blocking or DRM-bypass feature.

The user explicitly requires permission before a website opens another tab or takes the viewer away from the current page, referencing VideoFetch's Stay/Continue behavior. Destination proposals must remain pending until the user decides, including replacement-page navigation and server redirects. No automatic follow or timeout approval.
