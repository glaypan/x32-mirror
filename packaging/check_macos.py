"""Verify a macOS bundle's minimum system version (pure stdlib).

    python packaging/check_macos.py <folder-or-.app> [--max 10.14]

Reads LC_BUILD_VERSION / LC_VERSION_MIN_MACOSX from every Mach-O file and
checks the x86_64 slice (universal binaries also carry an arm64 slice whose
minimum is irrelevant here). Exits non-zero when anything needs a newer OS.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

MACHO_MAGICS = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


def _ver(value: int) -> tuple[int, int, int]:
    return (value >> 16) & 0xFFFF, (value >> 8) & 0xFF, value & 0xFF


def _thin_minos(data: bytes, base: int):
    magic = struct.unpack_from("<I", data, base)[0]
    if magic not in (0xFEEDFACF, 0xFEEDFACE):
        return None
    off = base + (32 if magic == 0xFEEDFACF else 28)
    ncmds = struct.unpack_from("<I", data, base + 16)[0]
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd == 0x32 and struct.unpack_from("<I", data, off + 8)[0] == 1:
            return _ver(struct.unpack_from("<I", data, off + 12)[0])
        if cmd == 0x24:
            return _ver(struct.unpack_from("<I", data, off + 8)[0])
        off += size
    return None


def min_version(path: str):
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 8 or data[:4] not in MACHO_MAGICS:
        return None
    if data[:4] == b"\xca\xfe\xba\xbe":
        count = struct.unpack_from(">I", data, 4)[0]
        for i in range(count):
            cpu = struct.unpack_from(">I", data, 8 + i * 20)[0]
            off = struct.unpack_from(">I", data, 8 + i * 20 + 8)[0]
            if cpu == 0x01000007:  # x86_64
                return _thin_minos(data, off)
        return None
    return _thin_minos(data, 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--max", default="10.14")
    args = ap.parse_args()
    limit = tuple(int(x) for x in args.max.split("."))

    found = []
    for base, _dirs, files in os.walk(args.root):
        for name in files:
            path = os.path.join(base, name)
            try:
                v = min_version(path)
            except Exception:  # noqa: BLE001
                continue
            if v:
                found.append((v, os.path.relpath(path, args.root)))

    if not found:
        print("no Mach-O files found under", args.root)
        return 2
    worst = max(found, key=lambda x: x[0])
    print(f"{len(found)} Mach-O file(s); highest minimum macOS: "
          f"{'.'.join(map(str, worst[0]))} ({worst[1]})")
    bad = [f for f in found if f[0] > limit]
    for v, name in bad[:10]:
        print("  TOO NEW:", ".".join(map(str, v)), name)
    if bad:
        print(f"FAIL: {len(bad)} file(s) require newer than {args.max}")
        return 1
    print(f"OK: all files run on macOS {args.max} or older")
    return 0


if __name__ == "__main__":
    sys.exit(main())
