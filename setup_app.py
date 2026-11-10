#!/usr/bin/env python3
"""One-time setup for UVD, including Advanced mode by default."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
ENV_DIR = ROOT / ".venv"
ENV_PYTHON = ENV_DIR / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def step(label: str, command: list[str], cwd: Path = ROOT) -> None:
    print(f"\n{label}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up UVD once; use python run.py afterward.")
    parser.add_argument("--basic", action="store_true", help="Install regular scanning only, without Playwright/Chromium.")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.")
        return 1
    try:
        if not ENV_PYTHON.is_file():
            if ENV_DIR.exists():
                print("The existing .venv is incomplete. Rename that folder, then rerun this script.")
                return 1
            print("Creating the project's virtual environment…", flush=True)
            venv.EnvBuilder(with_pip=True).create(ENV_DIR)
        else:
            print("Using the existing .venv; no activation needed.", flush=True)

        pip_check = subprocess.run([str(ENV_PYTHON), "-m", "pip", "--version"], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if pip_check.returncode:
            step("Installing pip in the virtual environment…", [str(ENV_PYTHON), "-m", "ensurepip", "--upgrade"])
        step("Installing app dependencies…", [str(ENV_PYTHON), "-m", "pip", "install", "-e",
            str(ROOT) + ("" if args.basic else "[browser]")])
        if not args.basic:
            step("Installing Chromium for Advanced mode (already installed files are reused)…",
                 [str(ENV_PYTHON), "-m", "playwright", "install", "chromium"])

        if not (ROOT / "frontend/dist/index.html").is_file():
            npm = shutil.which("npm")
            if not npm:
                print("Built frontend missing. Install Node.js and rerun this setup script.")
                return 1
            step("Installing frontend build dependencies…", [npm, "ci", "--no-audit", "--no-fund"], ROOT / "frontend")
            step("Building the frontend…", [npm, "run", "build"], ROOT / "frontend")

        # Check imports using exactly the interpreter that run.py will use.
        modules = "fastapi, uvicorn, yt_dlp, httpx, selectolax, pydantic"
        if not args.basic:
            modules += ", playwright"
        step("Checking the installed Python dependencies…", [str(ENV_PYTHON), "-c", "import " + modules])
        if shutil.which("ffmpeg"):
            print("ffmpeg found: separate video/audio streams can be merged.")
        else:
            print("\nffmpeg is not installed. Combined video/audio downloads still work.")
            if shutil.which("pacman"):
                print("For full quality support, install it with: sudo pacman -S ffmpeg")
            elif shutil.which("apt"):
                print("For full quality support, install it with: sudo apt install ffmpeg")
            elif sys.platform == "darwin":
                print("For full quality support, install ffmpeg (Homebrew: brew install ffmpeg).")
            else:
                print("For full quality support, install ffmpeg and add its bin directory to PATH.")
        print("\nSetup complete. Start the app anytime with:\n  python run.py")
        print("You do not need to activate .venv or reinstall dependencies each time.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"\nSetup stopped because a step failed (exit {exc.returncode}).")
        print("Check the error above, then rerun python setup_app.py" + (" --basic" if args.basic else ""))
        print("Browser installation errors may require OS libraries; see README.md for Playwright system dependencies.")
        return 1
    except OSError as exc:
        print(f"\nSetup could not finish: {exc}")
        print("Check Python/venv support, network access, and project write permissions, then rerun setup.")
        return 1
    except KeyboardInterrupt:
        print("\nSetup interrupted. Rerun the same setup command when ready.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
