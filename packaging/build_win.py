"""Build the Windows portable bundle and zip it.

    .build-venv\\Scripts\\python.exe packaging\\build_win.py

Outputs:
    build\\pkg\\x32-mirror-<ver>-win64\\      (unzip-and-run folder)
    dist\\x32-mirror-<ver>-win64.zip          (release asset)

The bundle contains the PyInstaller onedir build plus the config templates,
a short Chinese readme and a demo launcher - no Python installation needed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(ROOT)
BUILD = os.path.join(WORKSPACE, "build", "win")
APP_DIR = os.path.join(BUILD, "app")
PKG_DIR = os.path.join(BUILD, "pkg")
DIST = os.path.join(WORKSPACE, "dist")

DEMO_BAT = """@echo off
rem 无硬件演示：启动两台模拟调音台并打开界面
cd /d "%~dp0"
start "" "x32-mirror.exe" --demo
"""


def version() -> str:
    with open(os.path.join(ROOT, "x32mirror", "__init__.py"), encoding="utf-8") as fh:
        return re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)


def run_pyinstaller() -> None:
    launcher = os.path.join(ROOT, "packaging", "launcher.py")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--noupx",
        "--name", "x32-mirror",
        "--distpath", APP_DIR,
        "--workpath", os.path.join(BUILD, "work"),
        "--specpath", BUILD,
        "--collect-submodules", "webview",
        "--hidden-import", "webview.platforms.edgechromium",
        "--hidden-import", "webview.platforms.winforms",
        "--hidden-import", "clr_loader",
        "--hidden-import", "pythonnet",
        "--exclude-module", "pytest",
        "--exclude-module", "numpy",
        launcher,
    ]
    print("[*] " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def assemble(ver: str) -> str:
    src = os.path.join(APP_DIR, "x32-mirror")
    if not os.path.isdir(src):
        raise SystemExit(f"PyInstaller output missing: {src}")
    name = f"x32-mirror-{ver}-win64"
    pkg = os.path.join(PKG_DIR, name)
    if os.path.isdir(pkg):
        shutil.rmtree(pkg)
    shutil.copytree(src, pkg)

    for f in ("config.json", "config-demo.json", "LICENSE"):
        shutil.copy2(os.path.join(ROOT, f), os.path.join(pkg, f))
    shutil.copy2(os.path.join(ROOT, "packaging", "README-win.txt"),
                 os.path.join(pkg, "使用说明.txt"))
    with open(os.path.join(pkg, "演示模式.bat"), "w", encoding="gbk") as fh:
        fh.write(DEMO_BAT)
    return pkg


def zip_pkg(pkg: str, ver: str) -> str:
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f"x32-mirror-{ver}-win64.zip")
    if os.path.exists(out):
        os.remove(out)
    root = os.path.basename(pkg)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, _dirs, files in os.walk(pkg):
            for f in files:
                fp = os.path.join(base, f)
                arc = os.path.join(root, os.path.relpath(fp, pkg))
                z.write(fp, arc)
    size = os.path.getsize(out) / (1024 * 1024)
    with zipfile.ZipFile(out) as z:
        bad = z.testzip()
        print(f"[+] {out}  ({size:.1f} MB, {len(z.namelist())} entries, "
              f"integrity {'OK' if bad is None else 'BAD ' + str(bad)})")
    return out


def main() -> int:
    ver = version()
    if os.path.isdir(APP_DIR):
        shutil.rmtree(APP_DIR)
    run_pyinstaller()
    pkg = assemble(ver)
    zip_pkg(pkg, ver)
    print(f"[+] folder: {pkg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
