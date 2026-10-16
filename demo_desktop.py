"""Launch the macOS-style desktop UI with the local demo mocks.

Self-contained: starts two mock consoles (10023/10024) if they are not
running yet, then opens the pywebview window with config-demo.json.
"""
import os
import subprocess
import sys
import time

ROOT = r"E:\AI\workbuddy\x32\x32-mirror"
PY = r"C:\Python314\python.exe"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import socket  # noqa: E402


def port_open(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.6)
    try:
        s.sendto(b"/xinfo\0\0\0", ("127.0.0.1", port))
        s.recvfrom(256)
        return True
    except OSError:
        return False
    finally:
        s.close()


if not port_open(10023):
    print("starting mock consoles...")
    subprocess.Popen([PY, os.path.join(ROOT, "demo_mocks.py")],
                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    for _ in range(20):
        time.sleep(0.3)
        if port_open(10023):
            break
print("mocks up; opening desktop UI...")
from x32mirror.desktop import run_desktop  # noqa: E402
import json  # noqa: E402

with open(os.path.join(ROOT, "config-demo.json"), encoding="utf-8") as fh:
    cfg = json.load(fh)
sys.exit(run_desktop(cfg, os.path.join(ROOT, "config-demo.json")))
