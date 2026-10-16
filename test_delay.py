"""Delayed-mirror self test: A operates -> B syncs after sync_delay_s.

Verifies:
  1. B does NOT receive the write before the delay elapses
  2. B receives it shortly after the delay (trailing single write)
  3. the echo from B is suppressed (no ping-pong back to A)
  4. recent_ops records delayed -> synced entries
  5. full-sync baseline ignores the delay
  6. stop() discards pending delayed writes
"""
import asyncio
import socket
import sys
import time

sys.path.insert(0, r"E:\AI\workbuddy\x32\x32-mirror")

from x32mirror.engine import MirrorEngine
from x32mirror.osc import encode_message
from x32mirror.simulator import MockX32

PORT_A, PORT_B, PORT_E = 21023, 21024, 21099
DELAY = 2.0
PATH = "/ch/01/mix/01/fader"
VALUE = 0.4321

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


async def wait_for(predicate, timeout, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def main():
    a = MockX32("mock-A", "127.0.0.1", PORT_A)
    b = MockX32("mock-B", "127.0.0.1", PORT_B)
    await asyncio.gather(a.start(), b.start())

    def make_cfg(**over):
        cfg = {
            "listen_host": "127.0.0.1", "listen_port": PORT_E,
            "direction": "both", "echo_window_s": 1.0, "renew_interval_s": 5.0,
            "coalesce_window_s": 0.12, "sync_delay_s": DELAY,
            "reconcile_interval_s": 3600.0, "link_timeout_s": 15.0,
            "full_sync": False, "full_sync_from": "a", "oplog_db": None,
            "extra_sync_paths": [],
            "consoles": {
                "a": {"name": "mock-A", "host": "127.0.0.1", "port": PORT_A, "driver": "x32"},
                "b": {"name": "mock-B", "host": "127.0.0.1", "port": PORT_B, "driver": "x32"},
            },
        }
        cfg.update(over)
        return cfg

    loop = asyncio.get_running_loop()

    async def spawn(cfg):
        eng = MirrorEngine(cfg)
        transport, _ = await loop.create_datagram_endpoint(
            lambda: eng, local_addr=(cfg["listen_host"], cfg["listen_port"]))
        await eng.start()
        return eng, transport

    # ---------- phase 1: full sync baseline ignores the delay ----------
    print("phase 1: full-sync baseline with delay active")
    eng, tr = await spawn(make_cfg(full_sync=True))
    ok = await wait_for(lambda: len(b.state) >= 1000, 12)
    check("full sync completes despite sync_delay (bypass)", ok,
          f"B state paths={len(b.state)}")
    await eng.stop()
    tr.close()
    await asyncio.sleep(0.6)  # let Windows release the UDP port
    b.state = {p: v for p, v in b.state.items()}  # keep; next engine re-aligns

    # ---------- phase 2: delayed mirroring ----------
    print("phase 2: delayed mirroring A -> B")
    b.state[PATH] = 0.01  # distinct from VALUE so the change is visible
    eng, tr = await spawn(make_cfg())
    await asyncio.sleep(0.5)  # renew subscriptions settle

    user = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    user.sendto(encode_message(PATH, [VALUE]), ("127.0.0.1", PORT_A))
    t0 = time.monotonic()

    # B must NOT get it early
    await asyncio.sleep(DELAY * 0.5)
    early = b.state.get(PATH)
    check("B not updated before delay", early is None or abs(early - VALUE) > 1e-6, f"B={early}")

    ok = await wait_for(lambda: b.state.get(PATH) is not None and abs(b.state.get(PATH) - VALUE) < 1e-6, DELAY + 2.5)
    elapsed = time.monotonic() - t0
    check("B updated after delay", ok, f"elapsed={elapsed:.2f}s (delay={DELAY}s)")
    check("delay honoured (>= 1.8s)", elapsed >= 1.8, f"{elapsed:.2f}s")

    # echo must be suppressed: A keeps its value, engine counts the echo
    await asyncio.sleep(1.5)
    check("echo suppressed (no ping-pong to A)",
          a.state.get(PATH) is not None and abs(a.state.get(PATH) - VALUE) < 1e-6
          and eng.stats.get("echo_suppressed", 0) >= 1,
          f"A={a.state.get(PATH)} echo={eng.stats.get('echo_suppressed')}")

    ops = eng.status_dict()["recent_ops"]
    synced = [o for o in ops if o["state"] == "synced" and o["path"] == PATH]
    delayed = [o for o in ops if o["state"] == "delayed" and o["path"] == PATH]
    check("recent_ops records delayed+synced", bool(synced) and bool(delayed),
          f"synced={len(synced)} delayed={len(delayed)}")
    check("status exposes sync_delay_s/pending_delay",
          eng.status_dict()["sync_delay_s"] == DELAY, "")

    # ---------- phase 3: stop discards pending delayed writes ----------
    print("phase 3: stop() discards pending delayed writes")
    user.sendto(encode_message(PATH, [0.9]), ("127.0.0.1", PORT_A))
    await asyncio.sleep(0.4)  # inside the delay window
    pending = eng.status_dict()["pending_delay"]
    await eng.stop()
    tr.close()
    await asyncio.sleep(DELAY + 1.0)
    check("pending write discarded on stop",
          pending >= 1 and b.state.get(PATH) is not None and abs(b.state.get(PATH) - VALUE) < 1e-6,
          f"pending_before_stop={pending} B={b.state.get(PATH)}")

    a.transport.close()
    b.transport.close()

    print()
    failed = [n for n, ok in results if not ok]
    print(f"result: {'PASS' if not failed else 'FAIL'} ({len(results) - len(failed)}/{len(results)})")
    return 0 if not failed else 1


sys.exit(asyncio.run(main()))
