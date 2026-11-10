"""Small, explicit limits for a single-user local application."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOWNLOAD_DIR = ROOT / "downloads"
DIST_DIR = ROOT / "frontend" / "dist"
MAX_JOBS = 2
MAX_ITEMS = 40
MAX_PENDING = MAX_ITEMS
MAX_HISTORY = 100
SCAN_TIMEOUT = 65
NETWORK_TIMEOUT = 12
DOWNLOAD_TIMEOUT = 7200
MAX_HTML_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024**3
HOST = os.getenv("UVD_HOST", "127.0.0.1")
PORT = int(os.getenv("UVD_PORT", "8000"))
