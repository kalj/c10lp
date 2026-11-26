#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""C4 driver legality per (buffer, wire, dx, dy, (X+Y) mod 4), with the batched RCF oracle (drvmap.py for C4).

On vertical-span builds (xrkn:8:0:+4 at (X, Y)), each net's route is forced to "the source LE's buffer b -> C4 w" (the
rest of the route dropped) for b in its two buffers, w in 0..23 and the four driver offsets the corpus shows (wire
column X or X - 1; start row Y + 1 or Y - 4).  Hop of the RCF error: 1 = b can't drive w, 2 = the driver exists (w
just can't reach the old destination).  8 probes per fit.
Output: out/c4drvmap.json {"X8Y3": {"phase": p, "legal": ["b|w|dx|dy", ...], "done": [...]}}

  c4drvmap.py X Y [X Y ...]          (NPAR parallel fits)
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import rcfforce as F  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out", "c4drvmap.json")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", os.path.join(HERE, "out")), "tmp", "rcfc4d")
NPAR = int(os.environ.get("NPAR", "8"))
OFFSETS = [(0, 1), (-1, 1), (0, -4), (-1, -4)]
SEEDS = (11, 2731)                      # their 8 source slots together cover most of the 16 LEs


def main() -> int:
    xs = list(map(int, sys.argv[1:]))
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for X, Y in zip(xs[::2], xs[1::2]):
        key = f"X{X}Y{Y}"
        e = res.setdefault(key, {"phase": (X + Y) % 4, "legal": [], "done": []})
        for seed in SEEDS:
            if seed in e["done"]:
                continue
            t0 = time.time()
            pr = F.Project(xdev.Job("c10_016", f"xrkn:8:0:4:{seed}", (X, Y, 0), "vidor"), ROOT)
            probes, meta = [], []
            for s, p in F.nets(pr.base_rcf).items():
                path = [F.node_name(r) for r in p]
                if len(path) < 2 or not path[0].startswith(f"LE_BUFFER_X{X}_Y{Y}_"):
                    continue
                bq = int(path[0].rsplit("_I", 1)[1])
                for bb in (bq - bq % 2, bq - bq % 2 + 1):
                    for dx, dy in OFFSETS:
                        if Y + dy < 0 or X + dx < 0:
                            continue                    # off the die (from row 3, a wire starting at row -1)
                        for w in range(24):
                            probes.append((s, path, [f"LE_BUFFER_X{X}_Y{Y}_N0_I{bb}", f"C4_X{X + dx}_Y{Y + dy}_N0_I{w}"]))
                            meta.append(f"{bb}|{w}|{dx}|{dy}")
            legal = set(e["legal"])
            for (pb, ok, msg, _c), k in zip(F.scan_batched(pr, probes, workers=NPAR), meta):
                if msg == "rcf error at hop 2" or ok:
                    legal.add(k)
            e["legal"] = sorted(legal)
            e["done"].append(seed)
            json.dump(res, open(OUT, "w"), indent=0)
            print(f"{key} seed {seed}: {len(probes)} probes, {len(legal)} legal drivers so far, {time.time() - t0:.0f}s",
                  flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
