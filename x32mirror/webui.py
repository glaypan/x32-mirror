"""Mobile-friendly web console: control the mirror from any phone browser.

    python -m x32mirror web --http-port 8080

Open  http://<this-pc-ip>:8080  on Android / iPhone. Pure stdlib:
ThreadingHTTPServer (worker thread) + a single-page app; engine runs in
the asyncio loop of this process. No third-party packages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import cloud
from .desktop_page import DESKTOP_PAGE
from .drivers import DRIVERS, get_driver
from .engine import MirrorEngine, restore_snapshot
from .helptext import HELP_CAUTION, HELP_FAQ, HELP_USAGE
from .ha import send_ha_command

log = logging.getLogger("x32mirror.web")

SNAP_DIR = "snapshots"


# ---------------------------------------------------------------- log ring
class RingHandler(logging.Handler):
    def __init__(self, maxlen=800):
        super().__init__()
        self.buf = deque(maxlen=maxlen)
        self.seq = 0
        self._lock = threading.Lock()

    def emit(self, record):
        with self._lock:
            self.seq += 1
            self.buf.append({
                "seq": self.seq,
                "ts": time.strftime("%H:%M:%S", time.localtime(record.created)),
                "lvl": record.levelname[:4],
                "msg": record.getMessage(),
            })

    def after(self, n):
        with self._lock:
            return [r for r in self.buf if r["seq"] > n]


# ---------------------------------------------------------------- engine mgr
class EngineManager:
    """Owns the MirrorEngine; safe to call from HTTP worker threads."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.engine: MirrorEngine | None = None
        self.transport = None
        self.running_cfg: dict | None = None
        self.last_error: str | None = None
        self._lock = threading.Lock()

    # -- coroutines on the loop side ---------------------------------
    async def _start(self, cfg: dict):
        if self.engine is not None:
            return
        loop = asyncio.get_running_loop()
        try:
            eng = MirrorEngine(cfg)
            transport, _ = await loop.create_datagram_endpoint(
                lambda: eng,
                local_addr=(cfg.get("listen_host", "0.0.0.0"),
                            int(cfg.get("listen_port", 10099))))
            await eng.start()
            self.engine, self.transport = eng, transport
            self.running_cfg = cfg
            log.info("engine started via web (listen :%s)", cfg.get("listen_port", 10099))
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            log.error("engine start failed: %s", exc)
            raise

    async def _stop(self):
        if self.engine is None:
            return
        try:
            await self.engine.stop()
            self.transport.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("engine stop error: %s", exc)
        finally:
            self.engine, self.transport = None, None
        log.info("engine stopped via web")

    async def _temp_snapshot(self, cfg: dict, wait: float = 3.0) -> dict:
        """Read console state with a temporary engine (mirror not running)."""
        loop = asyncio.get_running_loop()
        cfg = dict(cfg)
        cfg["listen_port"] = int(cfg.get("listen_port", 10099)) + 60
        eng = MirrorEngine(cfg)
        transport, _ = await loop.create_datagram_endpoint(
            lambda: eng, local_addr=(cfg.get("listen_host", "0.0.0.0"), cfg["listen_port"]))
        await eng.start()
        await asyncio.sleep(wait)
        snap = eng.snapshot_dict()
        await eng.stop()
        transport.close()
        return snap

    # -- thread-side API ----------------------------------------------
    def start(self, cfg: dict):
        with self._lock:
            if self.engine is not None:
                return {"ok": True, "already": True}
            self.last_error = None
            fut = asyncio.run_coroutine_threadsafe(self._start(cfg), self.loop)
            try:
                fut.result(timeout=10)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}
            return {"ok": True}

    def stop(self):
        with self._lock:
            if self.engine is None:
                return {"ok": True, "already": True}
            fut = asyncio.run_coroutine_threadsafe(self._stop(), self.loop)
            fut.result(timeout=10)
            return {"ok": True}

    def status(self) -> dict:
        eng = self.engine
        out = {"running": eng is not None, "error": self.last_error}
        if eng:
            detail = eng.status_dict()
            def con_info(c):
                age = None if c.last_seen is None else round(time.time() - c.last_seen, 1)
                return {"name": c.name, "host": c.host, "port": c.port, "age_s": age}
            cons = detail["consoles"]
            out.update({
                "active": bool(eng.active),
                "role": "单机" if not eng.ha else ("主机" if eng.active else "备机"),
                "ha": eng.ha is not None,
                "listen_port": self.running_cfg.get("listen_port") if self.running_cfg else None,
                "direction": eng.direction,
                "sync_mode": eng.sync_mode,
                "master": eng.master,
                "xinfo": eng.xinfo,
                "stats": detail["stats"],
                "latency_ms": detail["latency_ms"],
                "clients": len(eng.clients),
                "consoles": [{
                    "name": c["name"], "host": c["host"], "port": c["port"],
                    "age_s": c["last_seen_age_s"], "last_seen_age_s": c["last_seen_age_s"],
                    "online": c["online"], "alert": c["alert"],
                } for c in cons],
                "state_paths": len(eng.state),
                "sync_paths": detail["sync_paths"],
                "drivers": [detail["driver_a"], detail["driver_b"]],
                "sync_delay_s": detail.get("sync_delay_s", 0),
                "pending_delay": detail.get("pending_delay", 0),
                "pending_revert": detail.get("pending_revert", 0),
                "paused": detail.get("paused", False),
                "sync_job": detail.get("sync_job"),
                "last_align": detail.get("last_align"),
                "recent_ops": detail.get("recent_ops", []),
            })
        return out

    # -- sync mode (single / mirror / independent) ----------------------
    async def _set_mode(self, mode: str, master: str):
        eng = self.engine
        if eng is None:
            return {"ok": False, "error": "引擎未运行"}
        return eng.set_mode(mode, master)

    def set_mode(self, mode: str, master: str) -> dict:
        """Switch sync mode at runtime; False when the engine is not running
        (the caller then persists the choice to the config file instead)."""
        with self._lock:
            if self.engine is None:
                return {"ok": False, "not_running": True}
            fut = asyncio.run_coroutine_threadsafe(self._set_mode(mode, master), self.loop)
            try:
                return fut.result(timeout=10)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

    # -- safety check / pause -------------------------------------------
    def job_info(self) -> dict:
        """Current (or last) alignment job, polled by the progress dialog."""
        eng = self.engine
        if eng is None:
            return {"running": False, "job": None, "paused": False}
        return {"running": True, "paused": bool(eng.paused),
                "job": eng.job.dict() if eng.job else None,
                "last_align": eng.last_align}

    def cancel_align(self) -> dict:
        with self._lock:
            eng = self.engine
            if eng is None:
                return {"ok": False, "not_running": True}

            async def _go():
                return eng.cancel_align()

            fut = asyncio.run_coroutine_threadsafe(_go(), self.loop)
            try:
                return fut.result(timeout=5)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

    def set_paused(self, value: bool) -> dict:
        with self._lock:
            eng = self.engine
            if eng is None:
                return {"ok": False, "not_running": True}

            async def _go():
                return eng.set_paused(value)

            fut = asyncio.run_coroutine_threadsafe(_go(), self.loop)
            try:
                return fut.result(timeout=5)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

    def ha_info(self) -> dict:
        """HA role/epoch/peer snapshot for the UI (empty when disabled)."""
        eng = self.engine
        ha = getattr(eng, "ha", None) if eng else None
        if ha is None:
            return {"enabled": False}
        peer = getattr(ha, "_peer", None)
        return {
            "enabled": True,
            "node_id": getattr(ha, "node_id", None),
            "peer_host": getattr(ha, "peer_host", None),
            "port": getattr(ha, "port", None),
            "active": bool(getattr(ha, "active", False)),
            "epoch": int(getattr(ha, "epoch", 0) or 0),
            "peer": peer,
        }

    def snapshot_now(self, cfg: dict, wait: float = 3.0) -> dict:
        """Thread-safe: snapshot from the running engine, or read via a temp engine."""
        eng = self.engine
        if eng is not None and eng.state:
            fut = asyncio.run_coroutine_threadsafe(asyncio.sleep(0), self.loop)
            fut.result(timeout=2)
            snap = eng.snapshot_dict()
        else:
            fut = asyncio.run_coroutine_threadsafe(self._temp_snapshot(cfg, wait), self.loop)
            snap = fut.result(timeout=wait + 15)
        os.makedirs(SNAP_DIR, exist_ok=True)
        name = f"snapshot-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path = os.path.join(SNAP_DIR, name)
        with open(path, "wb") as fh:
            fh.write(cloud.snapshot_bytes(snap))
        return {"file": name, "paths": len(snap.get("paths") or {}),
                "ts": snap.get("ts"), "model": snap.get("model")}

    def restore(self, cfg: dict, name: str, confirm: bool) -> dict:
        path = os.path.join(SNAP_DIR, os.path.basename(name))
        if not os.path.exists(path):
            return {"ok": False, "error": f"快照不存在: {name}"}
        with open(path, "rb") as fh:
            snap = cloud.load_snapshot(fh.read())
        paths = snap.get("paths") or {}
        info = {"ok": True, "confirm": confirm, "file": name,
                "ts": snap.get("ts"), "model": snap.get("model"), "paths": len(paths)}
        if not confirm:
            info["preview"] = {p: paths[p] for p in sorted(paths)[:12]}
            return info

        # restore_snapshot is blocking (rate-limited writes); run in executor
        async def _job():
            return await asyncio.get_running_loop().run_in_executor(
                None, restore_snapshot, cfg, snap)
        fut = asyncio.run_coroutine_threadsafe(_job(), self.loop)
        n = fut.result(timeout=120)
        info["written"] = n
        return info


# ---------------------------------------------------------------- HTTP
class WebApp:
    def __init__(self, cfg: dict, config_path: str, http_port: int = 8080,
                 host: str = "0.0.0.0"):
        self.cfg = cfg
        self.config_path = os.path.abspath(config_path)
        self.http_port = http_port
        self.http_host = host
        self.loop = asyncio.get_running_loop()
        self.mgr = EngineManager(self.loop)
        self.ring = RingHandler()
        logging.getLogger().addHandler(self.ring)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ---- config helpers (phone can edit console IPs) -----------------
    def _save_cfg(self, new_cfg: dict):
        keep = dict(self.cfg)
        for k, v in new_cfg.items():
            if k == "consoles" and isinstance(v, dict):
                # deep-merge: a partial console update must not drop the
                # other side's settings or the untouched fields
                cons = dict(keep.get("consoles") or {})
                for side, cc in v.items():
                    if isinstance(cc, dict):
                        cons[side] = {**cons.get(side, {}), **cc}
                    else:
                        cons[side] = cc
                keep["consoles"] = cons
            else:
                keep[k] = v
        self.cfg = keep
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh, indent=2, ensure_ascii=False)

    def start_http(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # quiet default access log
                log.debug("http %s", fmt % args)

            def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj, code=200):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

            def do_GET(self):
                path = self.path.split("?")[0]
                if path in ("/", "/index.html"):
                    self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/desktop":
                    self._send(200, DESKTOP_PAGE.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/api/status":
                    self._json(app.mgr.status())
                elif path == "/api/logs":
                    try:
                        after = int(self.path.split("after=")[-1])
                    except ValueError:
                        after = 0
                    self._json({"logs": app.ring.after(after), "seq": app.ring.seq})
                elif path == "/api/snapshots":
                    files = sorted(os.listdir(SNAP_DIR), reverse=True) \
                        if os.path.isdir(SNAP_DIR) else []
                    self._json({"files": files})
                elif path.startswith("/api/snapshot/"):
                    name = os.path.basename(path[len("/api/snapshot/"):])
                    fp = os.path.join(SNAP_DIR, name)
                    if os.path.exists(fp):
                        with open(fp, "rb") as fh:
                            self._send(200, fh.read(), "application/json; charset=utf-8")
                    else:
                        self._json({"error": "not found"}, 404)
                elif path == "/api/config":
                    c = dict(app.cfg)
                    self._json({"config": c, "drivers": ["auto"] + sorted(DRIVERS.keys())})
                elif path.startswith("/api/detect"):
                    from urllib.parse import parse_qs, urlparse
                    q = parse_qs(urlparse(self.path).query)
                    host = (q.get("host") or [""])[0].strip()
                    if host:
                        from .drivers import detect_console_sync
                        key, model, port = detect_console_sync(host, 2.5)
                        self._json({"host": host, "driver": key, "model": model, "port": port})
                    else:
                        self._json({"error": "host query parameter required"}, 400)
                elif path == "/api/docs":
                    self._json({"usage": HELP_USAGE, "caution": HELP_CAUTION, "faq": HELP_FAQ})
                elif path == "/api/ha":
                    self._json(app.mgr.ha_info())
                elif path == "/api/job":
                    self._json(app.mgr.job_info())
                elif path == "/api/mode":
                    eng = app.mgr.engine
                    if eng is None:
                        c = app.cfg
                        self._json({
                            "running": False,
                            "sync_mode": c.get("sync_mode", "mirror"),
                            "master": c.get("master", "a"),
                            "direction": c.get("direction", "both"),
                            "revert_delay_s": c.get("revert_delay_s", 0.5),
                        })
                    else:
                        self._json({
                            "running": True,
                            "sync_mode": eng.sync_mode,
                            "master": eng.master,
                            "direction": eng.direction,
                            "revert_delay_s": eng.revert_delay,
                        })
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                path = self.path.split("?")[0]
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                except Exception:  # noqa: BLE001
                    body = {}

                if path == "/api/start":
                    cfg = dict(app.cfg)
                    for k in ("listen_port", "direction", "full_sync", "sync_delay_s",
                              "sync_mode", "master", "revert_delay_s"):
                        if k in body:
                            cfg[k] = body[k]
                    for side in ("a", "b"):
                        cc = body.get(side)
                        if cc:
                            cfg["consoles"][side].update(cc)
                    self._json(app.mgr.start(cfg))
                elif path == "/api/stop":
                    self._json(app.mgr.stop())
                elif path == "/api/snapshot":
                    try:
                        self._json({"ok": True, **app.mgr.snapshot_now(app.cfg)})
                    except Exception as exc:  # noqa: BLE001
                        self._json({"ok": False, "error": str(exc)}, 500)
                elif path == "/api/restore":
                    try:
                        self._json(app.mgr.restore(app.cfg, body.get("file", ""),
                                                   bool(body.get("confirm"))))
                    except Exception as exc:  # noqa: BLE001
                        self._json({"ok": False, "error": str(exc)}, 500)
                elif path == "/api/config":
                    try:
                        app._save_cfg(body)
                        self._json({"ok": True})
                    except Exception as exc:  # noqa: BLE001
                        self._json({"ok": False, "error": str(exc)}, 500)
                elif path == "/api/ha":
                    action = str(body.get("action") or "status")
                    ha_cfg = dict(app.cfg.get("ha") or {})
                    port = int(ha_cfg.get("port") or 49900)
                    host = ha_cfg.get("peer_host") or "127.0.0.1"
                    ack = send_ha_command(host, port, action)
                    if ack is None:
                        self._json({"ok": False,
                                    "error": f"HA 节点无应答（{host}:{port}）。"
                                             "确认本节点已启用双机热备并正在运行。"})
                    else:
                        self._json({"ok": True, "ack": ack})
                elif path == "/api/job/cancel":
                    self._json(app.mgr.cancel_align())
                elif path == "/api/pause":
                    self._json(app.mgr.set_paused(bool(body.get("paused"))))
                elif path == "/api/mode":
                    mode = str(body.get("mode") or "").strip()
                    master = str(body.get("master") or "").strip()
                    if mode not in ("single", "mirror", "independent"):
                        self._json({"ok": False, "error": f"未知同步模式: {mode!r}"})
                    elif master not in ("a", "b"):
                        self._json({"ok": False, "error": f"未知主机: {master!r}"})
                    else:
                        r = app.mgr.set_mode(mode, master)
                        if r.get("not_running"):
                            # not running: persist the choice, it applies on
                            # the next start
                            app._save_cfg({"sync_mode": mode, "master": master})
                            self._json({"ok": True, "saved": True,
                                        "sync_mode": mode, "master": master})
                        else:
                            self._json(r)
                else:
                    self._json({"error": "not found"}, 404)

        self._httpd = ThreadingHTTPServer((self.http_host, self.http_port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True, name="x32mirror-web")
        self._thread.start()
        log.warning("web console: http://%s:%s  (open this address in any phone browser)",
                    _local_ip(), self.http_port)

    def stop_http(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None


def _local_ip() -> str:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------- page
PAGE = """<!DOCTYPE html>
<html lang="zh"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>x32-mirror 调音台同步</title>
<style>
:root{--bg:#f5f6f8;--card:#fff;--ink:#222;--mut:#777;--grn:#1a7f37;--red:#c62828;--amb:#9a6700;--line:#e4e6ea}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink);font-size:15px}
header{background:#1c2536;color:#fff;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:5}
header b{font-size:16px}
.dot{width:10px;height:10px;border-radius:50%;background:#888;display:inline-block;margin-right:6px}
.dot.on{background:#4caf50;box-shadow:0 0 6px #4caf50}.dot.off{background:#9e9e9e}.dot.err{background:#e53935}
main{padding:12px;max-width:720px;margin:0 auto;padding-bottom:76px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
.card h3{font-size:14px;color:var(--mut);margin-bottom:10px;font-weight:600}
.row{display:flex;gap:10px}.row>*{flex:1;min-width:0}
label{font-size:12px;color:var(--mut);display:block;margin:8px 0 4px}
input,select{width:100%;padding:10px;border:1px solid var(--line);border-radius:8px;font-size:15px;background:#fff}
button{width:100%;padding:12px;border:0;border-radius:10px;font-size:15px;font-weight:600;background:#2b5fd9;color:#fff;margin-top:10px}
button:active{opacity:.8}button.gray{background:#667}button.red{background:var(--red)}button.green{background:var(--grn)}
.kv{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed var(--line);font-size:14px}
.kv:last-child{border:0}.kv span:first-child{color:var(--mut)}
.stat{font-size:13px;color:var(--mut)}
pre#logs{background:#161b22;color:#c9d1d9;font:12px/1.6 Consolas,monospace;padding:10px;border-radius:10px;height:300px;overflow:auto;white-space:pre-wrap;word-break:break-all}
.doc{white-space:pre-wrap;font-size:14px;line-height:1.8}
.warn{background:#fff7e6;border:1px solid #f0d9a8;border-radius:10px;padding:10px;font-size:13px;color:#7a5b00;margin-bottom:10px}
nav{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid var(--line);display:flex;z-index:5}
nav button{background:none;color:var(--mut);font-size:12px;font-weight:500;padding:8px 0 10px;margin:0;border-radius:0}
nav button.on{color:#2b5fd9}
.hide{display:none}
.mono{font-family:Consolas,monospace;font-size:12px;color:#555;word-break:break-all}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;background:#eef}
.badge.g{background:#e6f4ea;color:var(--grn)}.badge.y{background:#fff3cd;color:var(--amb)}
</style></head><body>
<header><b>🎛 x32-mirror</b><span><span class="dot off" id="dot"></span><span id="headState" style="font-size:14px">未运行</span></span></header>
<main>

<div id="t-status">
  <div class="card">
    <h3>镜像状态</h3>
    <div id="stBody" class="stat">加载中…</div>
  </div>
  <div class="card">
    <h3>控制</h3>
    <button class="green" id="btnStart">▶ 启动镜像</button>
    <button class="red" id="btnStop" style="display:none">■ 停止镜像</button>
  </div>
</div>

<div id="t-config" class="hide">
  <div class="warn">改完点底部“保存配置”；启动镜像请回“状态”页操作。</div>
  <div class="card"><h3>调音台 A</h3>
    <label>IP 地址</label><input id="a_host" placeholder="192.168.1.100">
    <div class="row"><div><label>端口</label><input id="a_port" inputmode="numeric"></div>
    <div><label>型号</label><select id="a_drv"></select></div></div>
  </div>
  <div class="card"><h3>调音台 B</h3>
    <label>IP 地址</label><input id="b_host" placeholder="192.168.1.101">
    <div class="row"><div><label>端口</label><input id="b_port" inputmode="numeric"></div>
    <div><label>型号</label><select id="b_drv"></select></div></div>
  </div>
  <div class="card"><h3>运行选项</h3>
    <div class="row"><div><label>监听端口(遥控软件用)</label><input id="listen" inputmode="numeric"></div>
    <div><label>同步方向</label><select id="direction"><option>both</option><option>a_to_b</option><option>b_to_a</option></select></div></div>
    <div class="row"><div><label>同步模式</label><select id="syncmode"><option value="mirror">全镜像</option><option value="single">单控台</option><option value="independent">显示独立</option></select></div>
    <div><label>主机</label><select id="master"><option value="a">A</option><option value="b">B</option></select></div></div>
    <button id="btnCfg">💾 保存配置</button>
  </div>
</div>

<div id="t-snap" class="hide">
  <div class="warn">⚠ 恢复会覆盖两台调音台当前状态！先拍快照留还原点，恢复前务必先预览。</div>
  <div class="card"><h3>快照备份</h3>
    <button id="btnSnap">📸 立即拍摄快照</button>
    <div id="snapMsg" class="stat" style="margin-top:8px"></div>
  </div>
  <div class="card"><h3>恢复（写回两台调音台）</h3>
    <div id="snapList" class="stat">加载中…</div>
  </div>
</div>

<div id="t-log" class="hide">
  <div class="card"><h3>实时日志 <button class="gray" style="width:auto;padding:6px 14px;margin:0;font-size:12px" onclick="logSeq=0;document.getElementById('logs').textContent=''">清屏</button></h3>
  <pre id="logs"></pre></div>
</div>

<div id="t-help" class="hide">
  <div class="card"><h3>使用说明</h3><div class="doc" id="docUsage">…</div></div>
  <div class="card"><h3>⚠ 注意事项</h3><div class="doc" id="docCaution">…</div></div>
  <div class="card"><h3>常见问题</h3><div class="doc" id="docFaq">…</div></div>
</div>

</main>
<nav>
  <button data-t="t-status" class="on">状态</button>
  <button data-t="t-config">配置</button>
  <button data-t="t-snap">快照</button>
  <button data-t="t-log">日志</button>
  <button data-t="t-help">说明</button>
</nav>
<script>
let logSeq=0,docs=false;
const $=id=>document.getElementById(id);
function tab(btn){document.querySelectorAll('nav button').forEach(b=>b.classList.remove('on'));btn.classList.add('on');
 ['t-status','t-config','t-snap','t-log','t-help'].forEach(t=>$(t).classList.add('hide'));$(btn.dataset.t).classList.remove('hide');
 if(btn.dataset.t==='t-log')pollLogs();}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>tab(b));

async function jget(u){const r=await fetch(u);return r.json()}
async function jpost(u,d){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d||{})});return r.json()}

function age(a){return a==null?'无数据':(a<3?'● 在线':(a<15?'● 迟缓':'○ 失联'))+' ('+a+'s 前)'}

async function pollStatus(){
 try{
  const s=await jget('/api/status');
  const dot=$('dot');dot.className='dot '+(s.running?(s.active?'on':'off'):(s.error?'err':'off'));
  $('headState').textContent=s.running?(s.role+(s.active?' · 运行中':' · 待命')):(s.error?'启动出错':'未运行');
  let h;
  if(s.running){
   const c=s.consoles;
   h=`<div class="kv"><span>角色</span><b class="badge ${s.active?'g':'y'}">${s.role}${s.active?' (转发中)':' (只记录)'}</b></div>
      <div class="kv"><span>同步模式</span><span>${({single:'单控台',mirror:'全镜像',independent:'显示独立'})[s.sync_mode]||s.sync_mode} · 主机 ${(s.master||'a').toUpperCase()}</span></div>
      <div class="kv"><span>调音台 A</span><span>${c[0].host}:${c[0].port} ${age(c[0].age_s)}</span></div>
      <div class="kv"><span>调音台 B</span><span>${c[1].host}:${c[1].port} ${age(c[1].age_s)}</span></div>
      <div class="kv"><span>方向 / 遥控端</span><span>${s.direction} / ${s.clients} 个在线</span></div>
      <div class="kv"><span>收到 / 转发 / 抑制回声</span><span>${s.stats.received||0} / ${s.stats.forwarded||0} / ${s.stats.echo_suppressed||0}</span></div>`;
   $('btnStart').style.display='none';$('btnStop').style.display='block';
  }else{
   h=s.error?`<div class="kv"><span>上次错误</span><span class="mono">${s.error}</span></div>`:'镜像未运行。先到“配置”页确认两台调音台 IP，再点下方启动。';
   $('btnStart').style.display='block';$('btnStop').style.display='none';
  }
  $('stBody').innerHTML=h;
 }catch(e){$('headState').textContent='无法连接';}
 setTimeout(pollStatus,2000);
}

async function pollLogs(){
 if($('t-log').classList.contains('hide')&&document.querySelector('nav button.on').dataset.t!=='t-log'){
   setTimeout(pollLogs,2000);return;}
 try{
  const d=await jget('/api/logs?after='+logSeq);
  if(d.logs.length){const el=$('logs');el.textContent+=d.logs.map(l=>`[${l.ts}] ${l.lvl} ${l.msg}`).join('\\n')+'\\n';el.scrollTop=el.scrollHeight;logSeq=d.seq;}
 }catch(e){}
 setTimeout(pollLogs,1500);
}

$('btnStart').onclick=async()=>{$('btnStart').disabled=true;const r=await jpost('/api/start');if(!r.ok)alert('启动失败：'+r.error);$('btnStart').disabled=false;pollStatus();};
$('btnStop').onclick=async()=>{if(!confirm('确定停止镜像同步？两台调音台将各自独立运行。'))return;await jpost('/api/stop');pollStatus();};

async function loadConfig(){
 const d=await jget('/api/config');const c=d.config;
 const sel=(el,v)=>{el.innerHTML=d.drivers.map(k=>`<option ${k===v?'selected':''}>${k}</option>`).join('')};
 sel($('a_drv'),c.consoles.a.driver||'x32');sel($('b_drv'),c.consoles.b.driver||'x32');
 $('a_host').value=c.consoles.a.host||'';$('a_port').value=c.consoles.a.port||10023;
 $('b_host').value=c.consoles.b.host||'';$('b_port').value=c.consoles.b.port||10023;
 $('listen').value=c.listen_port||10099;$('direction').value=c.direction||'both';
 $('syncmode').value=c.sync_mode||'mirror';$('master').value=c.master||'a';
}
$('btnCfg').onclick=async()=>{
 const body={consoles:{a:{host:$('a_host').value.trim(),port:+$('a_port').value||10023,driver:$('a_drv').value},
                          b:{host:$('b_host').value.trim(),port:+$('b_port').value||10023,driver:$('b_drv').value}},
             listen_port:+$('listen').value||10099,direction:$('direction').value,
             sync_mode:$('syncmode').value,master:$('master').value};
 const r=await jpost('/api/config',body);alert(r.ok?'配置已保存':'保存失败：'+r.error);
};

async function loadSnaps(){
 const d=await jget('/api/snapshots');
 $('snapList').innerHTML=d.files.length?d.files.map(f=>
  `<div class="kv"><span class="mono">${f}</span><span><button class="gray" style="width:auto;padding:6px 12px;margin:0 4px 0 0;font-size:12px" onclick="doRestore('${f}',false)">预览</button><button style="width:auto;padding:6px 12px;margin:0;font-size:12px" onclick="doRestore('${f}',true)">写台</button></span></div>`).join(''):'暂无快照，先点上方“立即拍摄快照”。';
}
$('btnSnap').onclick=async()=>{
 $('btnSnap').disabled=true;$('snapMsg').textContent='正在读取调音台状态…';
 const r=await jpost('/api/snapshot');
 $('snapMsg').textContent=r.ok?`已保存 ${r.file}（${r.paths} 个参数）`:'失败：'+r.error;
 $('btnSnap').disabled=false;loadSnaps();};
async function doRestore(f,confirm){
 if(confirm&&!window.confirm('⚠ 将把快照 '+f+' 写回两台调音台，覆盖当前状态！\\n确定继续？'))return;
 const r=await jpost('/api/restore',{file:f,confirm:confirm});
 if(!r.ok){alert('失败：'+r.error);return;}
 if(!confirm){alert('预览（干跑）：共 '+r.paths+' 个参数，未写台。\\n确认无误后再点“写台”。');}
 else{alert('恢复完成：'+r.written+' 个参数已写回两台调音台。');}
}

async function loadDocs(){
 if(docs)return;docs=true;
 const d=await jget('/api/docs');
 $('docUsage').textContent=d.usage;$('docCaution').textContent=d.caution;$('docFaq').textContent=d.faq;
}
['t-config','t-snap','t-help'].forEach((t,i)=>{
 const obs=new MutationObserver(()=>{const vis=!$(t).classList.contains('hide');
  if(vis&&t==='t-config')loadConfig();if(vis&&t==='t-snap')loadSnaps();if(vis&&t==='t-help')loadDocs();});
 obs.observe($(t),{attributes:true});
});

pollStatus();pollLogs();
</script></body></html>"""
