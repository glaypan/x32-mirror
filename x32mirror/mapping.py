"""Canonical parameter mapping between console driver families.

A canonical parameter is (family, num, kind):
    family in {ch, aux, bus, dca, main}
    kind   in {fader, mute, name}

Canonical value units:
    fader -> dB (float); None means -inf (fully down)
    mute  -> int 0/1
    name  -> str

X32/M32 fader position (0..1) <-> dB uses the official piecewise-linear
curve (anchors verified across X32 wiki / Bitfocus Companion module):
    0.0 -> -oo | 0.0625 -> -60 | 0.25 -> -30 | 0.5 -> -10 | 0.75 -> 0 | 1.0 -> +10
WING fader natively carries dB floats; -144 dB represents -inf.
"""

import re
from typing import List, Optional, Tuple

Param = Tuple[str, int, str]

# ---------------------------------------------------------------- X32/M32

def _x32_pos_to_db(f: float) -> Optional[float]:
    if f <= 0.0:
        return None
    if f <= 0.0625:
        return f * 480 - 90
    if f <= 0.25:
        return f * 160 - 70
    if f <= 0.5:
        return f * 80 - 50
    return f * 40 - 30


def _db_to_x32_pos(db: Optional[float]) -> float:
    if db is None:
        return 0.0
    if db >= -10:
        f = (db + 30) / 40
    elif db >= -30:
        f = (db + 50) / 80
    elif db >= -60:
        f = (db + 70) / 160
    else:
        f = (db + 90) / 480
    return min(1.0, max(0.0, f))


# rules: (regex, canonical template, path template, max_n or None for fixed)
_X32_RULES = [
    (re.compile(r"^/ch/(\d+)/mix/01/fader$"), ("ch", "fader"), "/ch/{n:02d}/mix/01/fader", 32),
    (re.compile(r"^/ch/(\d+)/mix/01/on$"), ("ch", "mute"), "/ch/{n:02d}/mix/01/on", 32),
    (re.compile(r"^/ch/(\d+)/config/name$"), ("ch", "name"), "/ch/{n:02d}/config/name", 32),
    (re.compile(r"^/bus/(\d+)/mix/01/fader$"), ("bus", "fader"), "/bus/{n:02d}/mix/01/fader", 16),
    (re.compile(r"^/bus/(\d+)/mix/01/on$"), ("bus", "mute"), "/bus/{n:02d}/mix/01/on", 16),
    (re.compile(r"^/dca/(\d+)/fader$"), ("dca", "fader"), "/dca/{n}/fader", 8),
    (re.compile(r"^/dca/(\d+)/on$"), ("dca", "mute"), "/dca/{n}/on", 8),
    (re.compile(r"^/main/st/mix/01/fader$"), ("main", "fader"), "/main/st/mix/01/fader", None),
    (re.compile(r"^/main/st/mix/01/on$"), ("main", "mute"), "/main/st/mix/01/on", None),
]

# ------------------------------------------------------------------- WING

_WING_RULES = [
    (re.compile(r"^/ch/(\d+)/fdr$"), ("ch", "fader"), "/ch/{n}/fdr", 40),
    (re.compile(r"^/ch/(\d+)/mute$"), ("ch", "mute"), "/ch/{n}/mute", 40),
    (re.compile(r"^/ch/(\d+)/name$"), ("ch", "name"), "/ch/{n}/name", 40),
    (re.compile(r"^/aux/(\d+)/fdr$"), ("aux", "fader"), "/aux/{n}/fdr", 8),
    (re.compile(r"^/aux/(\d+)/mute$"), ("aux", "mute"), "/aux/{n}/mute", 8),
    (re.compile(r"^/aux/(\d+)/name$"), ("aux", "name"), "/aux/{n}/name", 8),
    (re.compile(r"^/bus/(\d+)/fdr$"), ("bus", "fader"), "/bus/{n}/fdr", 16),
    (re.compile(r"^/bus/(\d+)/mute$"), ("bus", "mute"), "/bus/{n}/mute", 16),
    (re.compile(r"^/dca/(\d+)/fdr$"), ("dca", "fader"), "/dca/{n}/fdr", 16),
    (re.compile(r"^/dca/(\d+)/mute$"), ("dca", "mute"), "/dca/{n}/mute", 16),
    (re.compile(r"^/main/(\d+)/fdr$"), ("main", "fader"), "/main/{n}/fdr", 4),
    (re.compile(r"^/main/(\d+)/mute$"), ("main", "mute"), "/main/{n}/mute", 4),
]

# ------------------------------------------------------------- family maps

class FamilyMap:
    def __init__(self, name, rules, fader_to_db, db_to_fader):
        self.name = name
        self.rules = rules
        self._fader_to_db = fader_to_db
        self._db_to_fader = db_to_fader

    def parse(self, path: str) -> Optional[Param]:
        for rx, key, _tmpl, max_n in self.rules:
            m = rx.match(path)
            if m:
                if max_n is None:
                    return (key[0], 1, key[1])
                n = int(m.group(1))
                if not 1 <= n <= max_n:
                    return None
                return (key[0], n, key[1])
        return None

    def build(self, key: Param) -> Optional[str]:
        family, n, kind = key
        for _rx, tkey, tmpl, max_n in self.rules:
            if tkey == (family, kind):
                if max_n is not None and not 1 <= n <= max_n:
                    return None
                return tmpl.format(n=n)
        return None

    def fader_to_db(self, value):
        return self._fader_to_db(value)

    def db_to_fader(self, db):
        return self._db_to_fader(db)


def _wing_pos_to_db(v):
    if v is None or v <= -143.5:
        return None
    return float(v)


def _db_to_wing(db):
    return -144.0 if db is None else float(db)


_X32_MAP = FamilyMap("x32", _X32_RULES, _x32_pos_to_db, _db_to_x32_pos)
_WING_MAP = FamilyMap("wing", _WING_RULES, _wing_pos_to_db, _db_to_wing)

MAP_FAMILY = {"x32": "x32", "m32": "x32", "wing": "wing"}
MAPS = {"x32": _X32_MAP, "wing": _WING_MAP}


class PairMap:
    """Translates native paths/values from one console family to another."""

    def __init__(self, src_family: str, dst_family: str):
        self.src_family = src_family
        self.cross_family = src_family != dst_family
        self.src = MAPS[src_family]
        self.dst = MAPS[dst_family]

    def translate(self, path: str, args: List) -> Optional[Tuple[str, List]]:
        key = self.src.parse(path)
        if key is None:
            # Same family shares the native path space: everything outside the
            # canonical set (sends, pans, headamp, mute groups, scenes /goto
            # & /load, ...) passes through verbatim. Only cross-family pairs
            # are restricted to the canonical parameter table.
            if not self.cross_family:
                return path, list(args)
            return None
        dst_path = self.dst.build(key)
        if dst_path is None:
            return None
        kind = key[2]
        if not args:
            return dst_path, []
        v = args[0]
        if kind == "fader":
            return dst_path, [self.dst.db_to_fader(self.src.fader_to_db(v))]
        if kind == "mute":
            return dst_path, [int(bool(v))]
        return dst_path, [v]  # name / strings pass through
