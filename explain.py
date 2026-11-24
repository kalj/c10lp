#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""How much of a design's bitstream can our models produce?  A coverage metric toward a Quartus-free flow.

Diffs a Quartus build of a design against the all-zero design (out/lo_quartus_0000.rbf, same pin set) and
sorts every differing core bit into
  lut        a LUT cell of a placed LE (lutpos)
  le-local   frames -12..+12 of a placed LE's LAB at that LE's rows: input-mux codes, output selects, FF
             controls (modelled by tpatch / mux maps / ff_control, not re-derived here)
  routing    a bit of a routing hop of the design's own .rcf, as predicted by switchmodel / the LUT-input keys
  other      anything else: unmodelled routing, clocks, I/O tiles, ...
plus the periphery bits (frames 1..36) separately.  For routing, it also reports hops the model can't price.

  explain.py tpl NAME            a tpatch template (e.g. div24)
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
import rcfforce as F  # noqa: E402
import reroute  # noqa: E402
import routegraph as G  # noqa: E402
import routemap as R  # noqa: E402
import switchmodel as S  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcf")


def core_diff(a: bytes, b: bytes):
    out = set()
    for i in range(32 + 37 * 255, min(len(a), len(b))):
        x = a[i] ^ b[i]
        if x:
            f, p = divmod(i - 32, 255)
            if p < 253:
                out |= {(f, p, k) for k in range(8) if x >> k & 1}
    return out


def periph_diff(a: bytes, b: bytes) -> int:
    return sum(bin(a[i] ^ b[i]).count("1") for i in range(32 + 255, 32 + 37 * 255))


def rcf_hops(rcf: str):
    """Routing hops (from node, to node) of every branch of every net in a back-annotated .rcf (LUT-input hops,
    the last resource -> the destination port, are left to the LE-local category)."""
    hops = set()
    for brs in F.branches(rcf).values():
        for path, _dest in brs:
            hops |= set(zip(path, path[1:]))
    return sorted(hops)


def explain(job: xdev.Job, placed: dict):
    pr = F.Project(job, ROOT)
    zero = open(os.path.join(OUT, "lo_quartus_0000.rbf"), "rb").read()
    D = core_diff(zero, pr.base_rbf)
    lut = {c for (x, y, n) in placed.values() for c in lutpos._predict_phys(x, y, n)}
    local = set()
    for (x, y, n) in placed.values():
        c = lutpos._predict_phys(x, y, n)
        f0, lo, hi = R._col_frame(x), min(v[1] for v in c), max(v[1] for v in c)
        local |= {(f0 + df, p, b) for df in range(-12, 13) for p in range(lo - 2, hi + 3) for b in range(8)}
    m, g = S.Model(), G.Graph(min_inst=20)
    pred, priced, unpriced = set(), 0, collections.Counter()
    for u, v in rcf_hops(pr.base_rcf):
        b = m.bits(u, v)
        if b is not None:                                  # (an empty list: a priced hop with no bits)
            pred |= set(b)
            priced += 1
        else:
            unpriced[(u.split("_X")[0], v.split("_X")[0])] += 1
    # fixed path bundles measured for a placement (e.g. the output path LE X10Y3N30 -> D5: out/outpath_bits.json)
    bp = os.path.join(OUT, "outpath_bits.json")
    bundle = {tuple(c) for c in json.load(open(bp))} if os.path.exists(bp) else set()
    cats = collections.Counter()
    other = []
    for c in D:
        k = ("lut" if c in lut else "routing (model)" if c in pred else "le-local" if c in local
             else "output path (bundle)" if c in bundle else "other")
        cats[k] += 1
        if k == "other":
            other.append(c)
    explain.other = sorted(other)
    return D, cats, priced, unpriced, periph_diff(zero, pr.base_rbf), len(pred - D)


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "tpl":
        print(__doc__)
        return 2
    import tpatch
    name = sys.argv[2]
    job = tpatch.job(name, [mk for _, mk in xdev.tpl_luts(name)])
    t = tpatch.Template(name, partial=True)
    D, cats, priced, unpriced, nper, wrong = explain(job, t.les)
    print(f"{name}: {len(D)} core bits differ from the all-zero design; periphery bits differ: {nper}")
    for k in ("lut", "le-local", "routing (model)", "output path (bundle)", "other"):
        print(f"  {k:16s} {cats[k]:5d}  {100 * cats[k] / len(D):5.1f}%")
    print(f"  routing hops priced by the model: {priced}; predicted bits not in the design: {wrong}")
    print(f"  unpriced hop types: {dict(unpriced.most_common(8))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
