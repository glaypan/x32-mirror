"""Minimal OSC 1.0 codec (stdlib only).

Supports messages with f/i/s/b/T/F arguments and #bundle containers,
which covers everything the Behringer X32/M32 remote protocol uses
(including /meters/... blob payloads).
"""

import struct


def _pad(data: bytes) -> bytes:
    return data + b"\x00" * ((4 - len(data) % 4) % 4)


def _tag(value) -> bytes:
    if isinstance(value, bool):
        return b"T" if value else b"F"
    if isinstance(value, float):
        return b"f"
    if isinstance(value, int):
        return b"i"
    if isinstance(value, str):
        return b"s"
    if isinstance(value, (bytes, bytearray)):
        return b"b"
    raise TypeError(f"unsupported OSC argument type: {type(value)!r}")


def encode_message(address: str, args=()) -> bytes:
    data = _pad(address.encode("utf-8") + b"\x00")
    tags = b"," + b"".join(_tag(v) for v in args)
    data += _pad(tags + b"\x00")
    for v in args:
        if isinstance(v, bool):
            continue  # T/F tags carry no payload
        if isinstance(v, float):
            data += struct.pack(">f", v)
        elif isinstance(v, int):
            data += struct.pack(">i", v)
        elif isinstance(v, str):
            data += _pad(v.encode("utf-8") + b"\x00")
        elif isinstance(v, (bytes, bytearray)):
            data += _pad(struct.pack(">I", len(v)) + bytes(v))
    return data


def _read_padded(data: bytes, offset: int):
    end = data.index(b"\x00", offset)
    chunk = data[offset:end]
    next_offset = offset + ((end - offset + 1 + 3) // 4) * 4
    return chunk, next_offset


def decode_osc(data: bytes):
    """Decode one datagram into a list of (address, args) tuples."""
    out = []
    _decode_element(data, 0, out)
    return out


def _decode_element(data: bytes, offset: int, out: list):
    addr, offset = _read_padded(data, offset)
    if addr == b"#bundle":
        offset += 8  # timetag
        while offset + 4 <= len(data):
            (size,) = struct.unpack_from(">I", data, offset)
            offset += 4
            if size == 0:
                break
            _decode_element(data, offset, out)
            offset += size
        return
    args = []
    if offset < len(data) and data[offset : offset + 1] == b",":
        tags, offset = _read_padded(data, offset)
        for t in tags[1:]:
            if t == ord("f"):
                (v,) = struct.unpack_from(">f", data, offset)
                offset += 4
                args.append(v)
            elif t == ord("i"):
                (v,) = struct.unpack_from(">i", data, offset)
                offset += 4
                args.append(v)
            elif t == ord("s"):
                s, offset = _read_padded(data, offset)
                args.append(s.decode("utf-8"))
            elif t == ord("b"):
                (size,) = struct.unpack_from(">I", data, offset)
                offset += 4
                args.append(bytes(data[offset : offset + size]))
                offset += ((size + 3) // 4) * 4
            elif t == ord("T"):
                args.append(True)
            elif t == ord("F"):
                args.append(False)
            else:
                raise ValueError(f"unsupported OSC type tag: {chr(t)!r}")
    out.append((addr.decode("utf-8"), args))
