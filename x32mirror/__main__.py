"""CLI entry point.

Commands:
    run       start the mirror engine against real consoles (config.json)
    simulate  run two mock consoles locally and verify end-to-end mirroring
"""

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import time

from .engine import MirrorEngine, restore_snapshot
from .mapping import MAPS
from .simulator import FADER_PATHS, MUTE_PATHS, MockRemoteApp, MockWing, MockX32


async def cmd_run(cfg, duration=None):
    loop = asyncio.get_running_loop()
    engine = MirrorEngine(cfg)
    transport, _ = await loop.create_datagram_endpoint(
        lambda: engine, local_addr=(cfg.get("listen_host", "0.0.0.0"), cfg.get("listen_port", 10099))
    )
    await engine.start()
    ha_role = "hot-standby enabled" if engine.ha else "single node"
    logging.getLogger("x32mirror").info(
        "mirror engine running (direction=%s, consoles=%s/%s, %s) - Ctrl+C to stop",
        engine.direction,
        engine.a.name,
        engine.b.name,
        ha_role,
    )
    try:
        if duration:
            await asyncio.sleep(duration)
        else:
            await asyncio.Event().wait()
    finally:
        await engine.stop()
        transport.close()


async def cmd_simulate(duration):
    a = MockX32("A", "127.0.0.1", 11023)
    b = MockX32("B", "127.0.0.1", 12023)
    await a.start()
    await b.start()

    cfg = {
        "listen_host": "127.0.0.1",
        "listen_port": 19023,
        "direction": "both",
        "echo_window_s": 1.0,
        "renew_interval_s": 5.0,
        "full_sync": True,
        "full_sync_from": "a",
        "oplog_db": None,
        "consoles": {
            "a": {"name": "mock-A", "host": "127.0.0.1", "port": 11023},
            "b": {"name": "mock-B", "host": "127.0.0.1", "port": 12023},
        },
    }
    engine = MirrorEngine(cfg)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: engine, local_addr=(cfg["listen_host"], cfg["listen_port"])
    )
    await engine.start()

    movers = [
        asyncio.create_task(a.auto_move(2.0)),
        asyncio.create_task(b.auto_move(3.0)),
    ]
    print(f"simulating {duration:.0f}s of live operation on both consoles...")
    await asyncio.sleep(duration)

    for t in movers:
        t.cancel()
    await engine.stop()
    transport.close()

    ok, mismatches = compare_states(a, b)
    print()
    print("=== simulation report ===")
    print(f"engine stats: {engine.stats}")
    print(f"mock A sets applied: {a.set_count}, mock B sets applied: {b.set_count}")
    if mismatches:
        print(f"state mismatches ({len(mismatches)}):")
        for path, va, vb in mismatches[:20]:
            print(f"  {path}: A={va!r} B={vb!r}")
    else:
        print("result: PASS - both consoles converged to identical state")
    return 0 if ok else 1


def compare_states(a: MockX32, b: MockX32):
    mismatches = []
    for path in sorted(set(a.state) | set(b.state)):
        va, vb = a.state.get(path), b.state.get(path)
        if isinstance(va, float) or isinstance(vb, float):
            if va is None or vb is None or abs(va - vb) > 1e-6:
                mismatches.append((path, va, vb))
        elif va != vb:
            mismatches.append((path, va, vb))
    return not mismatches, mismatches


def compare_states_cross(a: MockX32, b: MockWing):
    """Semantic comparison: convert both sides to canonical (dB/int/str)."""
    xm, wm = MAPS["x32"], MAPS["wing"]
    mismatches = []
    compared = 0
    for xpath, va in sorted(a.state.items()):
        key = xm.parse(xpath)
        if key is None:
            continue
        family, _n, kind = key
        wpath = wm.build(key)
        if wpath is None:  # no WING equivalent (should not happen for x32 keys)
            continue
        vb = b.state.get(wpath)
        if vb is None:
            continue  # path not yet synced on WING side
        compared += 1
        if kind == "fader":
            ca, cb_ = xm.fader_to_db(va), wm.fader_to_db(vb)
            if ca is None or cb_ is None:
                if not (ca is None and cb_ is None):
                    mismatches.append((f"{xpath} vs {wpath}", ca, cb_))
            elif abs(ca - cb_) > 0.05:
                mismatches.append((f"{xpath} vs {wpath}", ca, cb_))
        elif kind == "mute":
            if int(bool(va)) != int(bool(vb)):
                mismatches.append((f"{xpath} vs {wpath}", va, vb))
        else:
            if str(va) != str(vb):
                mismatches.append((f"{xpath} vs {wpath}", va, vb))
    return (not mismatches, mismatches, compared)


async def cmd_simulate_cross(duration):
    a = MockX32("X32", "127.0.0.1", 11023)
    b = MockWing("WING", "127.0.0.1", 12023)
    await a.start()
    await b.start()

    cfg = {
        "listen_host": "127.0.0.1",
        "listen_port": 19023,
        "direction": "both",
        "echo_window_s": 1.0,
        "renew_interval_s": 5.0,
        "full_sync": True,
        "full_sync_from": "a",
        "oplog_db": None,
        "consoles": {
            "a": {"name": "mock-x32", "host": "127.0.0.1", "port": 11023, "driver": "x32"},
            "b": {"name": "mock-wing", "host": "127.0.0.1", "port": 12023, "driver": "wing"},
        },
    }
    engine = MirrorEngine(cfg)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: engine, local_addr=(cfg["listen_host"], cfg["listen_port"])
    )
    await engine.start()

    movers = [
        asyncio.create_task(a.auto_move(2.0)),
        asyncio.create_task(b.auto_move(3.0)),
    ]
    print(f"simulating {duration:.0f}s of live operation: X32 <-> WING (cross-family mapping)...")
    await asyncio.sleep(duration)

    for t in movers:
        t.cancel()
    await engine.stop()
    transport.close()

    ok, mismatches, compared = compare_states_cross(a, b)
    print()
    print("=== cross-family simulation report ===")
    print(f"engine stats: {engine.stats}")
    print(f"semantic parameters compared: {compared}")
    if mismatches:
        print(f"mismatches ({len(mismatches)}):")
        for path, va, vb in mismatches[:20]:
            print(f"  {path}: X32={va!r} WING={vb!r}")
    else:
        print("result: PASS - X32 and WING converged semantically (dB-normalized)")
    return 0 if ok else 1


async def cmd_simulate_ha():
    """HA test: election -> crash failover -> manual promote -> manual demote."""
    a = MockX32("A", "127.0.0.1", 11023)
    b = MockX32("B", "127.0.0.1", 12023)
    await a.start()
    await b.start()

    def mk_cfg(listen_port, node, local_ha, peer_ha):
        return {
            "listen_host": "127.0.0.1",
            "listen_port": listen_port,
            "direction": "both",
            "echo_window_s": 1.0,
            "renew_interval_s": 5.0,
            "full_sync": True,
            "full_sync_from": "a",
            "oplog_db": None,
            "ha": {
                "enabled": True,
                "node_id": node,
                "peer_host": "127.0.0.1",
                "port": peer_ha,
                "local_port": local_ha,
                "failover_s": 3.0,
            },
            "consoles": {
                "a": {"name": "mock-A", "host": "127.0.0.1", "port": 11023},
                "b": {"name": "mock-B", "host": "127.0.0.1", "port": 12023},
            },
        }

    loop = asyncio.get_running_loop()

    async def spawn_engine(node):
        ports = {"pc-1": 19031, "pc-2": 19032}
        ha_ports = {"pc-1": (49901, 49902), "pc-2": (49902, 49901)}
        e = MirrorEngine(mk_cfg(ports[node], node, *ha_ports[node]))
        t, _ = await loop.create_datagram_endpoint(
            lambda: e, local_addr=("127.0.0.1", ports[node]))
        await e.start()
        return e, t

    e1, t1 = await spawn_engine("pc-1")
    await asyncio.sleep(0.5)  # let pc-1 win the election first (earlier start_ts)
    e2, t2 = await spawn_engine("pc-2")

    movers = [
        asyncio.create_task(a.auto_move(2.0)),
        asyncio.create_task(b.auto_move(3.0)),
    ]

    print("phase 1: pc-1 (primary) + pc-2 (standby), live operation 7s...")
    await asyncio.sleep(7)
    ok_phase1 = e1.active and not e2.active
    print(f"  election: pc-1 active={e1.active}, pc-2 active={e2.active}")

    print("phase 2: killing pc-1 (primary crash), failover window 3s...")
    await e1.stop()
    t1.close()
    await asyncio.sleep(8)  # failover (3s) + takeover full-sync (1060 paths ~2.5s) + convergence
    ok_phase2 = e2.active
    print(f"  failover: pc-2 active={e2.active}")

    print("phase 3: pc-1 restarts (auto-standby), manual PROMOTE to pc-1...")
    e1, t1 = await spawn_engine("pc-1")
    await asyncio.sleep(4)  # pc-1b rejoins as standby (pc-2 keeps leadership)
    ok_rejoin = e1.active is False and e2.active
    ack = await loop.run_in_executor(None, send_ha_command, "127.0.0.1", 49901, "promote")
    await asyncio.sleep(7)  # switchover + pc-1 full-sync (1060 paths) + convergence
    ok_phase3 = bool(ack and ack.get("ack") == "promote") and e1.active and not e2.active
    print(f"  rejoin: pc-1 standby={ok_rejoin}; promote ack={ack and ack.get('ack')}")
    print(f"  after switch: pc-1 active={e1.active}, pc-2 active={e2.active}")

    print("phase 4: manual DEMOTE to pc-1 (switch back)...")
    ack = await loop.run_in_executor(None, send_ha_command, "127.0.0.1", 49901, "demote")
    await asyncio.sleep(7)  # pc-2 takes back via auto election + convergence
    ok_phase4 = bool(ack and ack.get("ack") == "demote") and (not e1.active) and e2.active
    print(f"  after switch back: pc-1 active={e1.active}, pc-2 active={e2.active}")

    for t in movers:
        t.cancel()
    await asyncio.sleep(0.5)  # let in-flight coalesced writes settle

    ok_conv, mismatches = compare_states(a, b)
    print()
    print("=== hot-standby simulation report ===")
    print(f"phase 1 election:      {'PASS' if ok_phase1 else 'FAIL'} (pc-1 active / pc-2 standby)")
    print(f"phase 2 crash failover: {'PASS' if ok_phase2 else 'FAIL'} (pc-2 took over)")
    print(f"phase 3 rejoin+promote: {'PASS' if ok_phase3 else 'FAIL'} (manual switch to pc-1)")
    print(f"phase 4 manual demote:  {'PASS' if ok_phase4 else 'FAIL'} (switch back to pc-2)")
    print(f"final convergence:      {'PASS' if ok_conv else 'FAIL'} ({len(mismatches)} mismatches)")
    if mismatches:
        for path, va, vb in mismatches[:10]:
            print(f"  {path}: A={va!r} B={vb!r}")
    ok = ok_phase1 and ok_phase2 and ok_phase3 and ok_phase4 and ok_conv
    print("result:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


async def cmd_snapshot(args):
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    if args.listen_port:
        cfg["listen_port"] = args.listen_port
    if args.wait:
        cfg["full_sync"] = True

    loop = asyncio.get_running_loop()
    engine = MirrorEngine(cfg)
    transport, _ = await loop.create_datagram_endpoint(
        lambda: engine, local_addr=(cfg.get("listen_host", "0.0.0.0"), cfg.get("listen_port", 10099)))
    await engine.start()
    print("reading console state (full sync)...")
    await asyncio.sleep(args.wait or 3.0)
    snap = engine.snapshot_dict()
    await engine.stop()
    transport.close()

    from . import cloud
    body = cloud.snapshot_bytes(snap)
    out = args.out or f"snapshot-{time.strftime('%Y%m%d-%H%M%S')}.json"
    with open(out, "wb") as fh:
        fh.write(body)
    print(f"snapshot saved: {out} ({len(snap['paths'])} paths, model={snap['model']})")
    if engine.cloud_cfg:
        name = cloud.snapshot_name(snap.get("node", "node"))
        cloud.upload(engine.cloud_cfg, body, name)
        cloud.upload(engine.cloud_cfg, body, "latest.json")
        print(f"uploaded to cloud ({engine.cloud_cfg.get('provider')}): {name} + latest.json")
    return 0


async def cmd_restore(args):
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    from . import cloud
    if args.file == "latest":
        raw = cloud.download_latest(cfg.get("cloud") or {})
        if raw is None:
            print("no cloud snapshot found (check cloud config / connectivity)")
            return 1
        print("downloaded latest snapshot from cloud")
    else:
        with open(args.file, "rb") as fh:
            raw = fh.read()
    snap = cloud.load_snapshot(raw)
    paths = snap.get("paths") or {}
    print(f"snapshot: ts={snap.get('ts')} model={snap.get('model')} paths={len(paths)}")
    for p in sorted(paths)[:8]:
        print(f"  {p} = {paths[p]}")
    if len(paths) > 8:
        print(f"  ... and {len(paths) - 8} more")
    if not args.yes:
        print("dry run: add --yes to write these values to BOTH consoles")
        return 0
    n = await asyncio.get_running_loop().run_in_executor(None, restore_snapshot, cfg, snap)
    print(f"restore complete: {n} paths written to both consoles")
    return 0


async def cmd_cloud_download(args):
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    from . import cloud
    raw = cloud.download_latest(cfg.get("cloud") or {})
    if raw is None:
        print("download failed or no snapshot in cloud")
        return 1
    out = args.out or "latest-snapshot.json"
    with open(out, "wb") as fh:
        fh.write(raw)
    snap = cloud.load_snapshot(raw)
    print(f"downloaded {out} ({len(snap.get('paths') or {})} paths, ts={snap.get('ts')})")
    return 0


async def cmd_simulate_cloud():
    """Offline cloud-backup test: snapshot -> local cloud dir -> restore."""
    import tempfile

    from . import cloud

    a = MockX32("A", "127.0.0.1", 11023)
    b = MockX32("B", "127.0.0.1", 12023)
    await a.start()
    await b.start()

    cloud_dir = os.path.join(tempfile.gettempdir(), "x32mirror-cloud-test")
    cfg = {
        "listen_host": "127.0.0.1",
        "listen_port": 19034,
        "direction": "both",
        "echo_window_s": 1.0,
        "renew_interval_s": 5.0,
        "full_sync": True,
        "full_sync_from": "a",
        "oplog_db": None,
        "cloud": {"enabled": True, "provider": "local", "dir": cloud_dir,
                  "prefix": "x32mirror", "interval_hours": 0},
        "consoles": {
            "a": {"name": "mock-A", "host": "127.0.0.1", "port": 11023},
            "b": {"name": "mock-B", "host": "127.0.0.1", "port": 12023},
        },
    }
    loop = asyncio.get_running_loop()
    engine = MirrorEngine(cfg)
    transport, _ = await loop.create_datagram_endpoint(
        lambda: engine, local_addr=(cfg["listen_host"], cfg["listen_port"]))
    await engine.start()
    await asyncio.sleep(3.5)  # full sync (1060 paths) populates the state cache

    # 1. snapshot from live state and upload to the (local) cloud
    snap = engine.snapshot_dict()
    body = cloud.snapshot_bytes(snap)
    name = cloud.snapshot_name("node")
    cloud.upload(cfg["cloud"], body, name)
    cloud.upload(cfg["cloud"], body, "latest.json")
    n_paths = len(snap["paths"])
    print(f"1. snapshot + upload: {n_paths} paths -> {cfg['cloud']['provider']}:{name}")

    # 2. download back from the cloud and verify integrity
    dl = cloud.download_latest(cfg["cloud"])
    ok_upload = dl is not None and cloud.load_snapshot(dl)["paths"] == snap["paths"]
    print(f"2. cloud download & integrity: {'PASS' if ok_upload else 'FAIL'}")

    # 3. scramble both consoles' fader/mute state (simulates drift/accident)
    import random as _r
    for p in FADER_PATHS:
        v = round(_r.uniform(0.0, 1.0), 3)
        a._apply(p, [v])
        b._apply(p, [v])
    for p in MUTE_PATHS:
        v = _r.randint(0, 1)
        a._apply(p, [v])
        b._apply(p, [v])
    print("3. consoles scrambled")

    # 4. one-key restore from the cloud snapshot
    n = await loop.run_in_executor(None, restore_snapshot, cfg, cloud.load_snapshot(dl))
    await asyncio.sleep(1.0)  # let broadcasts settle
    print(f"4. restore wrote {n} paths back to both consoles")

    # 5. verify both consoles match the snapshot again
    mismatches = []
    for path, args_ in snap["paths"].items():
        want = args_[0]
        for mock in (a, b):
            got = mock.state.get(path)
            if isinstance(want, float) and isinstance(got, float):
                if abs(want - got) > 1e-6:
                    mismatches.append((mock.name, path, want, got))
            elif got != want:
                mismatches.append((mock.name, path, want, got))
    ok_restore = n == n_paths and not mismatches
    print(f"5. verify: {'PASS' if ok_restore else 'FAIL'} ({len(mismatches)} mismatches)")
    for m in mismatches[:10]:
        print(f"   {m}")

    await engine.stop()
    transport.close()
    ok = ok_upload and ok_restore
    print()
    print("=== cloud backup simulation report ===")
    print("result:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


async def cmd_web(args):
    """Mirror + phone-friendly web console in one process."""
    from .webui import WebApp

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    app = WebApp(cfg, args.config, http_port=args.http_port)
    app.start_http()
    if args.autostart:
        app.mgr.start(cfg)
    log.info("web console ready - press Ctrl+C to quit")
    try:
        await asyncio.Event().wait()
    finally:
        await app.mgr._stop()  # noqa: SLF001
        app.stop_http()


def send_ha_command(host, port, action, timeout=2.0):
    """Send a manual-switch command to a node's HA port; return its ack dict."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(json.dumps({"app": "x32mirror", "cmd": action}).encode("utf-8"), (host, int(port)))
        data, _ = sock.recvfrom(4096)
        return json.loads(data.decode("utf-8"))
    except socket.timeout:
        return None
    finally:
        sock.close()


async def cmd_simulate_proxy():
    """Remote-app proxy test: a fake Mixing Station syncs through the tool."""
    a = MockX32("A", "127.0.0.1", 11023)
    b = MockX32("B", "127.0.0.1", 12023)
    await a.start()
    await b.start()

    cfg = {
        "listen_host": "127.0.0.1",
        "listen_port": 19033,
        "direction": "both",
        "echo_window_s": 1.0,
        "renew_interval_s": 5.0,
        "full_sync": True,
        "full_sync_from": "a",
        "oplog_db": None,
        "proxy": {"enabled": True, "max_clients": 8, "client_timeout_s": 60.0},
        "consoles": {
            "a": {"name": "mock-A", "host": "127.0.0.1", "port": 11023},
            "b": {"name": "mock-B", "host": "127.0.0.1", "port": 12023},
        },
    }
    loop = asyncio.get_running_loop()
    engine = MirrorEngine(cfg)
    transport, _ = await loop.create_datagram_endpoint(
        lambda: engine, local_addr=(cfg["listen_host"], cfg["listen_port"]))
    await engine.start()
    await asyncio.sleep(4.0)  # let the startup full-sync (1060 paths) settle

    app = MockRemoteApp("mixing-station", "127.0.0.1", cfg["listen_port"])
    await app.start()

    results = {}

    # 1. discovery: app asks /xinfo, tool answers like an X32
    app.send("/xinfo")
    xinfo, deadline = None, time.monotonic() + 3.0
    while time.monotonic() < deadline and xinfo is None:
        xinfo = app.xinfo_reply
        await asyncio.sleep(0.05)
    results["xinfo"] = bool(xinfo and len(xinfo) == 4 and xinfo[2] == "X32"
                            and "MIRROR" in str(xinfo[1]))
    print(f"1. /xinfo discovery: {xinfo} -> {'PASS' if results['xinfo'] else 'FAIL'}")

    # 2. subscribe, then the app moves a fader: both consoles must follow
    app.send("/renew")
    await asyncio.sleep(0.2)
    app.send("/ch/01/mix/01/fader", [0.555])
    ok_a = await wait_state(a, "/ch/01/mix/01/fader", 0.555)
    ok_b = await wait_state(b, "/ch/01/mix/01/fader", 0.555)
    results["app_write"] = ok_a and ok_b
    print(f"2. app fader write synced to A={a.state.get('/ch/01/mix/01/fader')} "
          f"B={b.state.get('/ch/01/mix/01/fader')} -> {'PASS' if results['app_write'] else 'FAIL'}")

    # 3. physical operation on console B: the app must see it
    app.clear()
    b._apply("/ch/02/mix/01/fader", [0.777])
    got = await app.wait_for("/ch/02/mix/01/fader")
    results["relay"] = bool(got and abs(got[0] - 0.777) < 1e-4)
    print(f"3. console B change relayed to app: {got} -> {'PASS' if results['relay'] else 'FAIL'}")

    # 4. app read request returns the console value
    app.clear()
    app.send("/ch/03/mix/01/fader")
    got = await app.wait_for("/ch/03/mix/01/fader")
    results["app_read"] = got is not None
    print(f"4. app read reply: {got} -> {'PASS' if results['app_read'] else 'FAIL'}")

    # 5. two apps stay in sync with each other
    app2 = MockRemoteApp("x32-edit", "127.0.0.1", cfg["listen_port"])
    await app2.start()
    app2.send("/renew")
    await asyncio.sleep(0.2)
    app.send("/ch/04/mix/01/fader", [0.333])
    got2 = await app2.wait_for("/ch/04/mix/01/fader")
    ok_a2 = await wait_state(a, "/ch/04/mix/01/fader", 0.333)
    results["two_apps"] = bool(got2 and abs(got2[0] - 0.333) < 1e-4 and ok_a2)
    print(f"5. second app received peer app write: {got2} -> {'PASS' if results['two_apps'] else 'FAIL'}")

    await engine.stop()
    transport.close()

    ok = all(results.values())
    print()
    print("=== remote-app proxy simulation report ===")
    print(f"engine stats: {engine.stats} clients={len(engine.clients)}")
    print("result:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


async def wait_state(mock, path, value, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = mock.state.get(path)
        if v is not None and abs(float(v) - value) < 1e-4:
            return True
        await asyncio.sleep(0.05)
    return False


async def cmd_replay(args):
    """Replay op-log entries onto the consoles (gap / replacement recovery)."""
    import ast
    import os
    import socket as _socket
    import sqlite3

    from .osc import encode_message

    if not os.path.exists(args.db):
        print(f"no op-log at {args.db} - nothing to replay")
        return 1
    db = sqlite3.connect(args.db)
    since = time.time() - args.since_hours * 3600.0
    q, params = "SELECT ts, src, path, val FROM ops WHERE ts > ?", [since]
    if args.src:
        q += " AND src = ?"
        params.append(args.src)
    rows = db.execute(q + " ORDER BY ts", params).fetchall()
    db.close()

    latest = {}  # newest value per path wins
    for ts, src, path, val in rows:
        try:
            latest[path] = ast.literal_eval(val)
        except Exception:  # noqa: BLE001
            continue
    print(f"op-log: {len(rows)} entries in the last {args.since_hours}h "
          f"-> {len(latest)} unique paths (latest value wins)")
    if not latest:
        return 0
    if not args.yes:
        print("dry run - add --yes to write these values to the consoles")
        for p in sorted(latest)[:10]:
            print(f"  {p} = {latest[p]!r}")
        return 0

    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    ca, cb = cfg["consoles"]["a"], cfg["consoles"]["b"]
    targets = {"both": [ca, cb], "a": [ca], "b": [cb]}[args.target]
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    try:
        for path, a in sorted(latest.items()):
            for c in targets:
                sock.sendto(encode_message(path, a), (c["host"], int(c.get("port", 10023))))
            await asyncio.sleep(args.rate)
    finally:
        sock.close()
    print(f"replayed {len(latest)} paths to {args.target}")
    return 0


def main(argv=None):
    # no args at all -> launch the desktop GUI (double-click friendliness)
    if argv is None and len(sys.argv) == 1:
        from .gui import run_gui
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        run_gui()
        return

    parser = argparse.ArgumentParser(prog="x32mirror", description="Digital console real-time mirror / sync backup")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_gui = sub.add_parser("gui", help="launch the desktop GUI (default when no command given)")
    p_gui.add_argument("--config", default="config.json")

    p_run = sub.add_parser("run", help="mirror real consoles")
    p_run.add_argument("--config", default="config.json")
    p_run.add_argument("--duration", type=float, default=None, help="run for N seconds then exit (default: forever)")

    p_sim = sub.add_parser("simulate", help="offline end-to-end self test (same family)")
    p_sim.add_argument("--duration", type=float, default=12.0)

    p_simc = sub.add_parser("simulate-cross", help="offline X32 <-> WING mapping self test")
    p_simc.add_argument("--duration", type=float, default=14.0)

    p_simha = sub.add_parser("simulate-ha", help="offline hot-standby failover self test")

    p_proxy = sub.add_parser("simulate-proxy", help="offline remote-app (Mixing Station) proxy self test")

    p_snap = sub.add_parser("snapshot", help="capture console state to a snapshot file (+ cloud upload)")
    p_snap.add_argument("--config", default="config.json")
    p_snap.add_argument("--out", default=None, help="output json path")
    p_snap.add_argument("--wait", type=float, default=3.0, help="seconds to read console state")
    p_snap.add_argument("--listen-port", type=int, default=None,
                        help="temp listen port override (use if the mirror is running on this PC)")

    p_restore = sub.add_parser("restore", help="write a snapshot back to BOTH consoles")
    p_restore.add_argument("--config", default="config.json")
    p_restore.add_argument("--file", required=True, help="snapshot json path, or 'latest' to pull from cloud")
    p_restore.add_argument("--yes", action="store_true", help="actually write (default: dry run)")

    p_cdl = sub.add_parser("cloud-download", help="download latest snapshot from cloud to a file")
    p_cdl.add_argument("--config", default="config.json")
    p_cdl.add_argument("--out", default=None)

    p_simc = sub.add_parser("simulate-cloud", help="offline cloud snapshot/restore self test")

    p_ha = sub.add_parser("ha-switch", help="manual HA switch on a running node")
    p_ha.add_argument("action", choices=["promote", "demote", "status"],
                      help="promote=force this node active; demote=yield to peer; status=show role")
    p_ha.add_argument("--host", required=True, help="IP of the computer running the target node")
    p_ha.add_argument("--port", type=int, default=49900, help="HA heartbeat port (must match config)")
    p_ha.add_argument("--timeout", type=float, default=2.0)

    p_web = sub.add_parser("web", help="mirror + phone web console (Android / iPhone)")
    p_web.add_argument("--config", default="config.json")
    p_web.add_argument("--http-port", type=int, default=8080)
    p_web.add_argument("--autostart", action="store_true", help="start the mirror engine immediately")

    p_show = sub.add_parser("show-config", help="print a sample config")

    p_inst = sub.add_parser("install", help="one-click install: x32mirror command + desktop shortcuts")
    p_inst.add_argument("--autostart", action="store_true",
                        help="also run mirror+web console at login (Windows Startup folder)")
    p_inst.add_argument("--web-port", type=int, default=8080, help="web console port for shortcuts/autostart")
    p_inst.add_argument("--dry-run", action="store_true", help="show what would be installed, change nothing")

    p_uninst = sub.add_parser("uninstall", help="remove installed shim/shortcuts/PATH entry")

    p_rep = sub.add_parser("replay", help="replay op-log entries to the consoles (gap recovery)")
    p_rep.add_argument("--config", default="config.json")
    p_rep.add_argument("--db", default="oplog.sqlite", help="op-log sqlite file")
    p_rep.add_argument("--src", default=None, help="only ops recorded from this source name")
    p_rep.add_argument("--since-hours", type=float, default=24.0)
    p_rep.add_argument("--target", choices=["both", "a", "b"], default="both")
    p_rep.add_argument("--rate", type=float, default=0.002, help="seconds between writes")
    p_rep.add_argument("--yes", action="store_true", help="actually write (default: dry run)")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "gui":
        from .gui import run_gui
        run_gui(args.config)
    elif args.cmd == "run":
        with open(args.config, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        asyncio.run(cmd_run(cfg, args.duration))
    elif args.cmd == "simulate":
        sys.exit(asyncio.run(cmd_simulate(args.duration)))
    elif args.cmd == "simulate-cross":
        sys.exit(asyncio.run(cmd_simulate_cross(args.duration)))
    elif args.cmd == "simulate-ha":
        sys.exit(asyncio.run(cmd_simulate_ha()))
    elif args.cmd == "simulate-proxy":
        sys.exit(asyncio.run(cmd_simulate_proxy()))
    elif args.cmd == "snapshot":
        sys.exit(asyncio.run(cmd_snapshot(args)))
    elif args.cmd == "restore":
        sys.exit(asyncio.run(cmd_restore(args)))
    elif args.cmd == "cloud-download":
        sys.exit(asyncio.run(cmd_cloud_download(args)))
    elif args.cmd == "simulate-cloud":
        sys.exit(asyncio.run(cmd_simulate_cloud()))
    elif args.cmd == "ha-switch":
        ack = send_ha_command(args.host, args.port, args.action, args.timeout)
        if ack is None:
            print(f"no reply from {args.host}:{args.port} - node down, wrong --port, or firewalled")
            sys.exit(1)
        role = "ACTIVE (primary)" if ack.get("active") else "STANDBY (backup)"
        peer = ack.get("peer")
        print(f"node {ack.get('id')}: {role}  force={ack.get('force')}  epoch={ack.get('epoch')}"
              + (f"  peer={peer.get('id')}({'active' if peer.get('active') else 'standby'})" if peer else ""))
        if args.action == "status":
            sys.exit(0)
        print(f"{args.action} applied."
              + ("" if ack.get("active") else " Node is standby; peer should be/ become active."))
    elif args.cmd == "web":
        asyncio.run(cmd_web(args))
    elif args.cmd == "show-config":
        from .engine import default_config

        print(json.dumps(default_config("192.168.1.100", "192.168.1.101"), indent=2))
    elif args.cmd == "install":
        from .installer import install

        ok = install(autostart=args.autostart, web_port=args.web_port, dry_run=args.dry_run)
        sys.exit(0 if ok else 1)
    elif args.cmd == "uninstall":
        from .installer import uninstall

        uninstall()
    elif args.cmd == "replay":
        sys.exit(asyncio.run(cmd_replay(args)))


if __name__ == "__main__":
    main()
