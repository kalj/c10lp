#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Complete R4 driver legality per buffer and phase, with the RCF oracle (offset -3: left-going wires starting 3
columns left of the buffer; --offset 1: right-going wires starting one column right).

Builds xrkn:8:-3:0:SEED at (X, Y) for seeds 1 and 2730 (their 8 source slots together cover all 16 LEs) and, for
each net, forces "LE_BUFFER b' -> R4_X(X-3)_Y_I w" with b' in {N, N+1} (the two buffers of source slot N) and
w in 0..47.  Hop of the reported error: 0 = the LE can't use buffer b', 1 = b' can't drive w, 2 = legal driver.
Output: out/drvmap.json {"X17Y8": {"phase": (X+Y)%4, "buffers": {b: {"usable": bool, "legal": [w, ...]}}}}

  drvmap.py X Y [X Y ...] [--offset -3|1]     (offset 1 builds xrkn:8:+3 and writes out/drvmap_p1.json)
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import rcfforce as F  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out", "drvmap.json")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", os.path.join(HERE, "out")), "tmp", "rcf")
SEEDS = (1, 2730)


def main() -> int:
    global OUT
    args = sys.argv[1:]
    off = -3
    if "--offset" in args:
        i = args.index("--offset")
        off = int(args[i + 1])
        del args[i:i + 2]
    if off != -3:
        OUT = OUT.replace("drvmap.json", f"drvmap_{'p' if off > 0 else 'm'}{abs(off)}.json")
    span = -3 if off < 0 else 3                         # sink 3 columns left (offset -3) or right (offset +1)
    xs = list(map(int, args))
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for X, Y in zip(xs[::2], xs[1::2]):
        key = f"X{X}Y{Y}"
        e = res.setdefault(key, {"phase": (X + Y) % 4, "buffers": {}, "done_seeds": []})
        for seed in SEEDS:
            if seed in e["done_seeds"]:
                continue
            t0 = time.time()
            pr = F.Project(xdev.Job("c10_016", f"xrkn:8:{span}:0:{seed}", (X, Y, 0), "vidor"), ROOT)
            probes = []
            for s, p in F.nets(pr.base_rcf).items():
                if len(p) >= 2 and p[0].startswith(f"LE_BUFFER:X{X}Y{Y}") and (off != -3 or len(p) == 3 and
                                                                                 p[1].startswith(f"R4:X{X - 3}")):
                    path = [F.node_name(r) for r in p]
                    bq = int(path[0].rsplit("_I", 1)[1])
                    for bb in (bq - bq % 2, bq - bq % 2 + 1):
                        probes += [(s, path, [f"LE_BUFFER_X{X}_Y{Y}_N0_I{bb}", f"R4_X{X + off}_Y{Y}_N0_I{w}"])
                                   for w in range(48)]
            for (s, old, new), ok, msg, _ in F.scan(pr, probes):
                bb = new[0].rsplit("_I", 1)[1]
                d = e["buffers"].setdefault(bb, {"usable": False, "legal": []})
                if msg in ("rcf error at hop 1", "rcf error at hop 2"):
                    d["usable"] = True
                if msg == "rcf error at hop 2":
                    d["legal"] = sorted(set(d["legal"]) | {int(new[1].rsplit("_I", 1)[1])})
            e["done_seeds"].append(seed)
            json.dump(res, open(OUT, "w"), indent=0)
            print(f"{key} seed {seed}: {len(probes)} probes, {time.time() - t0:.0f}s; buffers so far "
                  f"{len(e['buffers'])}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
