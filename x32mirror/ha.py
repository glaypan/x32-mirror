"""Two-node hot-standby coordination over UDP heartbeats + manual switch.

Each node sends a small JSON heartbeat to its peer once per second.
Election rule (auto): the node with the earlier start timestamp (tie-break:
node id) becomes ACTIVE and runs the forwarding engine; the other one
stays STANDBY - still subscribed to both consoles and still logging
every change to its own op-log (real-time backup), but never writing
to the consoles. When the active node dies (no heartbeat for
`failover_s` seconds), the standby takes over automatically.

Manual switch (from the CLI `ha-switch` command, via UDP datagrams to
the node's HA port):
- promote  -> the node bumps its `epoch` above the peer's and becomes
  ACTIVE immediately; it keeps leadership over the auto-elected peer.
  Not persisted: after a restart the node returns to auto election.
- demote   -> the node gives up leadership (epoch reset to 0) and stays
  STANDBY while the peer is alive. Safety net: if the peer later dies,
  it resumes ACTIVE after `auto_resume_s` so the mirror never stays
  down forever.
- status   -> replies with the current role/epoch/peer for operators.

Note: after a crashed primary restarts it gets a NEW start timestamp,
so it comes back as standby and does not preempt the node that took
over - this prevents split-brain flapping.
"""

import asyncio
import json
import logging
import time

log = logging.getLogger("x32mirror.ha")


class HANode(asyncio.DatagramProtocol):
    def __init__(self, node_id, peer_host, port=49900, local_port=None,
                 failover_s=3.0, auto_resume_s=30.0, on_change=None):
        self.node_id = node_id
        self.peer_host = peer_host
        self.port = int(port)
        self.local_port = int(local_port or port)
        self.failover_s = float(failover_s)
        self.auto_resume_s = float(auto_resume_s)
        self.on_change = on_change or (lambda active: None)
        self.start_ts = time.time()
        self.epoch = 0
        self.force = "auto"  # "auto" | "promote" | "demote"
        self.active = False
        self.transport = None
        self._peer = None                # {"id","start","epoch","active","seen"}
        self._peer_inactive_since = None
        self._task = None
        self._closed = False

    # ---- transport callbacks --------------------------------------
    def connection_made(self, transport):
        self.transport = transport

    def error_received(self, exc):
        log.warning("ha transport error: %s", exc)

    def datagram_received(self, data, addr):
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            return
        if msg.get("app") != "x32mirror":
            return
        if "cmd" in msg:
            self.handle_command(msg, addr)
            return
        if msg.get("id") == self.node_id:
            return
        now = time.monotonic()
        pid = msg.get("id")
        pstart = float(msg.get("start", 0))
        if (self._peer and self._peer.get("id") == pid
                and self._peer.get("start") == pstart):
            self._peer.update(
                active=bool(msg.get("active")),
                epoch=int(msg.get("epoch", 0)),
                seen=now,
            )
        else:
            # new peer or restarted node (start_ts changed): fresh entry so
            # the restarted node does NOT inherit its old start priority
            self._peer = {
                "id": pid,
                "start": pstart,
                "epoch": int(msg.get("epoch", 0)),
                "active": bool(msg.get("active")),
                "seen": now,
            }
        if self._peer["active"]:
            self._peer_inactive_since = None
        elif self._peer_inactive_since is None:
            self._peer_inactive_since = now

    # ---- manual switch ----------------------------------------------
    def handle_command(self, msg, addr):
        cmd = msg.get("cmd")
        if cmd == "promote":
            peer_epoch = self._peer["epoch"] if self._peer else 0
            self.epoch = max(self.epoch, peer_epoch + 1)
            self.force = "promote"
            log.warning("HA manual PROMOTE on %s (epoch=%d)", self.node_id, self.epoch)
            self._evaluate()
        elif cmd == "demote":
            self.epoch = 0
            self.force = "demote"
            log.warning("HA manual DEMOTE on %s (epoch reset, yields to peer)", self.node_id)
            self._evaluate()
        elif cmd == "status":
            pass
        else:
            return
        reply = {
            "app": "x32mirror",
            "ack": cmd,
            "id": self.node_id,
            "active": self.active,
            "force": self.force,
            "epoch": self.epoch,
            "peer": ({"id": self._peer["id"], "active": self._peer["active"]}
                     if self._peer else None),
        }
        try:
            self.transport.sendto(json.dumps(reply).encode("utf-8"), addr)
        except Exception as exc:  # noqa: BLE001
            log.warning("ha reply failed: %s", exc)

    # ---- lifecycle --------------------------------------------------
    async def start(self):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self, local_addr=("0.0.0.0", self.local_port))
        self._task = asyncio.create_task(self._beat_loop())

    async def stop(self):
        self._closed = True
        if self._task:
            self._task.cancel()
        if self.transport:
            self.transport.close()

    # ---- election -----------------------------------------------------
    def _i_win(self):
        if self._peer is None:
            return True
        pe = self._peer.get("epoch", 0)
        if pe != self.epoch:
            return self.epoch > pe
        return (self.start_ts, self.node_id) < (self._peer["start"], self._peer["id"])

    def _peer_live(self):
        return (self._peer is not None
                and time.monotonic() - self._peer["seen"] < self.failover_s)

    def _should_be_active(self):
        if self.force == "promote":
            return True  # operator insisted
        if self.force == "demote":
            if self._peer_live():
                return False  # peer can serve: stay standby as asked
            if self._peer is None:
                return True
            # peer gone: resume after the safety window so the mirror
            # never stays down forever
            return time.monotonic() - self._peer["seen"] > self.auto_resume_s
        # --- auto election ---
        if not self._peer_live():
            return True               # peer silent/dead -> take over
        if self._i_win():
            return True               # I outrank the peer
        # peer is live and outranks me
        if self._peer["active"]:
            return False              # normal hot-standby: peer works
        # peer outranks me but sits inactive; grace period, then take over
        grace = 2 * self.failover_s
        return (self._peer_inactive_since is not None
                and time.monotonic() - self._peer_inactive_since > grace)

    def _evaluate(self):
        want = self._should_be_active()
        if want != self.active:
            self.active = want
            log.warning("HA election: node %s -> %s", self.node_id,
                        "ACTIVE" if want else "STANDBY")
            self.on_change(want)

    async def _beat_loop(self):
        while not self._closed:
            try:
                self.transport.sendto(self._make_payload(), (self.peer_host, self.port))
            except Exception as exc:  # noqa: BLE001
                log.warning("ha send failed: %s", exc)
            await asyncio.sleep(1.0)
            self._evaluate()

    def _make_payload(self):
        return json.dumps({
            "app": "x32mirror",
            "id": self.node_id,
            "start": self.start_ts,
            "epoch": self.epoch,
            "active": self.active,
        }).encode("utf-8")
