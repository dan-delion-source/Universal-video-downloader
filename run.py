#!/usr/bin/env python3
"""Start the API and built UI with one command after initial installation."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent


def main():
    # Always use this checkout's environment, even from another working directory
    # or when a different project environment is active. Compare prefixes rather
    # than executable symlinks: venv Python often resolves to the system binary.
    env_dir = ROOT / ".venv"
    env_python = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.")
        return 1
    if not env_python.is_file():
        print("Set up this project first:\n  python setup_app.py")
        return 1
    if Path(sys.prefix).resolve() != env_dir.resolve():
        try:
            os.execv(str(env_python), [str(env_python), str(ROOT / "run.py"), *sys.argv[1:]])
        except OSError as exc:
            print(f"Could not start the project's Python: {exc}\nRun python setup_app.py to check the environment.")
            return 1
    missing = [name for name in ("uvicorn", "fastapi", "yt_dlp", "httpx", "selectolax") if importlib.util.find_spec(name) is None]
    if missing:
        print("Missing Python dependencies: " + ", ".join(missing))
        print("Run python setup_app.py to install the project dependencies.")
        return 1
    if not (ROOT / "frontend/dist/index.html").is_file():
        npm = shutil.which("npm")
        if not npm:
            print("Built frontend missing. Install Node.js 20.19+ and run:\n  cd frontend\n  npm ci\n  npm run build")
            return 1
        try:
            subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=ROOT / "frontend", check=True)
            subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
        except subprocess.CalledProcessError:
            print("Frontend build failed. Check Node.js and your network connection, then retry.")
            return 1
    from backend.config import HOST, PORT
    if HOST not in {"127.0.0.1", "localhost"}:
        print("UVD is a single-user local tool. UVD_HOST must be a loopback address.")
        return 1
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found: only combined video/audio formats will be offered.")
    url = f"http://{'[' + HOST + ']' if ':' in HOST else HOST}:{PORT}"
    print(f"Universal Video Downloader → {url}\nPress Ctrl+C to stop.")
    def open_when_ready():
        # Readiness polling avoids opening a tab before the server starts.
        import time
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            try:
                with opener.open(url + "/api/health", timeout=0.5) as response:
                    if response.status == 200:
                        webbrowser.open(url)
                        return
            except OSError: time.sleep(0.2)
    if os.getenv("UVD_NO_BROWSER") != "1":
        threading.Thread(target=open_when_ready, daemon=True).start()
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT, log_level="warning", access_log=False)
    return 0

if __name__ == "__main__":
    sys.exit(main())
