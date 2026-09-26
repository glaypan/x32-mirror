"""E2E test for the sync-optimisation package:

1. fader coalescing (first value instant, trailing latest value, storm collapsed)
2. scene passthrough (/goto forwarded verbatim, no loops)
3. periodic reconciliation (divergence detected -> full sync re-aligns)
4. echo-latency statistics
5. status_dict() monitoring fields
6. op-log replay CLI helper (gap recovery)
"""
import asyncio
import json
import logging
import socket as _socket
import sys
import time

logging.basicConfig(level=logging.WARNING, format="%(message)s")

from x32mirror.engine import MirrorEngine
from x32mirror.osc import encode_message
from x32mirror.simulator import MockX32

results = {}
SWEEP_PATH = "/ch/01/mix/01/fader"
GOTO = "/goto"


def udp():
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    s.settimeout(0.5)
    return s


async def sweep(sock, port, n=12, gap=0.03):
    """Emulate a fast physical fader drag: many pushes in quick succession."""
    for i in range(n):
        sock.sendto(encode_message(SWEEP_PATH, [round(0.1 + 0.06 * i, 3)]),
                    ("127.0.0.1", port))
        await asyncio.sleep(gap)


async def flow():
    a = MockX32("A", "127.0.0.1", 11023)
    b = MockX32("B", "127.0.0.1", 12023)
    await a.start()
    await b.start()

    cfg = {
        "listen_host": "127.0.0.1",
        "listen_port": 19091,
        "direction": "both",
        "echo_window_s": 1.0,
        "coalesce_window_s": 0.15,
        "reconcile_interval_s": 3.0,
        "link_timeout_s": 5.0,
        "full_sync": True,
        "full_sync_from": "a",
        "oplog_db": "test-replay.sqlite",
        "consoles": {
            "a": {"name": "console-A", "host": "127.0.0.1", "port": 11023},
            "b": {"name": "console-B", "host": "127.0.0.1", "port": 12023},
        },
    }
    eng = MirrorEngine(cfg)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: eng, local_addr=("127.0.0.1", cfg["listen_port"]))
    await eng.start()
    await asyncio.sleep(4.0)  # full sync over ~1060 paths + settle
    results["full_sync_paths"] = len(eng.sync_paths)

    fwd0 = eng.stats["forwarded"]

    # --- 2. scene passthrough -------------------------------------------
    sock = udp()
    sock.sendto(encode_message(GOTO, [5]), ("127.0.0.1", 11023))
    await asyncio.sleep(0.4)
    # B applied the scene; A got it back as an echo -> round trip, no loop
    results["scene_forwarded"] = b.state.get(GOTO) == 5 and a.state.get(GOTO) == 5

    # --- 1. coalescing ----------------------------------------------------
    await sweep(sock, 11023)
    await asyncio.sleep(0.6)  # window (0.15s) closes, trailing value delivered
    results["coalesced_count"] = eng.stats.get("coalesced", 0)
    results["coalesce_forwards"] = eng.stats["forwarded"] - fwd0 - 1  # minus /goto
    results["final_value_synced"] = abs(
        (a.state.get(SWEEP_PATH) or 0) - (b.state.get(SWEEP_PATH) or 0)) < 1e-4
    results["coalesce_ok"] = results["coalesced_count"] >= 8 and \
        results["coalesce_forwards"] <= 4 and results["final_value_synced"]

    # --- 4. latency stats -------------------------------------------------
    results["latency_stat"] = eng.stats.get("echo_n", 0) > 0 and \
        eng.stats.get("echo_ms_sum", 0) > 0

    # --- 3. reconciliation ------------------------------------------------
    # simulate a lost UDP packet: one fader change from A never reaches B
    orig_send = eng._send
    dropped = {"flag": False}

    def dropping_send(console, path, args_):
        if not dropped["flag"] and console is eng.b and path == SWEEP_PATH:
            dropped["flag"] = True  # simulated packet loss: B misses the write
            return
        orig_send(console, path, args_)

    eng._send = dropping_send
    sock.sendto(encode_message(SWEEP_PATH, [0.66]), ("127.0.0.1", 11023))
    await asyncio.sleep(0.6)
    eng._send = orig_send
    # the reconcile stability grace (2s) hides in-flight paths; wait it out
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline and not eng._state_diff():
        await asyncio.sleep(0.3)
    results["divergence_created"] = bool(eng._state_diff())

    deadline = time.monotonic() + 14
    while time.monotonic() < deadline and not eng.stats.get("reconcile_fixes"):
        await asyncio.sleep(0.3)
    results["reconcile_fixes"] = eng.stats.get("reconcile_fixes", 0)
    # the triggered full sync takes ~2s over 1060 paths; wait for it to clear
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline and eng._state_diff():
        await asyncio.sleep(0.3)
    results["reconcile_ok"] = results["reconcile_fixes"] >= 1 and \
        results["divergence_created"] and not eng._state_diff()

    # --- 5. status dict ----------------------------------------------------
    sd = eng.status_dict()
    results["status_fields"] = all(k in sd for k in (
        "active", "consoles", "stats", "latency_ms", "clients",
        "pending_coalesce", "sync_paths", "driver_a", "driver_b"))
    results["status_online"] = all(c["online"] for c in sd["consoles"])
    results["latency_ms"] = sd["latency_ms"]

    await eng.stop()
    transport.close()

    # --- 6. op-log replay --------------------------------------------------
    from x32mirror.__main__ import cmd_replay
    b.state[SWEEP_PATH] = 0.0  # pretend B lost the value (replacement console)
    cfg["listen_port"] = 19092
    with open("test-replay-config.json", "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)

    class A:  # argparse namespace stand-in
        config = "test-replay-config.json"
        db = "test-replay.sqlite"
        src = None
        since_hours = 24.0
        target = "both"
        rate = 0.002
        yes = True

    await cmd_replay(A())
    await asyncio.sleep(0.4)
    results["replay_applied"] = abs((b.state.get(SWEEP_PATH) or 0) -
                                    (a.state.get(SWEEP_PATH) or 0)) < 1e-4


def main():
    asyncio.run(flow())
    ok_flags = {
        "scene": results["scene_forwarded"],
        "coalesce": results["coalesce_ok"],
        "latency": results["latency_stat"],
        "reconcile": results["reconcile_ok"],
        "status": results["status_fields"] and results["status_online"],
        "replay": results["replay_applied"],
    }
    for k, v in results.items():
        print(f"  {k}: {v}")
    print("flags:", ok_flags)
    print("result:", "PASS" if all(ok_flags.values()) else "FAIL")
    return 0 if all(ok_flags.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
