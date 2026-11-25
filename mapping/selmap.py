#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Map R4 -> LAB-line selects with the RCF oracle, one destination LAB per column class (X mod 8).

On xrkn:8:-3:0:SEED builds (seeds 1, 2730) with destination LAB (X, Y): for every R4 wire W' that some source LE
can drive (driver model, switchmodel.Model) and every LAB line L' unused in the build, force
"LE_BUFFER b' -> W' -> L' -> (the net's LUT port)".  Hop of the error: 1 = no such driver, 2 = W' can't enter L',
3 = L' can't reach that LUT port (the select exists; bits not measured); honoured = exact bits of the route.
Output (derived facts only): out/selmap.json
  {"X14Y10": {"class": X % 8, "W|L": {"status": ..., "bits": [[frame, byte, plane, value], ...]}}}

  selmap.py DST_X DST_Y [DST_X DST_Y ...]
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import rcfforce as F  # noqa: E402
import switchmodel as S  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out", "selmap.json")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", os.path.join(HERE, "out")), "tmp", "rcf")
SEEDS = (1, 2730)


def main() -> int:
    xs = list(map(int, sys.argv[1:]))
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    m = S.Model()
    for X, Y in zip(xs[::2], xs[1::2]):
        key = f"X{X}Y{Y}"
        e = res.setdefault(key, {"class": X % 8, "done_seeds": [], "pairs": {}})
        for seed in SEEDS:
            if seed in e["done_seeds"]:
                continue
            t0 = time.time()
            pr = F.Project(xdev.Job("c10_016", f"xrkn:8:-3:0:{seed}", (X + 3, Y, 0), "vidor"), ROOT)
            nets = F.nets(pr.base_rcf)
            used = {F.node_name(r) for p in nets.values() for r in p}
            lab = f"LOCAL_INTERCONNECT_X{X}_Y{Y}_N0_I"
            probes, seen = [], set(e["pairs"])
            for s, p in nets.items():
                if not (len(p) == 3 and p[0].startswith("LE_BUFFER") and p[1].startswith(f"R4:X{X}Y")):
                    continue
                path = [F.node_name(r) for r in p]
                bq = int(path[0].rsplit("_I", 1)[1])
                for bb in (bq - bq % 2, bq - bq % 2 + 1):
                    b = f"LE_BUFFER_X{X + 3}_Y{Y}_N0_I{bb}"
                    for w, _bits in m.fanout(b):
                        if not w.startswith(f"R4_X{X}_Y{Y}_") or w in used:
                            continue
                        for li in range(38):
                            L = lab + str(li)
                            k = f"{w}|{L}"
                            if L in used or k in seen:
                                continue
                            seen.add(k)
                            probes.append((s, path, [b, w, L]))
            n_h = 0
            for (s, old, new), ok, msg, diff in F.scan(pr, probes, want_bits=True):
                st = "honoured" if ok else {"rcf error at hop 1": "no driver", "rcf error at hop 2": "no select",
                                            "rcf error at hop 3": "select, port unreachable"}.get(msg, msg)
                e["pairs"][f"{new[1]}|{new[2]}"] = {"status": st, "bits": [list(c) for c in diff] if ok else None}
                n_h += ok
            e["done_seeds"].append(seed)
            json.dump(res, open(OUT, "w"), indent=0)
            print(f"{key} seed {seed}: {len(probes)} probes, {n_h} honoured, {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
