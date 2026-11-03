from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

PORT = int(os.environ.get("PKM_PORT", "8787"))
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"

BROWSERS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]


def health_info_at(port: int) -> dict | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://{HOST}:{port}/api/health", timeout=1.5) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def health_info() -> dict | None:
    return health_info_at(PORT)


def health() -> bool:
    return health_info() is not None


def same_vault(info: dict | None, expected: Path) -> bool:
    if not info or not info.get("vault_path"):
        return False
    try:
        actual = Path(str(info["vault_path"])).resolve()
        return os.path.normcase(str(actual)) == os.path.normcase(str(expected.resolve()))
    except OSError:
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


def choose_port(preferred: int | None, expected_vault: Path) -> int:
    if preferred:
        info = health_info_at(preferred)
        if info and same_vault(info, expected_vault):
            return preferred
        if not info and port_free(preferred):
            return preferred
        raise RuntimeError(f"端口 {preferred} 已被其他程序占用")
    candidate = PORT
    for _ in range(30):
        info = health_info_at(candidate)
        if info and same_vault(info, expected_vault):
            return candidate
        if not info and port_free(candidate):
            return candidate
        candidate += 1
    raise RuntimeError("找不到可用端口")


def wait_ready(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if health():
            return True
        time.sleep(0.3)
    return False


def browser_path() -> Path | None:
    return next((path for path in BROWSERS if path.exists()), None)


def open_window() -> subprocess.Popen | None:
    browser = browser_path()
    if browser is None:
        webbrowser.open(URL)
        return None
    profile = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AtlasPKM" / "browser"
    profile.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [
            str(browser),
            f"--app={URL}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1440,980",
        ]
    )


def asset_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


def rebuild_wiki() -> None:
    try:
        request = urllib.request.Request(f"{URL}/api/wiki/build", method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=30) as response:
            response.read()
    except Exception:
        pass


class Tray:
    """Small Windows tray icon using pywin32; no extra runtime dependency."""

    WM_TRAY = 0x0400 + 20
    MENU_OPEN = 1001
    MENU_REBUILD = 1002
    MENU_QUIT = 1003

    def __init__(self, on_quit, on_open=None) -> None:
        import win32con
        import win32gui

        self.win32con = win32con
        self.win32gui = win32gui
        self.on_quit = on_quit
        self.on_open = on_open or open_window
        self.nid = None
        wc = win32gui.WNDCLASS()
        wc.lpszClassName = "AtlasPKMTrayWindow"
        wc.lpfnWndProc = self._wndproc
        atom = win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindow(
            atom, "Atlas PKM", 0, 0, 0, 0, 0, 0, 0, 0, None
        )
        icon_path = asset_path("atlas.ico")
        if icon_path.exists():
            icon = win32gui.LoadImage(
                0,
                str(icon_path),
                win32con.IMAGE_ICON,
                0,
                0,
                win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE,
            )
        else:
            icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
        self.nid = (
            self.hwnd,
            0,
            win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
            self.WM_TRAY,
            icon,
            "Atlas PKM",
        )
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, self.nid)

    def _menu(self) -> None:
        win32con = self.win32con
        win32gui = self.win32gui
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, self.MENU_OPEN, "打开 Atlas")
        win32gui.AppendMenu(menu, win32con.MF_STRING, self.MENU_REBUILD, "重建 Wiki")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, None)
        win32gui.AppendMenu(menu, win32con.MF_STRING, self.MENU_QUIT, "退出 Atlas")
        x, y = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_LEFTALIGN | win32con.TPM_BOTTOMALIGN | win32con.TPM_RIGHTBUTTON,
            x,
            y,
            0,
            self.hwnd,
            None,
        )
        win32gui.PostMessage(self.hwnd, win32con.WM_NULL, 0, 0)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        win32con = self.win32con
        win32gui = self.win32gui
        if msg == self.WM_TRAY and lparam in (
            win32con.WM_LBUTTONUP,
            win32con.WM_RBUTTONUP,
        ):
            self._menu()
            return 0
        if msg == win32con.WM_COMMAND:
            if wparam == self.MENU_OPEN:
                threading.Thread(target=self.on_open, daemon=True).start()
            elif wparam == self.MENU_REBUILD:
                threading.Thread(target=rebuild_wiki, daemon=True).start()
            elif wparam == self.MENU_QUIT:
                self.close()
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def close(self) -> None:
        if self.nid:
            self.win32gui.Shell_NotifyIcon(self.win32gui.NIM_DELETE, self.nid)
            self.nid = None
        self.on_quit()
        self.win32gui.DestroyWindow(self.hwnd)

    def run(self) -> None:
        self.win32gui.PumpMessages()


def serve() -> None:
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")


def _setup_streams() -> Path | None:
    """Windowed builds have no stdout/stderr; redirect them to a local log."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    log_dir = root / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    stream = open(log_dir / "atlas.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = stream
    sys.stderr = stream
    return log_dir / "atlas.log"


def main() -> None:
    global PORT, URL
    if "--usage-login" in sys.argv:
        from app.usage_login import run as run_usage_login

        index = sys.argv.index("--usage-login")
        raise SystemExit(run_usage_login(sys.argv[index + 1:]))
    _setup_streams()
    # Create data/ and vault/ next to the executable before the UI opens.
    from app.config import settings

    settings.ensure()
    parser = argparse.ArgumentParser(description="Atlas PKM desktop launcher")
    parser.add_argument("--background", action="store_true", help="run without a window")
    parser.add_argument("--no-tray", action="store_true", help="disable the system tray")
    parser.add_argument("--edge", action="store_true", help="use the Edge app window instead of WebView2")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    try:
        PORT = choose_port(args.port, settings.default_vault)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return
    URL = f"http://{HOST}:{PORT}"

    if args.background:
        if health():
            print(f"AtlasPKM 已在运行：{URL}")
            return
        serve()
        return

    owns_server = not health()
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    if owns_server:
        config = uvicorn.Config(
            "app.main:app", host=HOST, port=PORT, log_level="info"
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True, name="pkm-uvicorn")
        thread.start()
        if not wait_ready():
            print(f"服务没有在预期时间内启动：{URL}", file=sys.stderr)
            if server:
                server.should_exit = True
            return

    native_started = False
    if not args.edge:
        try:
            import webview

            view = webview.create_window(
                "Atlas PKM",
                URL,
                width=1440,
                height=980,
                min_size=(960, 640),
                text_select=True,
            )
            tray = None
            if owns_server and not args.no_tray and server is not None:
                def quit_native() -> None:
                    server.should_exit = True
                    # WebView2 may keep its message loop alive after a
                    # cross-thread destroy; schedule a guaranteed exit first.
                    threading.Timer(1.5, lambda: os._exit(0)).start()
                    try:
                        view.destroy()
                    except Exception:
                        pass

                try:
                    tray = Tray(
                        on_quit=quit_native,
                        on_open=lambda: (view.show(), view.restore()),
                    )
                except Exception as exc:
                    print(f"系统托盘不可用：{exc}", file=sys.stderr)
            if tray is not None:
                threading.Thread(target=tray.run, daemon=True, name="pkm-tray").start()
            print(f"原生窗口已打开：{URL}")
            native_started = True
            webview.start()
        except Exception as exc:
            print(f"WebView2 不可用，回退到 Edge 窗口：{exc}", file=sys.stderr)
            native_started = False

    if not native_started:
        window = open_window()
        tray = None
        if owns_server and not args.no_tray and server is not None:
            try:
                tray = Tray(lambda: setattr(server, "should_exit", True))
            except Exception as exc:
                print(f"系统托盘不可用：{exc}", file=sys.stderr)
        try:
            if owns_server:
                # The Edge app process can exit immediately while its window stays open.
                # Keep the local server alive until the tray asks to quit.
                print(f"窗口已打开：{URL}")
                if tray is not None:
                    print("托盘菜单可打开窗口、重建 Wiki 或退出。")
                    tray.run()
                else:
                    while thread is not None and thread.is_alive():
                        time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    if owns_server and server is not None:
        server.should_exit = True
        if thread is not None:
            thread.join(timeout=8)


if __name__ == "__main__":
    main()

