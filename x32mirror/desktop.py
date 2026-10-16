"""macOS-style desktop shell: a native window (pywebview) around /desktop.

    python -m x32mirror gui            # new UI (falls back to tkinter)
    python -m x32mirror gui --classic  # force the classic tkinter UI

The page itself is pure HTML/CSS/JS served by webui.py on 127.0.0.1 only.
pywebview renders it in a real OS window (WKWebView on macOS, WebView2 on
Windows) so we get vibrancy/backdrop-filter, system fonts and dark mode
for free. If pywebview is missing we fall back to the system browser, and
`gui` falls back to the tkinter UI when neither is available.

Window chrome: frameless on macOS (CSS traffic lights, rounded corners,
window drag via -webkit-app-region). Windows keeps the native frame
(frameless resizing is unreliable there).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading

from .webui import WebApp

log = logging.getLogger("x32mirror.desktop")

DESKTOP_PORT = int(os.environ.get("X32MIRROR_DESKTOP_PORT", "10199"))


class _Api:
    """JS-callable window controls (traffic lights in the page).

    pywebview >=5: pass an object via create_window(js_api=...); its public
    methods become window.pywebview.api.* in the page.
    """

    def __init__(self):
        self._win = None  # bound right after create_window

    def _bind(self, window):
        self._win = window

    def close(self):
        if self._win:
            self._win.destroy()

    def minimize(self):
        if self._win:
            self._win.minimize()

    def toggle_maximize(self):
        if not self._win:
            return
        try:
            if self._win.fullscreen:
                self._win.restore()
            else:
                self._win.toggle_fullscreen()
        except Exception:  # noqa: BLE001
            pass


def _run_web(cfg: dict, config_path: str, port: int, ready: threading.Event,
             stop: threading.Event):
    """asyncio loop thread: own the WebApp (engine + HTTP API)."""

    async def main():
        app = WebApp(cfg, config_path, http_port=port, host="127.0.0.1")
        app.start_http()
        ready.set()
        try:
            while not stop.is_set():
                await asyncio.sleep(0.25)
        finally:
            await asyncio.sleep(0)  # let pending callbacks drain
            app.stop_http()

    asyncio.run(main())


def run_desktop(cfg: dict, config_path: str = "config.json",
                port: int = DESKTOP_PORT) -> int:
    """Open the macOS-style UI in a native window. Returns process exit code."""
    try:
        import webview  # pywebview
    except ImportError:
        print("未安装 pywebview，无法打开桌面窗口。")
        print("安装后重试：  pip install pywebview")
        print("或改用浏览器访问 http://127.0.0.1:%d/desktop" % port)
        return 2

    ready = threading.Event()
    stop = threading.Event()
    threading.Thread(target=_run_web, args=(cfg, config_path, port, ready, stop),
                     daemon=True, name="x32mirror-desktop-web").start()
    if not ready.wait(timeout=10):
        print("本地服务启动失败（端口 %d 可能被占用，可用 X32MIRROR_DESKTOP_PORT 更换）" % port)
        return 3

    url = "http://127.0.0.1:%d/desktop" % port
    frameless = sys.platform == "darwin"
    api = _Api()
    try:
        window = webview.create_window(
            "x32-mirror 调音台同步",
            url,
            width=1160, height=780, min_size=(940, 620),
            frameless=frameless,
            easy_drag=True,          # drag the page background to move window
            text_select=False,
            js_api=api,
        )
        api._bind(window)
        webview.start()
    except Exception as exc:  # noqa: BLE001
        log.error("pywebview failed: %s", exc)
        print("原生窗口打开失败：%s" % exc)
        print("可改用浏览器访问 %s" % url)
        return 4
    finally:
        stop.set()
    return 0


def open_in_browser(cfg: dict, config_path: str = "config.json",
                    port: int = DESKTOP_PORT) -> int:
    """No pywebview: serve the page and open it in the default browser."""
    import webbrowser

    ready = threading.Event()
    stop = threading.Event()
    threading.Thread(target=_run_web, args=(cfg, config_path, port, ready, stop),
                     daemon=True, name="x32mirror-desktop-web").start()
    if not ready.wait(timeout=10):
        print("本地服务启动失败（端口 %d 可能被占用）" % port)
        return 3
    url = "http://127.0.0.1:%d/desktop" % port
    print("已在新界面打开：%s（关闭此命令行窗口即退出）" % url)
    webbrowser.open(url)
    try:
        while not stop.is_set():
            stop.wait(3600)
    except KeyboardInterrupt:
        pass
    return 0
