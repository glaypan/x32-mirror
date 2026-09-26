"""Core mirror engine: listens for state changes from the consoles and
replicates operations between them in real time.

Key mechanisms (aligned with the design doc):
- /renew heartbeat keeps both consoles broadcasting changes to us
- echo suppression: writes we performed are recognised when the target
  console broadcasts them back, so no forwarding loops occur
- LSN-style append-only op-log (SQLite, WAL) before forwarding
"""

import asyncio
import logging
import random
import sqlite3
import sys
import time

from .drivers import get_driver
from .mapping import MAP_FAMILY, PairMap
from .osc import decode_osc, encode_message

log = logging.getLogger("x32mirror")

MGMT_PATHS = {"/xinfo", "/renew", "/status", "/ping"}


def harden_udp_socket(transport):
    """Windows: stop WSAECONNRESET from poisoning UDP sockets.

    A previous send to a port that has gone away (console rebooted, peer
    offline) makes Windows report ConnectionReset on the socket and the
    proactor transport STOPS READING permanently (socket goes deaf while
    still being able to send). Disabling SIO_UDP_CONNRESET makes the
    socket behave like a normal connectionless UDP socket.

    The correct control code is 0x9800000C (verified empirically; the
    textbook _WSAIOW(IOC_VENDOR,12) derivations all fail with
    WSAEOPNOTSUPP). Python's socket.ioctl() whitelists only a few control
    codes, so we call WSAIoctl directly via ctypes. No-op on other
    platforms.
    """
    if sys.platform != "win32":
        return
    try:
        sock = transport.get_extra_info("socket")
        if sock is None:
            return
        import ctypes

        SIO_UDP_CONNRESET = 0x9800000C
        wsaioctl = ctypes.WinDLL("ws2_32").WSAIoctl
        wsaioctl.argtypes = [
            ctypes.c_size_t,                      # SOCKET
            ctypes.c_uint32,                      # dwIoControlCode
            ctypes.c_void_p,                      # lpvInBuffer
            ctypes.c_uint32,                      # cbInBuffer
            ctypes.c_void_p,                      # lpvOutBuffer
            ctypes.c_uint32,                      # cbOutBuffer
            ctypes.POINTER(ctypes.c_uint32),      # lpcbBytesReturned
            ctypes.c_void_p,                      # LPWSAOVERLAPPED
            ctypes.c_void_p,                      # completion routine
        ]
        arg = ctypes.c_uint32(0)  # FALSE = disable CONNRESET reporting
        returned = ctypes.c_uint32(0)
        wsaioctl(sock.fileno(), SIO_UDP_CONNRESET,
                 ctypes.byref(arg), ctypes.sizeof(arg),
                 None, 0, ctypes.byref(returned), None, None)
    except Exception as exc:  # noqa: BLE001
        log.debug("SIO_UDP_CONNRESET not applied: %s", exc)


def expand_sync_paths(extra=None):
    """Default full-sync path table (X32/M32 family)."""
    paths = get_driver("x32").sync_paths()
    for p in extra or []:
        if p not in paths:
            paths.append(p)
    return paths


class Console:
    def __init__(self, name: str, host: str, port: int):
        self.name = name
        self.host = host
        self.port = int(port)
        self.last_seen = None

    def __repr__(self):
        return f"<Console {self.name} {self.host}:{self.port}>"


class MirrorEngine(asyncio.DatagramProtocol):
    def __init__(self, cfg: dict):
        ca, cb = cfg["consoles"]["a"], cfg["consoles"]["b"]
        self.a = Console(ca.get("name", "A"), ca["host"], ca["port"])
        self.b = Console(cb.get("name", "B"), cb["host"], cb["port"])
        # driver "auto" = detect the model over the wire at start()
        self._auto_a = ca.get("driver", "x32") == "auto"
        self._auto_b = cb.get("driver", "x32") == "auto"
        self.drv_a = get_driver(ca.get("driver", "x32"))
        self.drv_b = get_driver(cb.get("driver", "x32"))
        self._extra_paths = list(cfg.get("extra_sync_paths") or [])
        self.full_sync_from = cfg.get("full_sync_from", "a")
        self._rebuild_topology()
        if self.drv_a.key != self.drv_b.key:
            if self.pairmap_ab:
                log.info("cross-family pair %s <-> %s: value/path mapping enabled", self.drv_a.key, self.drv_b.key)
            else:
                log.warning(
                    "cross-brand pair (%s <-> %s): no parameter mapping available, "
                    "forwarding will pass through untranslated and is likely meaningless",
                    self.drv_a.key, self.drv_b.key,
                )
        self.direction = cfg.get("direction", "both")
        self.echo_window = float(cfg.get("echo_window_s", 1.0))
        self.renew_interval = float(cfg.get("renew_interval_s", 5.0))
        self.coalesce_window = float(cfg.get("coalesce_window_s", 0.12))
        self.reconcile_interval = float(cfg.get("reconcile_interval_s", 3600.0))
        self.link_timeout = float(cfg.get("link_timeout_s", 15.0))
        self.oplog_db = cfg.get("oplog_db")
        self.full_sync = bool(cfg.get("full_sync", False))

        self.transport = None
        self._recent_writes = []  # (mono_ts, host, path, args)
        self._opbuf = []
        self._db = None
        self._tasks = []
        self._fs_task = None
        self._stop = asyncio.Event()
        self.stats = {"received": 0, "forwarded": 0, "echo_suppressed": 0}
        if self.oplog_db:
            self._init_db()

        # hot-standby coordination (two PCs sharing one mirror pair)
        ha_cfg = cfg.get("ha") or {}
        self.ha = None
        self.active = True
        if ha_cfg.get("enabled"):
            from .ha import HANode
            self.ha = HANode(
                node_id=ha_cfg.get("node_id", "node-1"),
                peer_host=ha_cfg["peer_host"],
                port=int(ha_cfg.get("port", 49900)),
                local_port=int(ha_cfg.get("local_port", ha_cfg.get("port", 49900))),
                failover_s=float(ha_cfg.get("failover_s", 3.0)),
                auto_resume_s=float(ha_cfg.get("auto_resume_s", 30.0)),
                on_change=self.set_active,
            )
            self.active = False  # decided by election after first heartbeats

        # remote-client proxy (Mixing Station / X32-Edit / iPad apps connect
        # to THIS tool instead of a console and stay in sync with everything)
        proxy_cfg = cfg.get("proxy") or {}
        self.proxy_enabled = bool(proxy_cfg.get("enabled", True))
        self.max_clients = int(proxy_cfg.get("max_clients", 8))
        self.client_timeout_s = float(proxy_cfg.get("client_timeout_s", 60.0))
        self.clients = {}  # (host, port) -> last_seen (monotonic)

        # live state cache (fed by every console message) -> snapshot source
        self.state = {}
        # per-source view: reconcile diffs A vs B to detect silent divergence
        self.state_by_src = {"a": {}, "b": {}}
        self.state_src_ts = {"a": {}, "b": {}}  # monotonic, per path
        # coalescing: (dst_name, path) -> [latest_args, deadline, dst, sent_args]
        self._pending = {}
        self.link_alerted = {"a": False, "b": False}

        # cloud backup (periodic snapshot upload; see cloud.py)
        cloud_cfg = cfg.get("cloud") or {}
        self.cloud_cfg = cloud_cfg if cloud_cfg.get("enabled") else None

    # ---- lifecycle -------------------------------------------------
    def connection_made(self, transport):
        self.transport = transport
        harden_udp_socket(transport)

    def _rebuild_topology(self):
        """(Re)derive pairmaps and full-sync path table from current drivers."""
        fam_a, fam_b = MAP_FAMILY.get(self.drv_a.key), MAP_FAMILY.get(self.drv_b.key)
        self.pairmap_ab = PairMap(fam_a, fam_b) if fam_a and fam_b else None
        self.pairmap_ba = PairMap(fam_b, fam_a) if fam_a and fam_b else None
        src_drv = self.drv_a if self.full_sync_from == "a" else self.drv_b
        self.sync_paths = src_drv.sync_paths()
        for p in self._extra_paths:
            if p not in self.sync_paths:
                self.sync_paths.append(p)

    async def _autodetect(self):
        """Resolve driver:'auto' consoles by probing them over the wire."""
        from .drivers import detect_console
        changed = False
        for c, is_auto in ((self.a, self._auto_a), (self.b, self._auto_b)):
            if not is_auto:
                continue
            try:
                key, model, port = await detect_console(c.host, timeout=2.5, extra_ports=[c.port])
            except Exception as exc:  # noqa: BLE001
                log.warning("auto-detect %s failed: %s (falling back to x32)", c.host, exc)
                continue
            if key:
                log.warning("auto-detect %s: %s -> driver=%s port=%d", c.host, model, key, port)
                c.port = int(port)
                if c is self.a:
                    self.drv_a = get_driver(key)
                else:
                    self.drv_b = get_driver(key)
                changed = True
            else:
                log.warning("auto-detect %s: no OSC reply on configured/standard "
                            "ports (falling back to x32, port unchanged)", c.host)
        if changed:
            self._rebuild_topology()

    async def start(self):
        if self._auto_a or self._auto_b:
            await self._autodetect()
        if self.ha:
            await self.ha.start()
        for c, drv in ((self.a, self.drv_a), (self.b, self.drv_b)):
            if drv.transport == "osc-udp":
                self._send(c, "/xinfo", [])
                if drv.renew_path:
                    self._send(c, drv.renew_path, [])
        self._tasks = [
            asyncio.create_task(self._renew_loop()),
            asyncio.create_task(self._flush_loop()),
            asyncio.create_task(self._stat_loop()),
            asyncio.create_task(self._coalesce_loop()),
            asyncio.create_task(self._watch_loop()),
        ]
        if self.reconcile_interval > 0:
            self._tasks.append(asyncio.create_task(self._reconcile_loop()))
        if self.full_sync and not self.ha:
            # HA nodes must NOT full-sync before the election: a standby drops
            # replies, so the sync would be wasted. set_active(True) runs it.
            self._fs_task = asyncio.create_task(self._full_sync())
        if self.cloud_cfg:
            self._tasks.append(asyncio.create_task(self._cloud_loop()))

    def snapshot_dict(self) -> dict:
        """Current known state as a JSON-safe snapshot (blobs excluded)."""
        paths = {
            p: a for p, a in self.state.items()
            if a and not any(isinstance(v, (bytes, bytearray)) for v in a)
        }
        return {
            "ts": time.time(),
            "node": self.ha.node_id if self.ha else "node",
            "model": self.drv_a.key,
            "paths": paths,
        }

    async def _cloud_loop(self):
        interval_h = float(self.cloud_cfg.get("interval_hours", 6.0))
        if interval_h <= 0:
            return  # manual CLI uploads only
        while not self._stop.is_set():
            await asyncio.sleep(interval_h * 3600.0)
            if not self.active:
                continue  # standby node must not double-upload
            try:
                await self.upload_snapshot()
            except Exception as exc:  # noqa: BLE001
                log.warning("cloud snapshot upload failed: %s", exc)

    async def upload_snapshot(self):
        from . import cloud
        body = cloud.snapshot_bytes(self.snapshot_dict())
        node = self.ha.node_id if self.ha else "node"
        name = cloud.snapshot_name(node)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, cloud.upload, self.cloud_cfg, body, name)
        await loop.run_in_executor(None, cloud.upload, self.cloud_cfg, body, "latest.json")
        log.warning("cloud snapshot uploaded: %s (%d paths)", name, len(self.snapshot_dict()["paths"]))

    def set_active(self, value: bool):
        if value == self.active:
            return
        self.active = value
        if value:
            log.warning("HA: this node is now ACTIVE - forwarding enabled")
            for c, drv in ((self.a, self.drv_a), (self.b, self.drv_b)):
                if drv.renew_path:
                    self._send(c, drv.renew_path, [])
            if self.full_sync:
                # always re-align after becoming active: any sync that ran
                # while standby had its replies dropped, so the views may be
                # stale regardless of the previous task's state
                if self._fs_task and not self._fs_task.done():
                    self._fs_task.cancel()
                self._fs_task = asyncio.create_task(self._full_sync())
        else:
            log.warning("HA: this node is now STANDBY - forwarding disabled (still logging ops)")

    async def stop(self):
        self._stop.set()
        if self.ha:
            await self.ha.stop()
        for t in self._tasks:
            t.cancel()
        if self._fs_task:
            self._fs_task.cancel()
        try:
            self._flush_pending()  # deliver the final coalesced values
        except Exception:  # noqa: BLE001
            pass
        await self._flush_ops()
        if self._db:
            self._db.close()

    # ---- network ---------------------------------------------------
    def datagram_received(self, data: bytes, addr):
        try:
            for address, args in decode_osc(data):
                self._handle(address, args, addr)
        except Exception as exc:  # noqa: BLE001
            log.warning("bad datagram from %s: %s", addr, exc)

    def error_received(self, exc):
        log.warning("transport error: %s", exc)

    def _identify(self, addr):
        if (self.a.host, self.a.port) == addr:
            return self.a
        if (self.b.host, self.b.port) == addr:
            return self.b
        ips = [self.a.host, self.b.host]
        if ips.count(addr[0]) == 1:  # unique IP wins
            return self.a if self.a.host == addr[0] else self.b
        return None

    def _handle(self, address, args, addr):
        self.stats["received"] += 1
        src = self._identify(addr)
        if src is None:
            self._handle_client(address, args, addr)
            return
        src.last_seen = time.time()
        if address in MGMT_PATHS:
            return
        now = time.monotonic()
        self.state[address] = list(args)
        skey = "a" if src is self.a else "b"
        self.state_by_src[skey][address] = list(args)
        self.state_src_ts[skey][address] = now

        self._recent_writes = [
            r for r in self._recent_writes if now - r[0] < self.echo_window
        ]
        for ts, host, path, hargs in self._recent_writes:
            if host == src.host and path == address and self._args_match(hargs, args):
                self.stats["echo_suppressed"] += 1
                # echo round-trip = our write -> console broadcast back: a good
                # proxy for one-way sync latency
                self.stats["echo_ms_sum"] = self.stats.get("echo_ms_sum", 0.0) + (now - ts) * 1000.0
                self.stats["echo_n"] = self.stats.get("echo_n", 0) + 1
                return  # our own write echoed back by the console

        # relay console state to connected remote clients (read-only view)
        if self.clients:
            self._relay_to_clients(address, args)

        targets = []
        if self.active:
            if src is self.a and self.direction in ("both", "a_to_b"):
                targets = [self.b]
            elif src is self.b and self.direction in ("both", "b_to_a"):
                targets = [self.a]

        # record every observed change, active or standby - the standby
        # node's op-log IS the real-time backup on the second PC
        self._log_op(src.name, address, args)
        if not targets:
            return
        pairmap = self.pairmap_ba if src is self.b else self.pairmap_ab
        if pairmap:
            translated = pairmap.translate(address, args)
            if translated is None:
                self.stats["unmapped"] = self.stats.get("unmapped", 0) + 1
                log.debug("no mapping for %s from %s", address, src.name)
                return
            out_path, out_args = translated
        else:
            out_path, out_args = address, list(args)
        for dst in targets:
            if self.coalesce_window > 0 and len(out_args) == 1 and isinstance(out_args[0], float):
                self._coalesce_send(dst, out_path, out_args, now)
            else:
                self._dispatch(dst, out_path, out_args)

    # ---- dispatch / coalescing ----------------------------------------
    def _dispatch(self, dst: Console, path: str, args):
        """Write to a console immediately and record it for echo suppression."""
        self._send(dst, path, args)
        self._recent_writes.append((time.monotonic(), dst.host, path, list(args)))
        self.stats["forwarded"] += 1
        log.debug("-> %s %s %r", dst.name, path, args)

    def _coalesce_send(self, dst: Console, path: str, args, now: float):
        """Fader-style continuous streams: first value goes out at once
        (zero added latency), later values within the window collapse to a
        single trailing write of the latest value."""
        key = (dst.name, path)
        entry = self._pending.get(key)
        if entry is None:
            self._dispatch(dst, path, args)
            self._pending[key] = [list(args), now + self.coalesce_window, dst, list(args)]
        else:
            entry[0] = list(args)
            entry[1] = now + self.coalesce_window
            self.stats["coalesced"] = self.stats.get("coalesced", 0) + 1

    def _flush_pending(self):
        """Send the latest coalesced values (on window close / shutdown)."""
        now = time.monotonic()
        for (dname, path) in list(self._pending):
            entry = self._pending.pop((dname, path), None)
            if not entry:
                continue
            args, _, dst, sent = entry
            if args and not self._args_match(sent, args):
                self._dispatch(dst, path, args)

    async def _coalesce_loop(self):
        while not self._stop.is_set():
            await asyncio.sleep(0.03)
            now = time.monotonic()
            if any(now >= e[1] for e in self._pending.values()):
                self._flush_pending()

    # ---- remote client proxy ----------------------------------------
    def _handle_client(self, address, args, addr):
        """Serve an OSC remote app (Mixing Station / X32-Edit / iPad ...)."""
        if not self.proxy_enabled:
            return
        now = time.monotonic()
        if addr not in self.clients:
            if len(self.clients) >= self.max_clients:
                self.stats["clients_rejected"] = self.stats.get("clients_rejected", 0) + 1
                return
            log.info("remote client connected: %s:%s", *addr)
        self.clients[addr] = now

        if address in MGMT_PATHS:
            if address == "/xinfo":
                model = {"x32": "X32", "m32": "M32", "wing": "WING"}.get(
                    self.drv_a.key, self.drv_a.key.upper())
                name = f"{model}-MIRROR"
                self.transport.sendto(
                    encode_message("/xinfo", [self.a.host, name, model, "4.06"]), addr)
            return

        if args:
            # client writes: push to both consoles, mirror the value to
            # every other client; console echoes are suppressed as usual
            self._log_op("client", address, args)
            if not self.active:
                self.stats["client_writes_standby"] = self.stats.get("client_writes_standby", 0) + 1
                log.warning("client write while STANDBY ignored: %s", address)
                return
            now = time.monotonic()
            if self.coalesce_window > 0 and len(args) == 1 and isinstance(args[0], float):
                self._coalesce_send(self.a, address, list(args), now)
            else:
                self._send(self.a, address, list(args))
                self._recent_writes.append((now, self.a.host, address, list(args)))
            pairmap = self.pairmap_ab
            translated = pairmap.translate(address, args) if pairmap else (address, list(args))
            if translated is not None:
                out_path, out_args = translated
                if self.coalesce_window > 0 and len(out_args) == 1 and isinstance(out_args[0], float):
                    self._coalesce_send(self.b, out_path, list(out_args), now)
                else:
                    self._send(self.b, out_path, list(out_args))
                    self._recent_writes.append((now, self.b.host, out_path, list(out_args)))
            else:
                self.stats["unmapped"] = self.stats.get("unmapped", 0) + 1
            self.stats["client_writes"] = self.stats.get("client_writes", 0) + 1
            data = encode_message(address, args)
            for caddr in list(self.clients):
                if caddr != addr:
                    self.transport.sendto(data, caddr)
        else:
            # read / subscription request: ask console a, its reply is
            # relayed to all clients through the normal path
            self._send(self.a, address, [])

    def _relay_to_clients(self, address, args):
        data = None
        for caddr in list(self.clients):
            try:
                if data is None:
                    data = encode_message(address, args)
                self.transport.sendto(data, caddr)
            except Exception as exc:  # noqa: BLE001
                log.warning("relay to client %s failed: %s", caddr, exc)

    @staticmethod
    def _args_match(sent: list, received) -> bool:
        """Echo detection tolerant to float32 quantisation on the wire."""
        if len(sent) != len(received):
            return False
        for a, b in zip(sent, received):
            if isinstance(a, float) and isinstance(b, (int, float)):
                if abs(a - float(b)) > 1e-4 * max(1.0, abs(a)):
                    return False
            elif a != b:
                return False
        return True

    def _send(self, console: Console, address: str, args):
        try:
            self.transport.sendto(encode_message(address, args), (console.host, console.port))
        except OSError as exc:
            # Windows raises WSAECONNRESET on the next send after a console
            # vanished/rebooted; swallow it so forwarding keeps running.
            log.warning("send to %s failed: %s", console.name, exc)

    # ---- background tasks ------------------------------------------
    async def _renew_loop(self):
        while not self._stop.is_set():
            await asyncio.sleep(self.renew_interval)
            for c, drv in ((self.a, self.drv_a), (self.b, self.drv_b)):
                if drv.renew_path:
                    self._send(c, drv.renew_path, [])

    async def _stat_loop(self):
        while not self._stop.is_set():
            await asyncio.sleep(10)
            for c in (self.a, self.b):
                age = "never" if c.last_seen is None else f"{time.time() - c.last_seen:.1f}s ago"
                log.info("link %s: last message %s", c.name, age)
            if self.clients:
                now = time.monotonic()
                dead = [a for a, ts in self.clients.items()
                        if now - ts > self.client_timeout_s]
                for a in dead:
                    self.clients.pop(a, None)
                if dead:
                    log.info("dropped %d idle remote client(s)", len(dead))
            log.info("stats: %s clients=%d", self.stats, len(self.clients))

    async def _flush_loop(self):
        while not self._stop.is_set():
            await asyncio.sleep(2)
            await self._flush_ops()

    async def _watch_loop(self):
        """Link watchdog: actively probe consoles (idle consoles push nothing),
        alert once when one goes silent, once when it comes back."""
        while not self._stop.is_set():
            await asyncio.sleep(2.0)
            for key, c, drv in (("a", self.a, self.drv_a), ("b", self.b, self.drv_b)):
                if drv.transport == "osc-udp":
                    try:
                        self._send(c, "/xinfo", [])  # probe: console replies -> last_seen
                    except Exception:  # noqa: BLE001
                        pass
                age = None if c.last_seen is None else time.time() - c.last_seen
                online = age is not None and age < self.link_timeout
                if not online and not self.link_alerted[key]:
                    self.link_alerted[key] = True
                    self.stats["link_alerts"] = self.stats.get("link_alerts", 0) + 1
                    log.warning("LINK ALERT: console %s unreachable (no OSC reply for >%.0fs) - mirror degraded",
                                c.name, self.link_timeout)
                elif online and self.link_alerted[key]:
                    self.link_alerted[key] = False
                    log.warning("LINK RECOVERED: console %s is back", c.name)

    async def _reconcile_loop(self):
        """Periodic A-vs-B divergence check; on mismatch re-align via full sync."""
        await asyncio.sleep(self.reconcile_interval)
        while not self._stop.is_set():
            diff = self._state_diff()
            if diff and self.active:
                log.warning("reconcile: %d parameter(s) differ between consoles, re-aligning (e.g. %s)",
                            len(diff), diff[0])
                self.stats["reconcile_fixes"] = self.stats.get("reconcile_fixes", 0) + len(diff)
                if self.full_sync and (self._fs_task is None or self._fs_task.done()):
                    self._fs_task = asyncio.create_task(self._full_sync())
            elif diff:
                self.stats["reconcile_diff"] = len(diff)
            await asyncio.sleep(self.reconcile_interval)

    def _state_diff(self, grace: float = 2.0):
        """Paths where the two consoles' known values disagree.

        Paths updated within `grace` seconds on either side are skipped:
        during an active fader move B is intentionally behind by the
        coalescing window - that is in-flight traffic, not divergence.
        """
        sa, sb = self.state_by_src["a"], self.state_by_src["b"]
        now = time.monotonic()
        diff = []
        for path, va in sa.items():
            vb = sb.get(path)
            if vb is None:
                continue
            ta = self.state_src_ts["a"].get(path, 0.0)
            tb = self.state_src_ts["b"].get(path, 0.0)
            if now - max(ta, tb) < grace:
                continue  # recently active on either side -> may be in-flight
            if not self._args_match(va, vb):
                diff.append(path)
        return diff

    def status_dict(self) -> dict:
        def link(c, key):
            age = None if c.last_seen is None else time.time() - c.last_seen
            return {
                "name": c.name, "host": c.host, "port": c.port,
                "online": age is not None and age < self.link_timeout,
                "last_seen_age_s": round(age, 1) if age is not None else None,
                "alert": self.link_alerted[key],
            }
        st = dict(self.stats)
        n = st.get("echo_n", 0)
        lat = round(st.pop("echo_ms_sum", 0.0) / n, 1) if n else None
        st.pop("echo_n", None)
        return {
            "active": self.active,
            "ha": bool(self.ha),
            "consoles": [link(self.a, "a"), link(self.b, "b")],
            "stats": st,
            "latency_ms": lat,
            "clients": len(self.clients),
            "pending_coalesce": len(self._pending),
            "sync_paths": len(self.sync_paths),
            "driver_a": self.drv_a.key, "driver_b": self.drv_b.key,
        }

    async def _full_sync(self):
        if self.drv_a.key != self.drv_b.key and self.pairmap_ab is None:
            log.warning("full sync skipped: cross-brand pairs need parameter mapping (not implemented)")
            return
        src = self.a if self.full_sync_from == "a" else self.b
        log.info("full state sync from %s: %d paths", src.name, len(self.sync_paths))
        try:
            for path in self.sync_paths:
                self._send(src, path, [])  # read request; reply gets forwarded
                await asyncio.sleep(0.002)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("full sync crashed: %s", exc)

    # ---- op-log ------------------------------------------------------
    def _init_db(self):
        self._db = sqlite3.connect(self.oplog_db)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS ops ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, src TEXT, path TEXT, val TEXT)"
        )
        self._db.commit()

    def _log_op(self, src_name, address, args):
        if not self.oplog_db:
            return
        self._opbuf.append((time.time(), src_name, address, repr(args)))

    async def _flush_ops(self):
        if not self._db or not self._opbuf:
            return
        rows, self._opbuf = self._opbuf, []
        self._db.executemany("INSERT INTO ops (ts, src, path, val) VALUES (?, ?, ?, ?)", rows)
        self._db.commit()


def default_config(host_a, host_b, port_a=10023, port_b=10023):
    return {
        "listen_host": "0.0.0.0",
        "listen_port": 10099,
        "direction": "both",
        "echo_window_s": 1.0,
        "renew_interval_s": 5.0,
        "coalesce_window_s": 0.12,
        "reconcile_interval_s": 3600.0,
        "link_timeout_s": 15.0,
        "full_sync": True,
        "full_sync_from": "a",
        "oplog_db": "oplog.sqlite",
        "consoles": {
            "a": {"name": "console-A", "host": host_a, "port": port_a},
            "b": {"name": "console-B", "host": host_b, "port": port_b},
        },
    }


def restore_snapshot(cfg: dict, snap: dict, delay=0.004) -> int:
    """Standalone one-key restore: write every snapshot path back to BOTH
    consoles (value-translated for cross-family pairs). Returns path count.
    Fire-and-forget UDP writes, rate-limited to keep the consoles happy."""
    import socket as _socket

    paths = snap.get("paths") or {}
    ca, cb = cfg["consoles"]["a"], cfg["consoles"]["b"]
    drv_a = get_driver(ca.get("driver", "x32"))
    drv_b = get_driver(cb.get("driver", "x32"))
    fam_a, fam_b = MAP_FAMILY.get(drv_a.key), MAP_FAMILY.get(drv_b.key)
    pairmap = PairMap(fam_a, fam_b) if fam_a and fam_b else None

    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    try:
        n = 0
        for path, args in sorted(paths.items()):
            try:
                sock.sendto(encode_message(path, args), (ca["host"], int(ca.get("port", 10023))))
                if pairmap:
                    t = pairmap.translate(path, args)
                    if t is not None:
                        sock.sendto(encode_message(t[0], t[1]),
                                    (cb["host"], int(cb.get("port", 10023))))
                elif drv_a.key == drv_b.key:
                    sock.sendto(encode_message(path, args),
                                (cb["host"], int(cb.get("port", 10023))))
                n += 1
                time.sleep(delay)
            except Exception as exc:  # noqa: BLE001
                log.warning("restore write %s failed: %s", path, exc)
    finally:
        sock.close()
    return n


def random_fader():
    return round(random.uniform(0.0, 1.0), 3)
