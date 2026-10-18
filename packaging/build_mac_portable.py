"""Build a macOS .app that runs on macOS 10.14.6 (Mojave) without Python.

PyInstaller cannot do this from modern build hosts: it bundles the host's
system libraries (Homebrew sqlite/lzma/tk are built for the runner's macOS,
so the result needs 10.15+).  Instead we ship a **portable CPython runtime**
whose x86_64 slice targets macOS 10.9, plus pure/universal2 wheels for
pywebview/pyobjc (x86_64 slices also 10.9), and a small shell launcher.

Runs on any OS (no Mac required) - it only downloads and assembles files.

    python packaging/build_mac_portable.py

Output: dist/x32-mirror-<ver>-macos-x86_64.zip
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(ROOT)
BUILD = os.path.join(WORKSPACE, "build", "mac-portable")
DIST = os.path.join(WORKSPACE, "dist")

# 20230726 is the last release whose x86_64 macOS builds target 10.9.
# (Later builds target 10.15+, which would exclude Mojave.)
PBS_TAG = "20230726"
PY_VER = "3.11.4"
RUNTIME = f"cpython-{PY_VER}+{PBS_TAG}-x86_64-apple-darwin-install_only.tar.gz"
RUNTIME_URL = (f"https://github.com/astral-sh/python-build-standalone/releases/download/"
               f"{PBS_TAG}/{RUNTIME}")

WHEELS = [
    "pywebview==5.4",
    "pyobjc-core==11.1",
    "pyobjc-framework-Cocoa==11.1",
    "pyobjc-framework-WebKit==11.1",
    "pyobjc-framework-Quartz==11.1",
    "bottle==0.13.4",
    "typing_extensions>=4.0",
]

MAC_BOOT = '''\
"""Portable macOS entry point (not frozen: runs on the bundled runtime)."""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def base_dir():
    base = os.path.expanduser("~/Library/Application Support/x32-mirror")
    os.makedirs(base, exist_ok=True)
    for name in ("config.json", "config-demo.json"):
        dst = os.path.join(base, name)
        src = os.path.join(HERE, name)
        if not os.path.exists(dst) and os.path.exists(src):
            shutil.copy2(src, dst)
    return base


def run_demo():
    import asyncio
    import threading

    from x32mirror.desktop import run_desktop
    from x32mirror.simulator import MockX32

    async def mocks():
        a = MockX32("模拟台-A", "127.0.0.1", 10023)
        b = MockX32("模拟台-B", "127.0.0.1", 10024)
        await asyncio.gather(a.start(), b.start(), a.auto_move(2.0), b.auto_move(2.5))

    def worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(mocks())

    threading.Thread(target=worker, daemon=True, name="demo-mocks").start()
    cfg_path = os.path.join(base_dir(), "config-demo.json")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    return run_desktop(cfg, cfg_path)


def main():
    os.chdir(base_dir())
    argv = sys.argv[1:]
    if "--demo" in argv:
        return run_demo()
    from x32mirror.__main__ import main as cli
    cli(argv or ["gui"])


if __name__ == "__main__":
    sys.exit(main() or 0)
'''

LAUNCHER = '''#!/bin/bash
# x32-mirror launcher: run the bundled CPython + the app next to it.
DIR="$(cd "$(dirname "$0")" && pwd)"
RES="$DIR/../Resources"
export PYTHONHOME="$RES/python"
export PYTHONPATH="$RES/app:$RES/python/lib/python3.11/site-packages"
exec "$RES/python/bin/python3.11" "$RES/app/mac_boot.py" "$@"
'''

INFO_PLIST = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>x32-mirror</string>
  <key>CFBundleDisplayName</key><string>x32-mirror 调音台同步</string>
  <key>CFBundleIdentifier</key><string>com.glaypan.x32mirror</string>
  <key>CFBundleExecutable</key><string>x32-mirror</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleSignature</key><string>????</string>
  <key>CFBundleShortVersionString</key><string>{ver}</string>
  <key>CFBundleVersion</key><string>{ver}</string>
  <key>LSMinimumSystemVersion</key><string>10.14</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.music</string>
</dict>
</plist>
'''

DEMO_CMD = '''#!/bin/bash
cd "$(dirname "$0")"
./x32-mirror.app/Contents/MacOS/x32-mirror --demo
'''


def version() -> str:
    with open(os.path.join(ROOT, "x32mirror", "__init__.py"), encoding="utf-8") as fh:
        return re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)


def fetch(url: str, dest: str) -> None:
    if os.path.exists(dest):
        print("[=] cached", os.path.basename(dest))
        return
    print("[*] downloading", url, flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "x32-mirror-build"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def extract_runtime(tar_path: str, dest: str) -> None:
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    links = []
    with tarfile.open(tar_path) as t:
        for m in t.getmembers():
            target = os.path.join(dest, m.name)
            if m.isdir():
                os.makedirs(target, exist_ok=True)
            elif m.isfile():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                src = t.extractfile(m)
                with open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
            elif m.issym():
                links.append((m.name, m.linkname))
    # Windows cannot create symlinks reliably: copy the linked file instead
    for name, link in links:
        src = os.path.normpath(os.path.join(os.path.dirname(name), link))
        dst = os.path.join(dest, name)
        src_abs = os.path.join(dest, src)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isfile(src_abs):
            shutil.copy2(src_abs, dst)
        elif os.path.isdir(src_abs):
            shutil.copytree(src_abs, dst, dirs_exist_ok=True)


def ensure_site(site: str) -> None:
    if os.path.isdir(os.path.join(site, "webview")):
        print("[=] site-packages cached")
        return
    os.makedirs(site, exist_ok=True)
    cmd = [sys.executable, "-m", "pip", "install", "--target", site,
           "--platform", "macosx_10_9_x86_64", "--python-version", "3.11",
           "--implementation", "cp", "--abi", "cp311", "--only-binary=:all:",
           "--no-deps", "--upgrade", *WHEELS]
    print("[*] fetching macOS wheels")
    subprocess.run(cmd, check=True)

    # proxy_tools is sdist-only; it is a single pure-python module tree
    tmp = os.path.join(BUILD, "wheels")
    os.makedirs(tmp, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "download", "proxy_tools",
                    "--no-binary=:all:", "--no-deps", "-d", tmp], check=True)
    pkg = os.path.join(tmp, "proxy_tools-0.1.0.tar.gz")
    with tarfile.open(pkg) as t:
        for m in t.getmembers():
            if m.name.startswith("proxy_tools-0.1.0/proxy_tools/"):
                m.name = m.name.replace("proxy_tools-0.1.0/", "", 1)
                t.extract(m, site)


def app_tree(ver: str, runtime: str, site: str) -> str:
    name = f"x32-mirror-{ver}-macos-x86_64"
    pkg = os.path.join(BUILD, "pkg", name)
    if os.path.isdir(pkg):
        shutil.rmtree(pkg)
    app = os.path.join(pkg, "x32-mirror.app")
    contents = os.path.join(app, "Contents")
    macos = os.path.join(contents, "MacOS")
    res = os.path.join(contents, "Resources")
    os.makedirs(macos)
    os.makedirs(os.path.join(res, "app"))

    with open(os.path.join(contents, "Info.plist"), "w", encoding="utf-8") as fh:
        fh.write(INFO_PLIST.format(ver=ver))

    launcher = os.path.join(macos, "x32-mirror")
    with open(launcher, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(LAUNCHER)
    os.chmod(launcher, 0o755)

    shutil.copytree(os.path.join(runtime, "python"), os.path.join(res, "python"))
    shutil.copytree(site, os.path.join(res, "python", "lib", "python3.11", "site-packages"),
                    dirs_exist_ok=True)

    appdir = os.path.join(res, "app")
    shutil.copytree(os.path.join(ROOT, "x32mirror"), os.path.join(appdir, "x32mirror"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    with open(os.path.join(appdir, "mac_boot.py"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(MAC_BOOT)
    for f in ("config.json", "config-demo.json"):
        shutil.copy2(os.path.join(ROOT, f), os.path.join(appdir, f))
    shutil.copy2(os.path.join(ROOT, "packaging", "README-mac.txt"),
                 os.path.join(pkg, "使用说明.txt"))

    demo = os.path.join(pkg, "演示模式.command")
    with open(demo, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(DEMO_CMD)
    os.chmod(demo, 0o755)
    return pkg


def zip_tree(pkg: str, ver: str) -> str:
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f"x32-mirror-{ver}-macos-x86_64.zip")
    if os.path.exists(out):
        os.remove(out)
    root = os.path.basename(pkg)
    exec_names = {"x32-mirror", "python3.11", "python3", "python", "演示模式.command"}

    def put(z, path, arc):
        st = os.stat(path)
        mode = 0o755 if (os.path.basename(path) in exec_names
                         or st.st_mode & stat.S_IXUSR) else 0o644
        if os.path.isdir(path):
            zi = zipfile.ZipInfo(arc + "/", (2026, 10, 19, 0, 0, 0))
            zi.external_attr = (0o40000 | 0o755) << 16
            zi.compress_type = zipfile.ZIP_STORED
            z.writestr(zi, b"")
            return
        zi = zipfile.ZipInfo(arc, (2026, 10, 19, 0, 0, 0))
        zi.external_attr = (0o100000 | mode) << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        with open(path, "rb") as fh:
            z.writestr(zi, fh.read())

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, dirs, files in os.walk(pkg):
            rel = os.path.relpath(base, pkg)
            arcbase = root if rel == "." else os.path.join(root, rel)
            if rel != ".":
                put(z, base, arcbase)
            for f in files:
                put(z, os.path.join(base, f), os.path.join(arcbase, f))
    size = os.path.getsize(out) / (1024 * 1024)
    with zipfile.ZipFile(out) as z:
        bad = z.testzip()
        print(f"[+] {out} ({size:.1f} MB, {len(z.namelist())} entries, "
              f"integrity {'OK' if bad is None else 'BAD'})")
    return out


def main() -> int:
    os.makedirs(BUILD, exist_ok=True)
    tar = os.path.join(BUILD, RUNTIME)
    fetch(RUNTIME_URL, tar)
    runtime = os.path.join(BUILD, "runtime")
    if not os.path.isdir(runtime):
        print("[*] extracting runtime")
        extract_runtime(tar, runtime)
    site = os.path.join(BUILD, "site")
    ensure_site(site)
    ver = version()
    pkg = app_tree(ver, runtime, site)
    zip_tree(pkg, ver)
    print("[+] folder:", pkg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
