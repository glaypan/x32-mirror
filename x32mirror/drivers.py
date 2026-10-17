"""Console driver registry.

Each entry describes how to talk to one console family. The mirror engine
is transport-agnostic; a driver provides: transport kind, remote port,
keep-alive path (if the protocol needs subscription renewal), fader value
unit (for future cross-brand value mapping) and the default full-sync
path table.

Status legend:
  ready        - verified against the protocol docs, engine can drive it today
  experimental - OSC-based, engine can drive it but subscription/keep-alive
                 details need on-hardware confirmation
  planned      - protocol identified and researched, driver not implemented
  limited      - no full-state remote protocol exists; only partial control
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional


def _paths_behringer_x32() -> List[str]:
    """Full X32/M32 mirror coverage (same family, paths pass through verbatim).

    Covers: channel/bus/aux/fxret/DCA/main faders+mutes, channel & bus pans,
    bus sends (ch->bus and bus->bus levels), headamp gain +48V, mute groups,
    solo level/mute, channel names. Scenes sync via /goto & /load passthrough.
    """
    paths = []
    # headamp (preamp gain + phantom per channel)
    for ch in range(1, 33):
        paths += [f"/headamp/{ch:02d}/gain", f"/headamp/{ch:02d}/phantom"]
    # channel strip: fader / mute / name / pan + 16 bus sends
    for ch in range(1, 33):
        paths += [
            f"/ch/{ch:02d}/mix/01/fader",
            f"/ch/{ch:02d}/mix/01/on",
            f"/ch/{ch:02d}/config/name",
            f"/ch/{ch:02d}/mix/pan",
        ]
        for b in range(1, 17):
            paths.append(f"/ch/{ch:02d}/mix/{b:02d}/level")
    # bus masters: fader / mute / pan + bus-to-bus sends
    for b in range(1, 17):
        paths += [f"/bus/{b:02d}/mix/01/fader", f"/bus/{b:02d}/mix/01/on",
                  f"/bus/{b:02d}/mix/pan"]
        for b2 in range(1, 17):
            paths.append(f"/bus/{b:02d}/mix/{b2:02d}/level")
    # aux in / fx returns
    for a in range(1, 7):
        paths += [f"/aux/{a:02d}/mix/01/fader", f"/aux/{a:02d}/mix/01/on",
                  f"/aux/{a:02d}/mix/pan"]
    for r in range(1, 5):
        paths += [f"/fxret/{r:02d}/mix/01/fader", f"/fxret/{r:02d}/mix/01/on"]
    # DCA + main
    for d in range(1, 9):
        paths += [f"/dca/{d}/fader", f"/dca/{d}/on"]
    paths += ["/main/st/mix/01/fader", "/main/st/mix/01/on"]
    # mute groups + solo
    for m in range(1, 7):
        paths.append(f"/config/mutegroup/{m:02d}/on")
    paths += ["/config/solo/level", "/config/solo/mute"]
    # screen/UI state: selected channel + per-channel solo switches.
    # Followed in mirror mode, kept local in "independent" mode
    # (see engine.is_screen_path).
    paths.append("-stat/selidx")
    for s in range(1, 33):
        paths.append(f"-stat/solosw/{s:02d}")
    return paths


def _paths_wing() -> List[str]:
    # WING OSC official docs: fader is "/fdr" carrying dB floats (-144 = -inf),
    # mute is an integer 0/1, name is the scribble-strip string.
    paths = []
    for ch in range(1, 41):
        paths += [f"/ch/{ch}/fdr", f"/ch/{ch}/mute", f"/ch/{ch}/name"]
    for b in range(1, 17):
        paths += [f"/bus/{b}/fdr", f"/bus/{b}/mute"]
    for d in range(1, 17):
        paths += [f"/dca/{d}/fdr", f"/dca/{d}/mute"]
    for m in range(1, 5):
        paths += [f"/main/{m}/fdr", f"/main/{m}/mute"]
    # screen/UI state (same -stat/ family as X32): selected channel + solo
    # switches - followed in mirror mode, kept local in "independent" mode
    # (see engine.is_screen_path)
    paths.append("-stat/selidx")
    for s in range(1, 41):
        paths.append(f"-stat/solosw/{s}")
    return paths


@dataclass
class DriverSpec:
    key: str
    brand: str
    models: str
    transport: str                     # osc-udp | tcp-rcp | tcp-midi | none
    port: Optional[int]
    renew_path: Optional[str]          # keep-alive for change subscription
    fader_unit: str                    # linear-0-1 | db | db-x100 | unknown
    status: str                        # ready | experimental | planned | limited
    note: str
    build_paths: Optional[Callable[[], List[str]]] = None

    def sync_paths(self) -> List[str]:
        return self.build_paths() if self.build_paths else []


DRIVERS = {
    "x32": DriverSpec(
        key="x32", brand="Behringer", models="X32 / X32 Producer / Compact / Rack",
        transport="osc-udp", port=10023, renew_path="/renew",
        fader_unit="linear-0-1", status="ready",
        note="OSC 协议稳定，/renew 每 9s 续订变更推送",
        build_paths=_paths_behringer_x32,
    ),
    "m32": DriverSpec(
        key="m32", brand="Midas", models="M32 / M32R / M32 Live",
        transport="osc-udp", port=10023, renew_path="/renew",
        fader_unit="linear-0-1", status="ready",
        note="与 X32 同协议同端口，路径基本一致（effects/config 区有差异，可经 extra_sync_paths 校准）",
        build_paths=_paths_behringer_x32,
    ),
    "wing": DriverSpec(
        key="wing", brand="Behringer", models="WING / WING Compact / WING Rack",
        transport="osc-udp", port=2223, renew_path=None,
        fader_unit="db", status="experimental",
        note="官方授权 OSC 文档完整（wing-docs.com）；推子 /fdr 为 dB（-144=-inf），静音 int；"
             "与 X32 的互镜像经规范映射层（mapping.py）换算；接入真机时需按文档实装订阅推送",
        build_paths=_paths_wing,
    ),
    "sq": DriverSpec(
        key="sq", brand="Allen & Heath", models="SQ-5/6/7 / SQ-5A",
        transport="tcp-midi", port=51325, renew_path=None,
        fader_unit="unknown", status="planned",
        note="官方 MIDI over TCP（NRPN/CC，含场景与电平），Crestron/AMX 官方驱动同源；"
             "需实现 MIDI-over-TCP 编解码 + 参数映射",
    ),
    "qu": DriverSpec(
        key="qu", brand="Allen & Heath", models="Qu-16/24/32 / Qu-SB",
        transport="tcp-midi", port=51325, renew_path=None,
        fader_unit="unknown", status="planned",
        note="经典 Qu 走 CMNet（UDP，社区逆向，Mixing Station 同源）+ MIDI over TCP；逐机型实测后定",
    ),
    "dlive": DriverSpec(
        key="dlive", brand="Allen & Heath", models="dLive / Avantis",
        transport="tcp-midi", port=51325, renew_path=None,
        fader_unit="unknown", status="planned",
        note="MIDI over TCP（官方 External Control 文档）；覆盖电平/静音/场景，参数映射工作量中等",
    ),
    "yamaha-rcp": DriverSpec(
        key="yamaha-rcp", brand="Yamaha", models="TF / CL / QL / DM3",
        transport="tcp-rcp", port=None, renew_path=None,
        fader_unit="db-x100", status="planned",
        note="RCP 文本协议 over TCP：get/set/ssrecall_ex，NOTIFY 主动推送；"
             "dB×100 整数（-inf=-32768）；参考 BrenekH/yamaha-rcp-docs + 官方 RCP 规格；端口逐机型实测",
    ),
    "yamaha-osc": DriverSpec(
        key="yamaha-osc", brand="Yamaha", models="RIVAGE PM / DM3",
        transport="osc-udp", port=None, renew_path=None,
        fader_unit="db", status="planned",
        note="官方发布过 OSC Specifications（PM V1.0.2 / DM3 V1.0.0），按规格实装",
    ),
    "digico": DriverSpec(
        key="digico", brand="DiGiCo", models="SD / Quantum / S 系列",
        transport="none", port=None, renew_path=None,
        fader_unit="unknown", status="limited",
        note="整机状态无公开远程协议；Generic OSC 仅为每通道 8 旋钮+8 开关的外控，"
             "且不支持轮询，无法做实时整机镜像。退化为 session 文件级备份（离线导出/导入/对比）",
    ),
    "soundcraft": DriverSpec(
        key="soundcraft", brand="Soundcraft", models="Vi / Si / Ui 系列",
        transport="none", port=None, renew_path=None,
        fader_unit="unknown", status="planned",
        note="Vi/Si 以 MIDI/专有协议为主，Ui 系为 HTTP/OSC 混合；需按具体型号调研",
    ),
    "presonus": DriverSpec(
        key="presonus", brand="PreSonus", models="StudioLive 系列",
        transport="none", port=None, renew_path=None,
        fader_unit="unknown", status="planned",
        note="UCNet 为闭源 TCP；社区有逆向成果，覆盖率需逐型号验证",
    ),
}


def detect_console_sync(host: str, timeout: float = 2.0, extra_ports=()):
    """Blocking wrapper around detect_console for GUI/web threads."""
    import asyncio
    try:
        return asyncio.run(detect_console(host, timeout, extra_ports))
    except Exception:  # noqa: BLE001
        return None, None, None


def get_driver(key: str) -> DriverSpec:
    return DRIVERS.get(key, DRIVERS["x32"])


# ---- automatic detection -----------------------------------------------

# Probe ports for UDP-OSC drivers, most likely first. TCP-protocol drivers
# (planned status) are excluded: they cannot be probed with a bare /xinfo.
_PROBE_ORDER = ["x32", "m32", "wing"]
_PROBE_PORTS = {10023, 2223}

_MODEL_KEYWORDS = [
    ("X32", "x32"),
    ("M32", "m32"),
    ("WING", "wing"),
]


def identify_model(text: str) -> Optional[str]:
    """Map an /xinfo model string to a driver key (None if unknown)."""
    up = (text or "").upper()
    for kw, key in _MODEL_KEYWORDS:
        if kw in up:
            return key
    return None


async def detect_console(host: str, timeout: float = 2.0, extra_ports=()):
    """Probe a console over UDP OSC and identify its driver.

    Sends /xinfo to the given ports plus the standard remote ports and
    inspects the reply's model string. Returns (driver_key, model_string,
    port) or (None, None, None).
    """
    import socket as _socket
    import time as _time

    from .osc import decode_osc, encode_message

    payload = encode_message("/xinfo", [])
    ports = []
    for p in list(extra_ports) + sorted(_PROBE_PORTS):
        p = int(p)
        if p not in ports:
            ports.append(p)
    per_port = max(0.3, timeout / len(ports))
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    s.setblocking(True)
    try:
        for port in ports:
            try:
                s.sendto(payload, (host, port))
            except OSError:
                continue
            end = _time.monotonic() + per_port
            while True:
                remain = end - _time.monotonic()
                if remain <= 0:
                    break
                s.settimeout(remain)
                try:
                    data, addr = s.recvfrom(4096)
                except (_socket.timeout, OSError):
                    break
                try:
                    for path, args in decode_osc(data):
                        if path == "/xinfo" and args:
                            model = " ".join(str(a) for a in args)
                            key = identify_model(model)
                            if key:
                                return key, model, addr[1]
                except Exception:  # noqa: BLE001
                    pass
    finally:
        s.close()
    return None, None, None
