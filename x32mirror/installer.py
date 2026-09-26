"""One-click command-line installer for x32-mirror.

What "install" does (no third-party packages needed - the tool is stdlib only):

  1. Creates an `x32mirror` command shim inside the project folder and adds
     the folder to the USER PATH, so `x32mirror` works in any new terminal.
     Running it with no arguments opens the desktop GUI.
  2. Creates desktop shortcuts (GUI launcher; plus a web-console launcher).
  3. With --autostart (Windows): registers a Startup-folder shortcut that
     silently runs mirror + phone web console at login (pythonw, no window).

`uninstall` removes everything above. Nothing outside the user profile is
touched (no admin rights required).

Usage:
    python -m x32mirror install [--autostart] [--web-port 8080] [--dry-run]
    python -m x32mirror uninstall
"""

import os
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
IS_WIN = platform.system() == "Windows"
SHORTCUT_PREFIX = "X32-Mirror"
SHIM_NAME = "x32mirror.cmd" if IS_WIN else "x32mirror"


def _log(msg: str) -> None:
    print(f"  {msg}")


def _desktop_dirs():
    home = Path.home()
    dirs = [home / "Desktop", home / "OneDrive" / "Desktop"]
    return [d for d in dirs if d.is_dir()]


def _startup_dir():
    if not IS_WIN:
        return None
    d = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / \
        "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return d if d.is_dir() else None


# ---- Windows user PATH (HKCU\Environment) ------------------------------

def _read_user_path():
    if not IS_WIN:
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            val, _ = winreg.QueryValueEx(k, "Path")
            return val or ""
    except OSError:
        return ""


def _write_user_path(new_value: str) -> bool:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ, new_value)
    try:  # make running shells pick it up (best effort)
        import ctypes

        HWND_BROADCAST, WM_SETTINGCHANGE = 0xFFFF, 0x001A
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 1000, None)
    except Exception:  # noqa: BLE001
        pass
    return True


def _path_contains(entry: str) -> bool:
    cur = _read_user_path()
    return any(p.strip().lower() == entry.lower() for p in cur.split(";"))


def _add_to_user_path(entry: str):
    if _path_contains(entry):
        _log(f"PATH 已包含项目目录，跳过: {entry}")
        return False
    cur = _read_user_path()
    new = (cur.rstrip(";") + ";" if cur.strip() else "") + entry
    _write_user_path(new)
    _log(f"已加入用户 PATH: {entry}（新开的终端生效）")
    return True


def _remove_from_user_path(entry: str) -> bool:
    cur = _read_user_path()
    parts = [p for p in cur.split(";") if p.strip().lower() != entry.lower()]
    new = ";".join(parts)
    if new == cur:
        return False
    _write_user_path(new)
    return True


# ---- shortcuts ----------------------------------------------------------

def _ps_make_shortcut(lnk: Path, target: str, args: str, workdir: str) -> bool:
    """Create a .lnk via PowerShell (ASCII-only script; args passed safely)."""
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$sc = $ws.CreateShortcut('{lnk}'); "
        f"$sc.TargetPath = '{target}'; "
        f"$sc.Arguments = '{args}'; "
        f"$sc.WorkingDirectory = '{workdir}'; "
        "$sc.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            check=True, capture_output=True, timeout=30)
        return lnk.exists()
    except Exception as exc:  # noqa: BLE001
        _log(f"(warn) 创建快捷方式失败 {lnk.name}: {exc}")
        return False


def _shim_path() -> Path:
    return PROJECT_DIR / SHIM_NAME


def _write_shim(dry_run: bool):
    shim = _shim_path()
    py = sys.executable
    if IS_WIN:
        content = (
            "@echo off\r\n"
            f"cd /d \"{PROJECT_DIR}\"\r\n"
            f"\"{py}\" -m x32mirror %*\r\n"
        )
    else:
        content = (
            "#!/bin/bash\n"
            f"cd \"{PROJECT_DIR}\" || exit 1\n"
            f"exec \"{py}\" -m x32mirror \"$@\"\n"
        )
    if dry_run:
        _log(f"(dry-run) 将写入命令行入口: {shim}")
        return
    shim.write_text(content, encoding="utf-8")
    if not IS_WIN:
        shim.chmod(0o755)
    _log(f"命令行入口已创建: {shim}")


def _desktop_shortcuts(autostart: bool, web_port: int, dry_run: bool):
    """Return list of created shortcut paths."""
    py = sys.executable
    created = []

    if IS_WIN:
        targets = [
            (f"{SHORTCUT_PREFIX} GUI.lnk", py, "-m x32mirror"),
            (f"{SHORTCUT_PREFIX} Web.lnk", py, f"-m x32mirror web --autostart --http-port {web_port}"),
        ]
        for name, target, args in targets:
            for desk in _desktop_dirs():
                lnk = desk / name
                if dry_run:
                    _log(f"(dry-run) 将创建桌面快捷方式: {lnk}")
                    created.append(str(lnk))
                    continue
                if _ps_make_shortcut(lnk, target, args, str(PROJECT_DIR)):
                    created.append(str(lnk))
                    _log(f"桌面快捷方式已创建: {name}")
                break  # one desktop is enough
        if autostart:
            sd = _startup_dir()
            if sd:
                pythonw = Path(py).with_name("pythonw.exe")
                pythonw = pythonw if pythonw.exists() else Path(py)
                lnk = sd / f"{SHORTCUT_PREFIX} Autostart.lnk"
                if dry_run:
                    _log(f"(dry-run) 将创建登录自启: {lnk}")
                    created.append(str(lnk))
                elif _ps_make_shortcut(lnk, str(pythonw),
                                       f"-m x32mirror web --autostart --http-port {web_port}",
                                       str(PROJECT_DIR)):
                    created.append(str(lnk))
                    _log(f"登录自启已注册（开机后台运行镜像+手机控制台）: {lnk}")
            else:
                _log("(warn) 未找到 Startup 文件夹，跳过自启")
    else:
        # macOS: drop a double-clickable .command on the Desktop
        for desk in _desktop_dirs():
            lnk = desk / f"{SHORTCUT_PREFIX}.command"
            content = ("#!/bin/bash\n"
                       f"cd \"{PROJECT_DIR}\" || exit 1\n"
                       f"exec \"{py}\" -m x32mirror\n")
            if dry_run:
                _log(f"(dry-run) 将创建桌面启动器: {lnk}")
            else:
                lnk.write_text(content, encoding="utf-8")
                lnk.chmod(0o755)
                _log(f"桌面启动器已创建（双击即开 GUI）: {lnk}")
            created.append(str(lnk))
            break
        if autostart:
            _log("macOS 登录自启请在 系统偏好设置 → 用户与群组 → 登录项 中手动添加"
                 f" {PROJECT_DIR / 'x32mirror'}（无窗口后台可用 nohup 跑 web 模式）")

    return created


# ---- public API ---------------------------------------------------------

def install(autostart: bool = False, web_port: int = 8080, dry_run: bool = False) -> bool:
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"== x32-mirror 一键安装 ({'Windows' if IS_WIN else platform.system()}) ==")
    print(f"  项目目录: {PROJECT_DIR}")
    print(f"  Python:   {py_ver} ({sys.executable})")

    try:
        import tkinter  # noqa: F401
        _log("tkinter 检测: OK（GUI 可用）")
    except ImportError:
        _log("(warn) 当前 Python 缺少 tkinter：GUI 不可用，命令行/web 功能不受影响")

    print("[1/3] 命令行入口")
    _write_shim(dry_run)
    print("[2/3] 用户 PATH")
    if dry_run:
        _log(f"(dry-run) 将把 {PROJECT_DIR} 加入用户 PATH")
    else:
        _add_to_user_path(str(PROJECT_DIR))
    print("[3/3] 桌面快捷方式" + (" + 登录自启" if autostart else ""))
    _desktop_shortcuts(autostart, web_port, dry_run)

    print()
    print("安装完成。使用方式：")
    print("  · 任意新终端直接运行:  x32mirror            （弹出图形界面）")
    print("  ·                       x32mirror web --autostart   （镜像+手机控制台）")
    print("  ·                       x32mirror --help            （全部命令）")
    if IS_WIN:
        print("  注：PATH 对已打开的终端不生效，重开一个终端（或重新登录）即可。")
    print(f"卸载: python -m x32mirror uninstall")
    return True


def uninstall() -> None:
    print("== x32-mirror 卸载 ==")
    removed = []

    shim = _shim_path()
    if shim.exists():
        shim.unlink()
        removed.append(f"命令行入口 {shim}")

    if IS_WIN and _remove_from_user_path(str(PROJECT_DIR)):
        removed.append("用户 PATH 中的项目目录")

    targets = [f"{SHORTCUT_PREFIX} GUI.lnk", f"{SHORTCUT_PREFIX} Web.lnk",
               f"{SHORTCUT_PREFIX} Autostart.lnk", f"{SHORTCUT_PREFIX}.command"]
    for desk in _desktop_dirs() + ([_startup_dir()] if _startup_dir() else []):
        for name in targets:
            p = desk / name
            if p.exists():
                p.unlink()
                removed.append(str(p))

    if removed:
        for r in removed:
            print(f"  已移除: {r}")
    else:
        print("  未发现已安装的组件。")
    print("项目文件保留在原目录，可随时重新 install。")
