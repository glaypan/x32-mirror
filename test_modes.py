"""Sync-mode self test: single / mirror / independent + master + runtime switch.

Verifies (with two MockX32 consoles):
  single (master A):
    1. A operates -> B follows (one-way)
    2. B mis-touch -> B springs back to A's value after ~revert_delay
    3. no ping-pong: A keeps its value, echo suppressed
    4. recent_ops records reverting -> reverted; stats.reverts counted
  single (master B):
    5. B operates -> A follows; A mis-touch springs back to B's value
  mirror:
    6. bidirectional audio follows both ways
    7. screen state (-stat/selidx) follows too
  independent:
    8. audio follows both ways
    9. screen state stays local on each console (NOT forwarded)
  runtime switch:
   10. set_mode(single, a) while running flips direction to a_to_b
   11. set_mode(single, b) flips direction to b_to_a and revert source
"""
import asyncio
import socket
import sys
import time

sys.path.insert(0, r"E:\AI\workbuddy\x32\x32-mirror")

from x32mirror.engine import MirrorEngine, SYNC_MODES, is_screen_path
from x32mirror.osc import encode_message
from x32mirror.simulator import MockX32

PORT_A, PORT_B, PORT_E = 23023, 23024, 23099
FADER = "/ch/01/mix/01/fader"
SEL = "-stat/selidx"
REVERT = 0.5

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


def close(x, v, tol=1e-6):
    return x is not None and abs(x - v) < tol


async def main():
    a = MockX32("mock-A", "127.0.0.1", PORT_A)
    b = MockX32("mock-B", "127.0.0.1", PORT_B)
    await asyncio.gather(a.start(), b.start())

    def make_cfg(**over):
        cfg = {
            "listen_host": "127.0.0.1", "listen_port": PORT_E,
            "echo_window_s": 1.0, "renew_interval_s": 5.0,
            "coalesce_window_s": 0.12, "sync_delay_s": 0.0,
            "reconcile_interval_s": 3600.0, "link_timeout_s": 15.0,
            "full_sync": False, "full_sync_from": "a", "oplog_db": None,
            "extra_sync_paths": [], "sync_mode": "mirror", "master": "a",
            "revert_delay_s": REVERT,
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

    user = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def put(port, path, value):
        user.sendto(encode_message(path, [value]), ("127.0.0.1", port))

    async def align(path, value):
        """Simulate two already-aligned desks (operator set both)."""
        put(PORT_A, path, value)
        put(PORT_B, path, value)
        await wait_for(lambda: close(a.state.get(path), value)
                       and close(b.state.get(path), value), 3)

    # ---------- phase 1: single mode, master A ----------
    print("phase 1: single mode (master A)")
    await align(FADER, 0.5)
    eng, tr = await spawn(make_cfg(sync_mode="single", master="a"))
    await asyncio.sleep(0.5)

    put(PORT_A, FADER, 0.7)  # master operates
    ok = await wait_for(lambda: close(b.state.get(FADER), 0.7), 3)
    check("single: A operates -> B follows", ok, f"B={b.state.get(FADER)}")

    put(PORT_B, FADER, 0.1)  # slave mis-touch
    early = await asyncio.sleep(0.2) or b.state.get(FADER)
    check("single: no instant revert (grace period)",
          close(early, 0.1) or early is None, f"B right after touch={early}")
    ok = await wait_for(lambda: close(b.state.get(FADER), 0.7), 3)
    check("single: B springs back to A's value", ok, f"B={b.state.get(FADER)}")
    check("single: A keeps its value (no ping-pong)", close(a.state.get(FADER), 0.7),
          f"A={a.state.get(FADER)}")
    check("single: stats.reverts counted", eng.stats.get("reverts", 0) >= 1,
          f"reverts={eng.stats.get('reverts')}")
    ops = eng.status_dict()["recent_ops"]
    check("single: recent_ops shows reverting/reverted",
          any(o["state"] == "reverting" for o in ops)
          and any(o["state"] == "reverted" for o in ops),
          f"states={sorted({o['state'] for o in ops})}")
    await eng.stop()
    tr.close()
    await asyncio.sleep(0.8)  # let Windows release the UDP port

    # ---------- phase 2: single mode, master B ----------
    print("phase 2: single mode (master B)")
    await align(FADER, 0.3)
    eng, tr = await spawn(make_cfg(sync_mode="single", master="b"))
    await asyncio.sleep(0.5)
    check("single(master B): direction derived b_to_a", eng.direction == "b_to_a",
          f"direction={eng.direction}")

    put(PORT_B, FADER, 0.8)  # master operates
    ok = await wait_for(lambda: close(a.state.get(FADER), 0.8), 3)
    check("single(master B): B operates -> A follows", ok, f"A={a.state.get(FADER)}")

    put(PORT_A, FADER, 0.05)  # slave mis-touch
    ok = await wait_for(lambda: close(a.state.get(FADER), 0.8), 3)
    check("single(master B): A springs back to B's value", ok, f"A={a.state.get(FADER)}")
    await eng.stop()
    tr.close()
    await asyncio.sleep(0.8)

    # ---------- phase 3: mirror mode ----------
    print("phase 3: mirror mode")
    await align(FADER, 0.2)
    eng, tr = await spawn(make_cfg(sync_mode="mirror"))
    await asyncio.sleep(0.5)

    put(PORT_A, FADER, 0.6)
    ok = await wait_for(lambda: close(b.state.get(FADER), 0.6), 3)
    check("mirror: A -> B", ok, f"B={b.state.get(FADER)}")
    put(PORT_B, FADER, 0.4)
    ok = await wait_for(lambda: close(a.state.get(FADER), 0.4), 3)
    check("mirror: B -> A", ok, f"A={a.state.get(FADER)}")

    put(PORT_A, SEL, 5)  # screen state follows in mirror mode
    ok = await wait_for(lambda: b.state.get(SEL) == 5, 3)
    check("mirror: screen state (-stat/selidx) follows", ok, f"B sel={b.state.get(SEL)}")
    await eng.stop()
    tr.close()
    await asyncio.sleep(0.8)

    # ---------- phase 4: independent mode ----------
    print("phase 4: independent mode")
    await align(FADER, 0.2)
    eng, tr = await spawn(make_cfg(sync_mode="independent"))
    await asyncio.sleep(0.5)

    put(PORT_A, FADER, 0.9)
    ok = await wait_for(lambda: close(b.state.get(FADER), 0.9), 3)
    check("independent: audio A -> B", ok, f"B={b.state.get(FADER)}")
    put(PORT_B, FADER, 0.15)
    ok = await wait_for(lambda: close(a.state.get(FADER), 0.15), 3)
    check("independent: audio B -> A", ok, f"A={a.state.get(FADER)}")

    put(PORT_A, SEL, 9)  # screen state must stay local
    await asyncio.sleep(1.2)
    check("independent: A screen state NOT forwarded to B",
          b.state.get(SEL) != 9, f"B sel={b.state.get(SEL)}")
    put(PORT_B, SEL, 3)
    await asyncio.sleep(1.2)
    check("independent: B screen state NOT forwarded to A",
          a.state.get(SEL) != 3, f"A sel={a.state.get(SEL)}")
    check("independent: is_screen_path classification",
          is_screen_path(SEL) and not is_screen_path(FADER))
    await eng.stop()
    tr.close()
    await asyncio.sleep(0.8)

    # ---------- phase 5: runtime mode switch ----------
    print("phase 5: runtime mode switch")
    await align(FADER, 0.25)
    eng, tr = await spawn(make_cfg(sync_mode="mirror"))
    await asyncio.sleep(0.5)

    r = eng.set_mode("single", "a", realign=False)
    check("switch: mirror -> single(a) direction a_to_b",
          r["ok"] and eng.direction == "a_to_b" and eng.sync_mode == "single",
          f"r={r}")
    put(PORT_A, FADER, 0.65)
    ok = await wait_for(lambda: close(b.state.get(FADER), 0.65), 3)
    check("switch: A still drives B after switch", ok, f"B={b.state.get(FADER)}")
    put(PORT_B, FADER, 0.02)  # slave mis-touch after switch
    ok = await wait_for(lambda: close(b.state.get(FADER), 0.65), 3)
    check("switch: B springs back after switch", ok, f"B={b.state.get(FADER)}")

    r = eng.set_mode("single", "b", realign=False)
    check("switch: single(a) -> single(b) direction b_to_a",
          r["ok"] and eng.direction == "b_to_a" and eng.master == "b", f"r={r}")
    put(PORT_B, FADER, 0.75)  # B is master now
    ok = await wait_for(lambda: close(a.state.get(FADER), 0.75), 3)
    check("switch: B drives A after master switch", ok, f"A={a.state.get(FADER)}")
    put(PORT_A, FADER, 0.03)  # A is slave now -> spring back
    ok = await wait_for(lambda: close(a.state.get(FADER), 0.75), 3)
    check("switch: A springs back after master switch", ok, f"A={a.state.get(FADER)}")

    r = eng.set_mode("mirror", "a", realign=False)
    check("switch: back to mirror (both directions)",
          r["ok"] and eng.direction == "both", f"r={r}")
    put(PORT_B, FADER, 0.55)
    ok = await wait_for(lambda: close(a.state.get(FADER), 0.55), 3)
    check("switch: mirror restored (B -> A works again)", ok, f"A={a.state.get(FADER)}")
    check("SYNC_MODES constant intact", SYNC_MODES == ("single", "mirror", "independent"),
          str(SYNC_MODES))

    await eng.stop()
    tr.close()
    user.close()
    a.transport.close()
    b.transport.close()

    print()
    failed = [n for n, ok in results if not ok]
    print(f"result: {'PASS' if not failed else 'FAIL'} ({len(results) - len(failed)}/{len(results)})")
    return 0 if not failed else 1


sys.exit(asyncio.run(main()))
