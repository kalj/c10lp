#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Intra-LAB local-line input-mux encoding, from xdev design "mux" (data only).

Build pairs (sel A / sel B) differ only in which source drives all four inputs
of dst at slot d: srcA at slot a, or the fixed srcB at slot 30.  So
    S(a, d) = diff(A, B) = M(d <- a) XOR M(d <- 30)
where M(d <- s) is the set of mux-select bits that make dst's inputs pick
slot s's local line.  M(d <- 30) = what all S(a, d) share; M(d <- a) = the rest.

Bits are in dst-LE coordinates: (frame - first LUT frame of dst, byte - dst's
low LUT byte), mirrored for odd LEs (like the LUT byte swap), in dst's bit plane.

  muxmap.py [--repo ../Cyclone_CRAM_Mapper]
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.path.join(HERE, "..", "Cyclone_CRAM_Mapper"))
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.repo, "fuzz"))
    import bitstream
    bitstream._sigma_inv_lookup = lambda *x, **k: (0, 1, 2, 3)
    import mux_plan

    def anchor(dev, x, y, n):
        if dev == "c10_016":
            lc = lutpos._predict_phys(x, y, n)
        else:
            fb = GEO["ce6"]
            pats = bitstream.LutCodec.from_cram_model(x, y, n).patterns
            lc = [((o - 32) // fb, (o - 32) % fb, b) for c in pats.values() for o, b in c]
        return min(f for f, _, _ in lc), min(p for _, p, _ in lc), lc[0][2]

    def load(j):
        p = os.path.join(HERE, "out", j.name + ".rbf")
        if not os.path.exists(p):
            return None
        with open(p, "rb") as f:
            return f.read()

    tables = {}
    for dev, (x, y), pins in mux_plan.LABS:
        fb = GEO[dev]
        S = {}
        for j in mux_plan.jobs():
            if j.dev != dev or j.loc[:2] != (x, y) or not j.design.endswith(":A"):
                continue
            _, sa, sd, _ = j.design.split(":")
            A = load(j)
            B = load(type(j)(j.dev, j.design[:-1] + "B", j.loc, j.pins))
            if A is None or B is None:
                continue
            f0, lo, bit = anchor(dev, x, y, int(sd))
            odd = (int(sd) // 2) % 2
            rel = set()
            for i in range(len(A)):
                d = A[i] ^ B[i]
                if not d or i < 32:
                    continue
                f, p = divmod(i - 32, fb)
                if p >= fb - 2:
                    continue                                  # frame CRC
                for b in range(8):
                    if d >> b & 1:
                        dp = p - lo
                        rel.add((f - f0, (1 - dp) if odd else dp, b - bit))
            S[(int(sa), int(sd))] = rel
        M = {}
        for d in sorted({k[1] for k in S}):
            row = {aa: v for (aa, dd), v in S.items() if dd == d}
            ref = set.intersection(*row.values())
            M[("ref30", d)] = ref
            for aa, v in row.items():
                M[(aa, d)] = v - ref
        tables[(dev, (x, y))] = (S, M)
        sizes = collections.Counter(len(v) for k, v in M.items() if k[0] != "ref30")
        print(f"{dev} X{x}Y{y}: {len(S)} (a, d) pairs; |M(d<-a)| distribution {dict(sorted(sizes.items()))}; "
              f"|M(d<-30)| per d {sorted({len(v) for k, v in M.items() if k[0] == 'ref30'})}")

    keys = list(tables)
    for i in range(len(keys)):
        for k in range(i + 1, len(keys)):
            Ma, Mb = tables[keys[i]][1], tables[keys[k]][1]
            common = set(Ma) & set(Mb)
            same = sum(Ma[c] == Mb[c] for c in common)
            print(f"  {keys[i][0]} X{keys[i][1][0]}Y{keys[i][1][1]} vs {keys[k][0]} X{keys[k][1][0]}Y{keys[k][1][1]}: "
                  f"{same}/{len(common)} mux entries identical in dst-LE coordinates")

    # Structure: does M(d <- a) depend on a only (the source line), shifted with d?
    S, M = tables[keys[0]]
    by_a = collections.defaultdict(set)
    for (aa, d), v in M.items():
        if aa != "ref30":
            by_a[aa].add(frozenset(v))
    print(f"  {keys[0][0]}: distinct dst-relative patterns per source slot: "
          + ", ".join(f"a={aa}:{len(v)}" for aa, v in sorted(by_a.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
