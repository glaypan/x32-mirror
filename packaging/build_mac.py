"""Build a native macOS .app on a Mac with PyInstaller (10.15+).

    python3 packaging/build_mac.py --arch x86_64
    python3 packaging/build_mac.py --arch universal2 # Intel + Apple Silicon

NOTE: PyInstaller bundles the build host's libraries, so the result requires
the macOS version it was built on (10.15+) - NOT suitable for 10.14 Mojave.
For the release artifact use packaging/build_mac_portable.py, which ships a
portable CPython runtime targeting macOS 10.9 and can be assembled anywhere.

Outputs dist/x32-mirror-<ver>-macos-<arch>.zip containing x32-mirror.app.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")


def version() -> str:
    with open(os.path.join(ROOT, "x32mirror", "__init__.py"), encoding="utf-8") as fh:
        return re.search(r'__version__\s*=\s*"([^"]+)"', fh.read()).group(1)


def build(arch: str) -> str:
    app = os.path.join(DIST, "x32-mirror.app")
    if os.path.isdir(app):
        shutil.rmtree(app)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--noupx",
        "--name", "x32-mirror",
        "--osx-bundle-identifier", "com.glaypan.x32mirror",
        "--target-arch", arch,
        "--collect-submodules", "webview",
        "--hidden-import", "webview.platforms.cocoa",
        "--distpath", DIST,
        "--workpath", os.path.join(ROOT, "build", "mac"),
        "--specpath", os.path.join(ROOT, "build", "mac"),
        os.path.join(ROOT, "packaging", "launcher.py"),
    ]
    print("[*] " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)

    macos_dir = os.path.join(app, "Contents", "MacOS")
    for f in ("config.json", "config-demo.json"):
        shutil.copy2(os.path.join(ROOT, f), os.path.join(macos_dir, f))
    shutil.copy2(os.path.join(ROOT, "packaging", "README-mac.txt"),
                 os.path.join(macos_dir, "使用说明.txt"))
    return app


def smoke(app: str) -> None:
    exe = os.path.join(app, "Contents", "MacOS", "x32-mirror")
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=90)
    print("[*] --version ->", (out.stdout or out.stderr).strip(), "rc", out.returncode)
    if out.returncode != 0:
        raise SystemExit("smoke test failed")
    # show the deployment target so 10.14 users know what they get
    try:
        info = subprocess.run(["otool", "-l", exe], capture_output=True, text=True).stdout
        for line in info.splitlines():
            if "minos" in line or "version" in line and "10." in line:
                print("   ", line.strip())
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arch", default="x86_64", choices=["x86_64", "arm64", "universal2"])
    args = ap.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("macOS builds must run on a Mac (PyInstaller is not a cross-compiler)")
    ver = version()
    app = build(args.arch)
    smoke(app)
    out = os.path.join(DIST, f"x32-mirror-{ver}-macos-{args.arch}.zip")
    if os.path.exists(out):
        os.remove(out)
    subprocess.run(["ditto", "-c", "-k", "--keepParent", app, out], check=True)
    size = os.path.getsize(out) / (1024 * 1024)
    print(f"[+] {out} ({size:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
