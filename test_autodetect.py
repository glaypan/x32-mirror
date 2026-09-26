"""E2E test for driver auto-detection: mocks + engine(driver=auto) + probe."""
import asyncio
import logging
import sys
import threading
import time

logging.basicConfig(level=logging.WARNING, format="%(message)s")

from x32mirror.drivers import detect_console_sync, identify_model
from x32mirror.engine import MirrorEngine
from x32mirror.simulator import MockWing, MockX32

results = {}


def run_mocks(ready: threading.Event):
    async def m():
        a = MockX32("A", "127.0.0.1", 11023)              # replies model X32
        w = MockWing("B", "127.0.0.1", 12223)             # replies model WING
        await a.start()
        await w.start()
        ready.set()
        await asyncio.Event().wait()
    asyncio.run(m())


async def engine_flow():
    cfg = {
        "listen_host": "127.0.0.1",
        "listen_port": 19093,
        "direction": "both",
        "full_sync": True,
        "full_sync_from": "a",
        "oplog_db": None,
        "consoles": {
            "a": {"name": "mock-A", "host": "127.0.0.1", "port": 11023, "driver": "auto"},
            "b": {"name": "mock-B", "host": "127.0.0.1", "port": 12223, "driver": "auto"},
        },
    }
    eng = MirrorEngine(cfg)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: eng, local_addr=("127.0.0.1", cfg["listen_port"]))
    await eng.start()
    await asyncio.sleep(5.0)  # autodetect + renew + full sync (1060 paths ~2.5s)
    results["drv_a"] = eng.drv_a.key
    results["drv_b"] = eng.drv_b.key
    results["pairmap"] = eng.pairmap_ab is not None
    results["sync_paths"] = len(eng.sync_paths)
    results["stats"] = dict(eng.stats)
    await eng.stop()
    transport.close()


def main():
    ready = threading.Event()
    threading.Thread(target=run_mocks, args=(ready,), daemon=True).start()
    ready.wait(5)
    time.sleep(0.3)

    # 1. unit: model string -> driver key
    results["identify_x32"] = identify_model("X32 4.06 mock") == "x32"
    results["identify_m32"] = identify_model("M32R LIVE 1.15") == "m32"
    results["identify_wing"] = identify_model("WING 1.0 mock") == "wing"
    results["identify_unknown"] = identify_model("SQ-6 1.9") is None

    # 2. blocking probe against mocks (port hint first, then standard ports)
    key, model, port = detect_console_sync("127.0.0.1", 2.5, [11023])
    results["probe_x32"] = key == "x32" and port == 11023
    key2, model2, port2 = detect_console_sync("127.0.0.1", 2.5, [12223])
    results["probe_wing"] = key2 == "wing" and port2 == 12223
    key3, _, _ = detect_console_sync("127.0.0.1", 1.0, [19999])
    results["probe_dead"] = key3 is None

    # 3. engine with driver=auto on both sides
    asyncio.run(engine_flow())
    results["engine_detected"] = results["drv_a"] == "x32" and results["drv_b"] == "wing"
    results["engine_mapping"] = results["pairmap"] is True

    flags = [v for v in results.values() if isinstance(v, bool)]
    ok = all(flags) and results["engine_detected"] and results["engine_mapping"] and \
        results["probe_x32"] and results["probe_wing"] and results["probe_dead"]
    for k, v in results.items():
        print(f"  {k}: {v}")
    print("result:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
