#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Predict which single-input rewires work, from where Quartus shares a local source (mux4d).

Rule: an LE's local line reaches exactly two of a LUT's physical inputs directly
(the pairs Quartus uses when two inputs share that source).  A rewire of input p
to source s works iff p is one of s's two direct inputs AND s's local line is
driven in the base, i.e. the input that already selects s is one of its direct
inputs too.  Checked against every rewire.py log.

  lirule.py
"""
from __future__ import annotations

import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
sys.path.insert(0, os.path.join(HERE, "out"))
import mux1cmap  # noqa: E402
import rewire as R  # noqa: E402
import xdev  # noqa: E402


def direct_inputs() -> dict[int, set]:
    import mux4d_plan
    direct = collections.defaultdict(set)
    for j in mux4d_plan.jobs():
        _, sd, srcs = j.design.split(":")
        d, s0 = int(sd), int(srcs.split("-")[0])
        x, y, _ = j.loc
        perm = mux1cmap.perm_of(xdev.load(os.path.join(HERE, "out"), j.name), x, y, d)
        if perm:
            direct[s0] |= {perm[0], perm[1]}
    return dict(direct)


def predict(direct: dict, cur: dict, rewires: dict) -> bool:
    """True if every rewire (physical input -> source) is predicted to work, given the base's
    current assignment cur (physical input -> source slot)."""
    for p, s in rewires.items():
        if p not in direct.get(s, ()):
            return False
        if not any(q in direct[s] for q, v in cur.items() if v == s):
            return False                                  # s's local line isn't driven
    return True


def load_direct() -> dict[int, set]:
    return {int(k): set(v) for k, v in json.load(open(os.path.join(HERE, "data", "li_direct.json"))).items()}


def main() -> int:
    direct = direct_inputs()
    print("direct inputs per source slot:", {s: sorted(v) for s, v in sorted(direct.items())})
    json.dump({str(s): sorted(v) for s, v in sorted(direct.items())},
              open(os.path.join(HERE, "data", "li_direct.json"), "w"), indent=1)
    hit = tot = unknown = 0
    for f in sorted(glob.glob(os.path.join(HERE, "out", "rewire_*.jsonl"))):
        tag = os.path.basename(f)[len("rewire_"):]
        R.SRCS = [int(v) for v in tag.split("_")[0].split("-")] if tag[0].isdigit() and "-" in tag.split("_")[0] \
            else [0, 4, 8, 12]
        base = xdev.load(R.OUT, R.base_name())
        dst = R.Dst(base)
        cur = {dst.perm[i]: R.SRCS[i] for i in range(4)}
        for line in open(f):
            r = json.loads(line)
            rw = {int(k): v for k, v in r["rewires"].items()}
            if not rw:
                continue
            final = dict(cur)
            final.update(rw)
            ok_pred = True
            for p, s in rw.items():
                if s not in direct:
                    ok_pred = None
                    break
                holders = [q for q, v in final.items() if v == s and q != p]
                driven = any(q in direct[s] for q in holders) or p in direct[s]
                ok_pred = ok_pred and p in direct[s] and driven and \
                    any(q in direct[s] for q, v in cur.items() if v == s)
            if ok_pred is None:
                unknown += 1
                continue
            tot += 1
            hit += ok_pred == (not r["wrong"])
            if ok_pred != (not r["wrong"]):
                print(f"  mispredicted: {tag} {r['file']}")
    print(f"rule predicts {hit}/{tot} rewire outcomes ({unknown} involve sources without sharing data)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
