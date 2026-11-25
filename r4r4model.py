#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""R4 -> R4 continuations: which wire an R4 continues into, and the switch bits.

An R4 wire a (index ai, starting at column ax, row y) continues into a wire c starting 3 or 4 columns on.  Both are
die-wide given the key (ai, cx - ax, (ax + y) mod 4), the phase of R4 drivers (r4drv_model.json):
  - target: 146 keys over 318 observed continuations (r4r4map.py RCF probes: honoured or "no line", i.e. the switch
    exists; plus corpus routes), every key with a single target;
  - bits: c's driver mux in the LAB 3 columns back along the travel direction, frames +13..+15 (buffer -> R4
    drivers use +13/+14 of the same band).  Leave-one-out over positions (corpus exact solves): 47/50 exact.
Right-going wires (indices 0..16): bits in c's own start column, frames -19..-17 (23 exact solves).
Output: out/r4r4_model.json {"ai|dx|phase": {"c": ci, "bits": [[frame, row], ...] | null, "n": instances}}

  r4r4model.py
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lutpos  # noqa: E402
import routegraph as G  # noqa: E402
import routemap as R  # noqa: E402

OUT = os.path.join(HERE, "out")
NODE = re.compile(r"R4_X(\d+)_Y(\d+)_N0_I(\d+)$")
HOP = re.compile(r"R4_X(\d+)_Y(\d+)_N0_I(\d+)->R4_X(\d+)_Y(\d+)_N0_I(\d+)$")


def drive_lab(ax: int, cx: int) -> int:
    """Column whose frames hold c's driver: 3 columns back from c's start for left-going wires (band +13..+15),
    c's own start column for right-going ones (band -19..-17)."""
    return cx + 3 if cx < ax else cx


def band(ax: int, cx: int) -> tuple:
    return (13, 15) if cx < ax else (-19, -17)


def key(ai: int, ax: int, ay: int, cx: int) -> str:
    return f"{ai}|{cx - ax}|{(ax + ay) % 4}"


def rule_bits(ai: int, dx: int, ph: int, ci: int, tracks: dict):
    """Structural rule for left-going span-4 continuations: rows relative to the target's track t at the driving LAB
    (r4drv_model.json).  Sources 17..24 give sign +1, 25..33 sign -1; the pair is (13, t + s), (14, t + s) for even
    sources below 25 and odd ones above, else (13, t), (15, t + s).  Fits every observed entry (43 keys)."""
    if dx != -4 or not 17 <= ai <= 33:
        return None
    tr = {w: t for t, w in tracks.get((ph + dx + 3) % 4, {}).items()}.get(ci)
    if tr is None:
        return None
    sgn = 1 if ai <= 24 else -1
    if (ai + (ai >= 25)) % 2 == 0:
        return [[13, tr + sgn], [14, tr + sgn]]
    return [[13, tr], [15, tr + sgn]]


def build() -> dict:
    target = collections.defaultdict(collections.Counter)
    bits = collections.defaultdict(collections.Counter)
    p = os.path.join(OUT, "r4r4map.json")
    for out in (json.load(open(p)).values() if os.path.exists(p) else []):
        for k, v in out.items():
            if v["status"] in ("honoured", "no line"):
                a, c = k.split("|")
                ma, mc = NODE.match(a), NODE.match(c)
                target[key(int(ma[3]), int(ma[1]), int(ma[2]), int(mc[1]))][int(mc[3])] += 1
    for k, (ny, _nn, b) in json.load(open(os.path.join(OUT, "hopsolve.json"))).items():
        m = HOP.match(k)
        if not m or m[2] != m[5]:
            continue
        ax, ay, ai, cx, _cy, ci = map(int, m.groups())
        kk = key(ai, ax, ay, cx)
        target[kk][ci] += 1
        f0, l0 = R._col_frame(drive_lab(ax, cx)), R._row_index(ay)
        if ny < 2 or f0 is None or l0 is None:
            continue
        lo, hi = band(ax, cx)
        rel = frozenset((f - f0, p_ + lutpos.PLANE_START[pl] - l0) for f, p_, pl in b
                        if lo <= f - f0 <= hi and abs(p_ + lutpos.PLANE_START[pl] - l0) < 80)
        if rel:
            bits[kk][(ax, ay, rel)] += 1
    d = json.load(open(os.path.join(OUT, "r4drv_model.json")))
    tracks = {int(ph): {int(t): w for t, w in m.items()} for ph, m in d["tracks"].items()}
    model = {}
    for kk, cnt in target.items():
        (ci, _n), = cnt.most_common(1)
        if len(cnt) > 1:
            print(f"  {kk}: several targets {dict(cnt)}; kept {ci}")
        bc = bits.get(kk)
        # an exact solve can keep stray bits of hops that co-occur with this one: take the bits common to every
        # instance, and from a single instance only an exact pair (a driver is a bit pair)
        # The intersection needs instances at two or more positions (at one position a co-occurring hop's bit
        # survives it), and a driver pair lies on adjacent rows.
        b = None
        if bc:
            inst = [r for (_x, _y, r) in bc.elements()]
            npos = len({(x, y) for x, y, _r in bc})
            common = frozenset.intersection(*inst)
            b = (common if npos >= 2 and common else inst[0] if len(set(inst)) == 1 and len(inst[0]) == 2 else None)
            if b and max(l for _f, l in b) - min(l for _f, l in b) > 1:
                b = None
        ai, dx, ph = map(int, kk.split("|"))
        rb = rule_bits(ai, dx, ph, ci, tracks)
        if b and rb and not set(map(tuple, b)) <= set(map(tuple, rb)):
            print(f"  {kk}: measured {sorted(b)} not within the rule's {rb}")
        model[kk] = dict(c=ci, bits=sorted(map(list, b)) if b and not (rb and len(b) < 2) else rb,
                         n=sum(bc.values()) if bc else 0, rule=bool(rb) and not (b and len(b) >= 2))
    return model


TRAIN = ("xrkn_w2w_jobs.json", "xrkn_w2w2_jobs.json")


def validate(model: dict) -> int:
    """Drop entries whose bits aren't all set in some training build that uses the hop (a bit that depends on more
    than the key, e.g. 9|4|2's (-17, -40): set in 20 positions, clear in 2).  Returns the number dropped."""
    import routes
    import xdev
    bad = set()
    for jf in TRAIN:
        for name in json.load(open(os.path.join(OUT, jf))):
            buf = xdev.load(OUT, name)
            for u, v in routes.pips(json.load(open(os.path.join(OUT, name + ".route.json")))):
                mu, mv = NODE.match(u), NODE.match(v)
                if not mu or not mv or mu[2] != mv[2]:
                    continue
                ax, ay, cx = int(mu[1]), int(mu[2]), int(mv[1])
                kk = key(int(mu[3]), ax, ay, cx)
                e = model.get(kk)
                if not e or not e["bits"] or e["c"] != int(mv[3]):
                    continue
                f0, l0 = R._col_frame(drive_lab(ax, cx)), R._row_index(ay)
                if f0 is None or l0 is None:
                    continue
                for f, l in e["bits"]:
                    c = G.cell_of(f0 + f, l0 + l)
                    if c is None or not buf[32 + c[0] * 255 + c[1]] >> c[2] & 1:
                        bad.add(kk)
    for kk in bad:
        print(f"  {kk}: bits {model[kk]['bits']} not set in every use; dropped")
        model[kk]["bits"] = None
    return len(bad)


def main() -> int:
    m = build()
    validate(m)
    json.dump(m, open(os.path.join(OUT, "r4r4_model.json"), "w"), indent=0, sort_keys=True)
    print(f"{len(m)} continuation keys, {sum(1 for v in m.values() if v['bits'])} with bits -> out/r4r4_model.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
