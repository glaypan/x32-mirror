"""Mock consoles for offline testing of the mirror engine.

MockX32 emulates an X32/M32: /ch/01/mix/01/fader paths with linear 0..1
fader positions. MockWing emulates a WING: /ch/1/fdr paths with dB fader
values and integer mutes, per the official WING OSC protocol.

Both behave like real consoles for the parts the engine relies on:
- reply to /xinfo, keep subscriber list on /renew
- reply reads (message without args) with their current value
- apply incoming writes AND broadcast the change to all subscribers
- optionally auto-move a random fader periodically (simulates the user)
"""

import asyncio
import logging
import random
import time

from .engine import harden_udp_socket, random_fader
from .osc import decode_osc, encode_message

log = logging.getLogger("x32mirror.sim")

FADER_PATHS = [f"/ch/{c:02d}/mix/01/fader" for c in range(1, 9)]
MUTE_PATHS = [f"/ch/{c:02d}/mix/01/on" for c in range(1, 5)]

WING_FADER_PATHS = [f"/ch/{c}/fdr" for c in range(1, 9)]
WING_MUTE_PATHS = [f"/ch/{c}/mute" for c in range(1, 5)]


def _random_db():
    return round(random.uniform(-60.0, 10.0), 2)


class _SelfHealingEndpoint:
    """Mixin: rebuild the datagram endpoint when Windows reports WSAECONNRESET.

    harden_udp_socket() should prevent that error entirely, but if the
    ioctl is unsupported on some Windows build this keeps the mock from
    going deaf: the endpoint is recreated on the same port, so peers keep
    sending to the same address. Subscribers are pruned; they re-subscribe
    via /renew.
    """

    _rebuilding = False

    def _schedule_rebuild(self, exc):
        self.subscribers.clear()
        if self._rebuilding:
            return
        self._rebuilding = True
        try:
            asyncio.get_running_loop().create_task(self._rebuild_endpoint())
        except RuntimeError:
            self._rebuilding = False

    async def _rebuild_endpoint(self):
        try:
            old, self.transport = self.transport, None
            if old is not None:
                old.close()
            await asyncio.sleep(0.05)
            loop = asyncio.get_running_loop()
            self.transport, _ = await loop.create_datagram_endpoint(
                lambda: self, local_addr=(self.host, self.port)
            )
            harden_udp_socket(self.transport)
            log.warning("mock %s endpoint rebuilt after transport error", self.name)
        finally:
            self._rebuilding = False


class MockX32(asyncio.DatagramProtocol, _SelfHealingEndpoint):
    def __init__(self, name: str, host: str, port: int, model="X32"):
        self.name = name
        self.host = host
        self.port = port
        self.model = model
        self.state = {}
        self.subscribers = set()
        self.transport = None
        self.set_count = 0

    async def start(self):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self, local_addr=(self.host, self.port)
        )
        harden_udp_socket(self.transport)
        # seed a full state so the engine's full sync has content
        for p in FADER_PATHS:
            self.state[p] = random_fader()
        for p in MUTE_PATHS:
            self.state[p] = random.randint(0, 1)
        log.info("mock console %s listening on %s:%s", self.name, self.host, self.port)

    def connection_made(self, transport):
        self.transport = transport

    def error_received(self, exc):
        # Windows: a send to a dead subscriber raises WSAECONNRESET and the
        # proactor transport stops reading permanently. harden_udp_socket()
        # prevents this; if it ever fails, rebuild the endpoint (mixin).
        log.debug("mock %s transport error (pruning dead subscribers): %s", self.name, exc)
        self._schedule_rebuild(exc)

    def datagram_received(self, data: bytes, addr):
        try:
            for address, args in decode_osc(data):
                if address == "/xinfo":
                    self.transport.sendto(
                        encode_message("/xinfo", [self.model, "1.15", "mock", self.name]), addr
                    )
                elif address == "/renew":
                    self.subscribers.add(addr)
                elif args:
                    self._apply(address, args)
                else:
                    value = self.state.setdefault(address, 0.0)
                    self.transport.sendto(encode_message(address, [value]), addr)
        except Exception as exc:  # noqa: BLE001
            log.warning("mock %s bad datagram: %s", self.name, exc)

    def _apply(self, address, args):
        old = self.state.get(address)
        new = args[0]
        self.state[address] = new
        self.set_count += 1
        if old != new:
            self._broadcast(address, [new])

    def _broadcast(self, address, args):
        data = encode_message(address, args)
        for sub in list(self.subscribers):
            try:
                self.transport.sendto(data, sub)
            except OSError:
                self.subscribers.discard(sub)  # dead subscriber - drop it

    async def auto_move(self, interval: float):
        while True:
            await asyncio.sleep(interval)
            path = random.choice(FADER_PATHS)
            value = random_fader()
            log.info("user moves %s %s -> %s", self.name, path, value)
            self._apply(path, [value])


class MockWing(asyncio.DatagramProtocol, _SelfHealingEndpoint):
    """WING-family console mock: dB faders (/fdr), int mutes, string names."""

    def __init__(self, name: str, host: str, port: int, model="WING"):
        self.name = name
        self.host = host
        self.port = port
        self.model = model
        self.state = {}
        self.subscribers = set()
        self.transport = None
        self.set_count = 0

    async def start(self):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self, local_addr=(self.host, self.port)
        )
        harden_udp_socket(self.transport)
        for p in WING_FADER_PATHS:
            self.state[p] = _random_db()
        for p in WING_MUTE_PATHS:
            self.state[p] = random.randint(0, 1)
        log.info("mock console %s listening on %s:%s", self.name, self.host, self.port)

    def connection_made(self, transport):
        self.transport = transport

    def error_received(self, exc):
        # Windows: a send to a dead subscriber raises WSAECONNRESET and the
        # proactor transport stops reading permanently. harden_udp_socket()
        # prevents this; if it ever fails, rebuild the endpoint (mixin).
        log.debug("mock %s transport error (pruning dead subscribers): %s", self.name, exc)
        self._schedule_rebuild(exc)

    def datagram_received(self, data: bytes, addr):
        try:
            for address, args in decode_osc(data):
                if address == "/xinfo":
                    self.subscribers.add(addr)  # engine discovery = subscriber too
                    self.transport.sendto(
                        encode_message("/xinfo", [self.model, "1.0", "mock", self.name]), addr
                    )
                elif address == "/renew":
                    self.subscribers.add(addr)
                elif args:
                    self._apply(address, args)
                else:
                    value = self.state.setdefault(address, 0.0)
                    self.transport.sendto(encode_message(address, [value]), addr)
        except Exception as exc:  # noqa: BLE001
            log.warning("mock %s bad datagram: %s", self.name, exc)

    def _apply(self, address, args):
        old = self.state.get(address)
        new = args[0]
        self.state[address] = new
        self.set_count += 1
        if old != new:
            self._broadcast(address, [new])

    def _broadcast(self, address, args):
        data = encode_message(address, args)
        for sub in list(self.subscribers):
            try:
                self.transport.sendto(data, sub)
            except OSError:
                self.subscribers.discard(sub)  # dead subscriber - drop it

    async def auto_move(self, interval: float):
        while True:
            await asyncio.sleep(interval)
            path = random.choice(WING_FADER_PATHS)
            value = _random_db()
            log.info("user moves %s %s -> %s dB", self.name, path, value)
            self._apply(path, [value])


class MockRemoteApp(asyncio.DatagramProtocol):
    """Fake remote control app (Mixing Station / X32-Edit style).

    Talks to the mirror tool exactly like a real iPad/desktop remote app:
    /xinfo discovery, /renew subscription, OSC writes and reads, and
    receives every state change the tool relays.
    """

    def __init__(self, name: str, engine_host: str, engine_port: int):
        self.name = name
        self.engine_host = engine_host
        self.engine_port = engine_port
        self.transport = None
        self.inbox = []          # (address, args) received from the tool
        self.xinfo_reply = None

    async def start(self):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self, local_addr=("127.0.0.1", 0))
        log.info("mock remote app %s ready", self.name)

    def connection_made(self, transport):
        self.transport = transport

    def error_received(self, exc):
        log.warning("mock app %s transport error: %s", self.name, exc)

    def datagram_received(self, data: bytes, addr):
        try:
            for address, args in decode_osc(data):
                if address == "/xinfo":
                    self.xinfo_reply = args
                else:
                    self.inbox.append((address, args))
        except Exception as exc:  # noqa: BLE001
            log.warning("mock app %s bad datagram: %s", self.name, exc)

    def send(self, address, args=()):
        self.transport.sendto(
            encode_message(address, args), (self.engine_host, self.engine_port))

    def clear(self):
        self.inbox.clear()

    async def wait_for(self, address, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for a, args in self.inbox:
                if a == address:
                    return args
            await asyncio.sleep(0.05)
        return None
