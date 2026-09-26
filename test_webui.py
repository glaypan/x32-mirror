"""E2E test for the web console: mocks + WebApp + full API walk."""
import asyncio
import json
import logging
import threading
import time
import urllib.request

logging.basicConfig(level=logging.INFO)  # match real CLI entry level

from x32mirror.simulator import MockX32
from x32mirror.webui import WebApp


def run_mocks(ready):
    async def main():
        a = MockX32("A", "127.0.0.1", 11023)
        b = MockX32("B", "127.0.0.1", 12023)
        await a.start()
        await b.start()
        ready.set()
        await asyncio.Event().wait()
    asyncio.run(main())


def http(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:18080" + path, method=method, data=data)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} on {method} {path}: {e.read().decode('utf-8')[:300]}")
        raise
    try:
        return json.loads(raw)
    except Exception:
        return raw.decode("utf-8")


def run_web(ready):
    async def main():
        cfg = {
            "listen_host": "127.0.0.1", "listen_port": 19099, "direction": "both",
            "full_sync": True, "full_sync_from": "a", "oplog_db": None,
            "consoles": {
                "a": {"name": "mock-A", "host": "127.0.0.1", "port": 11023, "driver": "x32"},
                "b": {"name": "mock-B", "host": "127.0.0.1", "port": 12023, "driver": "x32"},
            },
        }
        app = WebApp(cfg, "test-web-config.json", http_port=18080, host="127.0.0.1")
        app.start_http()
        ready.set()
        await asyncio.Event().wait()
        await app.mgr._stop()
        app.stop_http()
    asyncio.run(main())


t1 = threading.Thread(target=run_mocks, args=(threading.Event(),), daemon=True)
t1.start()
ready2 = threading.Event()
t2 = threading.Thread(target=run_web, args=(ready2,), daemon=True)
t2.start()
ready2.wait(5)
time.sleep(0.5)

results = {}

# 1. page served
page = http("GET", "/")
results["page"] = "x32-mirror" in page and "调音台" in page
print("1. web page served:", results["page"])

# 2. status before start
st = http("GET", "/api/status")
results["status_initial"] = st["running"] is False
print("2. initial status:", st)

# 3. start engine via API with console override
r = http("POST", "/api/start", {"a": {"host": "127.0.0.1", "port": 11023},
                                "b": {"host": "127.0.0.1", "port": 12023}})
results["start"] = r.get("ok") is True
print("3. start:", r)
time.sleep(5.5)  # full sync (1060 paths ~2.5s) + settle

# 4. status running + forwarding happened
st = http("GET", "/api/status")
results["running"] = st["running"] and st["stats"].get("forwarded", 0) > 100
print("4. running status:", st)

# 5. phone edits config
r = http("POST", "/api/config", {"consoles": {
    "a": {"host": "127.0.0.1", "port": 11023, "driver": "x32"},
    "b": {"host": "127.0.0.1", "port": 12023, "driver": "x32"}}})
results["config_save"] = r.get("ok") is True
print("5. config save:", r)

# 6. snapshot
r = http("POST", "/api/snapshot")
results["snapshot"] = r.get("ok") and r.get("paths", 0) > 100
print("6. snapshot:", r)
snapfile = r["file"]

# 7. snapshots list + download
lst = http("GET", "/api/snapshots")
raw = http("GET", "/api/snapshot/" + snapfile)
results["snap_list"] = snapfile in lst["files"] and "paths" in raw
print("7. snapshots list:", lst["files"][:2], "download ok:", "paths" in str(raw)[:100000])

# 8. restore dry-run
r = http("POST", "/api/restore", {"file": snapfile, "confirm": False})
results["restore_dry"] = r.get("ok") and r.get("paths", 0) > 100 and "preview" in r
print("8. restore dry:", {k: r[k] for k in ("ok", "paths", "file")})

# 9. restore confirm
r = http("POST", "/api/restore", {"file": snapfile, "confirm": True})
results["restore_confirm"] = r.get("ok") and r.get("written", 0) > 100
print("9. restore confirm:", r)

# 10. logs + docs
lg = http("GET", "/api/logs?after=0")
dc = http("GET", "/api/docs")
results["logs_docs"] = len(lg["logs"]) >= 3 and "usage" in dc and "caution" in dc and "faq" in dc
print("10. logs:", len(lg["logs"]), "entries; docs keys:", sorted(dc.keys()))

# 11. stop via API
r = http("POST", "/api/stop")
st = http("GET", "/api/status")
results["stop"] = r.get("ok") and st["running"] is False
print("11. stop:", r, "-> running:", st["running"])

ok = all(results.values())
print()
print("=== web console e2e report ===")
for k, v in results.items():
    print(f"  {k}: {'PASS' if v else 'FAIL'}")
print("result:", "PASS" if ok else "FAIL")
raise SystemExit(0 if ok else 1)
