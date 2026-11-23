#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-physical-input local-line mux selects, from xdev design "mux1" (data only).

dst.dataa takes the selected source (slot a, or slot 30), its other inputs are
pins.  dst's mask (3CEC) identifies its input order in each build, so we know
which physical input p carries the source.  Pairs where p is the same in the
A and B builds give S = M(p <- a) XOR M(p <- 30) in dst-LE coordinates.

  muxmap1.py [--repo ../Cyclone_CRAM_Mapper]
"""
from __future__ import annotations

import argparse
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "out"))
import lutpos  # noqa: E402

GEO = {"ce6": 210, "c10_016": 255}
MASK = 0x3CEC


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.path.join(HERE, "..", "Cyclone_CRAM_Mapper"))
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.repo, "fuzz"))
    import bitstream
    bitstream._sigma_inv_lookup = lambda *x, **k: (0, 1, 2, 3)
    import mux1_plan

    def phys(dev, x, y, n):
        if dev == "c10_016":
            return lutpos._predict_phys(x, y, n)
        fb = GEO["ce6"]
        pats = bitstream.LutCodec.from_cram_model(x, y, n).patterns
        return [next((((o - 32) // fb, (o - 32) % fb, b) for o, b in pats[i])) for i in range(16)]

    def load(j):
        p = os.path.join(HERE, "out", j.name + ".rbf")
        with open(p, "rb") as f:
            return f.read()

    def perm_of(dev, buf, cells):
        fb = GEO[dev]
        on = {c for c in cells if buf[32 + c[0] * fb + c[1]] >> c[2] & 1}
        hits = [p for p in lutpos.PERMS
                if {cells[lutpos.permute(i, p)] for i in range(16) if MASK >> i & 1} == on]
        return hits[0] if len(hits) == 1 else None

    tables, stats = {}, collections.Counter()
    for dev, (x, y), pins in mux1_plan.LABS:
        fb = GEO[dev]
        T = {}
        for j in mux1_plan.jobs():
            if j.dev != dev or j.loc[:2] != (x, y) or not j.design.endswith(":A"):
                continue
            _, sa, sd, _ = j.design.split(":")
            d = int(sd)
            cells = phys(dev, x, y, d)
            A = load(j)
            B = load(type(j)(j.dev, j.design[:-1] + "B", j.loc, j.pins))
            pa, pb = perm_of(dev, A, cells), perm_of(dev, B, cells)
            if pa is None or pb is None or pa != pb:
                stats[(dev, "input order changed between A and B")] += 1
                continue
            p_in = pa[0]                                    # physical input of logical dataa
            f0 = min(c[0] for c in cells)
            lo = min(c[1] for c in cells)
            bit = cells[0][2]
            odd = (d // 2) % 2
            rel = set()
            for i in range(32, len(A)):
                v = A[i] ^ B[i]
                if not v:
                    continue
                f, pp = divmod(i - 32, fb)
                if pp >= fb - 2:
                    continue
                for b in range(8):
                    if v >> b & 1:
                        dp = pp - lo
                        rel.add((f - f0, (1 - dp) if odd else dp, b - bit))
            T[(int(sa), d)] = (p_in, rel)
            stats[(dev, f"usable, physical input {p_in}")] += 1
        tables[(dev, (x, y))] = T
    for k, v in sorted(stats.items()):
        print(f"  {k[0]}: {k[1]}: {v}")

    keys = list(tables)
    c1, c2, c3 = (tables[k] for k in keys)
    out = collections.defaultdict(list)
    for key in c1:
        if key in c2 and c1[key][0] == c2[key][0]:
            core = c1[key][1] & c2[key][1]
            mux = frozenset(b for b in core if 0 <= b[1] <= 3 and -18 <= b[0] <= -2)
            ce6 = c3.get(key)
            out[(key[0], c1[key][0])].append((key[1], mux, ce6 is not None and ce6[0] == c1[key][0]
                                              and mux <= ce6[1]))
    print("\nper (source slot a, physical input p): dst-relative input-mux core (both 10CL016 LABs),"
          " and whether the EP4CE6 has the same bits")
    for (aa, p), rows in sorted(out.items()):
        pats = collections.Counter(m for _, m, _ in rows)
        top = pats.most_common(1)[0][0]
        print(f"  a={aa:2d} p={p}: {len(rows)} dst(s), {len(pats)} pattern(s): {sorted(top)}"
              f"  CE6 same: {sum(c for _, _, c in rows)}/{len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
