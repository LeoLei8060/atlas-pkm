from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PKM_PORT", "8787"))
URL = f"http://127.0.0.1:{PORT}"

BROWSERS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]


def wait_ready(timeout: float = 30.0) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with opener.open(f"{URL}/api/health", timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main() -> None:
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=str(ROOT),
    )
    try:
        if not wait_ready():
            print("服务没有在预期时间内启动。请直接运行: python run.py")
            return
        browser = next((path for path in BROWSERS if path.exists()), None)
        if browser:
            subprocess.Popen(
                [str(browser), f"--app={URL}", "--window-size=1440,980"],
                cwd=str(ROOT),
            )
        else:
            webbrowser.open(URL)
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if server.poll() is None:
            server.terminate()


if __name__ == "__main__":
    main()
