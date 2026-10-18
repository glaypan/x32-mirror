"""Frozen-app entry point (used by PyInstaller, also runs from source).

    x32-mirror.exe                -> desktop UI (double-click friendly)
    x32-mirror.exe --demo         -> two mock consoles + UI, no hardware needed
    x32-mirror.exe run|web|...    -> the normal CLI (a console is allocated)

The working directory is pinned to the folder that contains the exe so
config.json / snapshots/ / oplog.sqlite live next to the executable no
matter how it was launched (shortcut, file explorer, scheduled task).
"""

from __future__ import annotations

import ctypes
import json
import os
import sys


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_console() -> None:
    """Windowed builds have no stdout; CLI commands get a console window."""
    if os.name != "nt" or sys.stdout is not None:
        return
    try:
        if not ctypes.windll.kernel32.AllocConsole():
            return  # already attached (e.g. launched from a terminal)
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stdin = open("CONIN$", "r", encoding="utf-8")
    except Exception:  # noqa: BLE001 - never block startup for cosmetics
        pass


def _fatal(message: str) -> None:
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(0, message, "x32-mirror", 0x10)
            return
        except Exception:  # noqa: BLE001
            pass
    print(message, file=sys.stderr)


def _start_demo_mocks() -> None:
    """Two local mock consoles on 10023/10024 that keep moving faders."""
    import asyncio
    import threading

    from x32mirror.simulator import MockX32

    async def run():
        a = MockX32("模拟台-A", "127.0.0.1", 10023)
        b = MockX32("模拟台-B", "127.0.0.1", 10024)
        await asyncio.gather(a.start(), b.start(),
                             a.auto_move(2.0), b.auto_move(2.5))

    def worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run())

    threading.Thread(target=worker, daemon=True, name="x32mirror-demo-mocks").start()


def _run_demo(base: str) -> int:
    from x32mirror.desktop import run_desktop

    cfg_path = os.path.join(base, "config-demo.json")
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(base, "config.json")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    _start_demo_mocks()
    return run_desktop(cfg, cfg_path)


def main() -> int:
    base = _base_dir()
    os.chdir(base)

    argv = sys.argv[1:]
    if "--demo" in argv:
        return _run_demo(base)

    if argv:
        _ensure_console()

    from x32mirror.__main__ import main as cli_main

    cli_main(argv or ["gui"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - show it instead of vanishing
        import traceback

        _fatal("启动失败：\n\n" + traceback.format_exc(limit=6))
        raise
