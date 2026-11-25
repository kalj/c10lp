#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Map driver and LAB-line select switches with the RCF oracle (rcfforce.py) on xrkn builds.

For each net LE_BUFFER b -> wire W -> LAB line L -> LUT of a build:
  1. drivers: which wires W' b can drive (force "b -> W'" alone: an error at hop 2 means the driver exists);
  2. selects: for each legal W' != W, which free lines L' it can enter (force "b -> W' -> L'": honoured or not);
  3. bits: for each honoured route, the XOR with the identity-forced build = bits(old route) + bits(new route).
Results (derived facts only, no .rcf content): out/oracle_map.json
  {job: {net: {"route": [b, W, L, dst], "drivers": [...], "lines": {W': [L', ...]}, "honoured": {"W'|L'": diff}}}}

  oraclemap.py JOB_DESIGN X Y [X Y ...]       e.g. oraclemap.py xrkn:8:-3:0:1 17 8 17 9
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

OUT = os.path.join(HERE, "out", "oracle_map.json")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", os.path.join(HERE, "out")), "tmp", "rcf")
N_WIRES = 48


def map_build(job: xdev.Job, res: dict):
    pr = F.Project(job, ROOT)
    nets = F.nets(pr.base_rcf)
    used = {F.node_name(r) for p in nets.values() for r in p}
    entry = res.setdefault(job.name, {})
    todo = {s: [F.node_name(r) for r in p] for s, p in nets.items()
            if len(p) == 3 and p[0].startswith("LE_BUFFER") and p[2].startswith("LOCAL_INTERCONNECT")}
    wt = lambda n: n.rsplit("_I", 1)[0] + "_I"               # wire name prefix: R4_X14_Y15_N0_I
    # 1. drivers
    probes = [(s, p[1:], [wt(p[1]) + str(i)]) for s, p in todo.items() for i in range(N_WIRES)]
    for (s, old, new), ok, msg, _ in F.scan(pr, probes):
        e = entry.setdefault(s, {"route": todo[s], "drivers": [], "lines": {}, "honoured": {}})
        if msg == "rcf error at hop 2":
            e["drivers"].append(new[0])
    # 2 + 3. lines and bits for alternative wires
    probes = []
    for s, p in todo.items():
        lab = p[2].rsplit("_I", 1)[0] + "_I"
        for w in entry[s]["drivers"]:
            if w == p[1] or w in used:
                continue
            probes += [(s, p[1:], [w, lab + str(li)]) for li in range(38) if lab + str(li) not in used]
    for (s, old, new), ok, msg, diff in F.scan(pr, probes, want_bits=True):
        if ok:
            entry[s]["lines"].setdefault(new[0], []).append(new[1])
            entry[s]["honoured"][f"{new[0]}|{new[1]}"] = [list(c) for c in diff]
    return entry


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    design, xs = sys.argv[1], list(map(int, sys.argv[2:]))
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for x, y in zip(xs[::2], xs[1::2]):
        job = xdev.Job("c10_016", design, (x, y, 0), "vidor")
        if job.name in res:
            continue
        t0 = time.time()
        e = map_build(job, res)
        json.dump(res, open(OUT, "w"), indent=0)
        nh = sum(len(v["honoured"]) for v in e.values())
        print(f"{job.name}: {len(e)} nets, {sum(len(v['drivers']) for v in e.values())} drivers, {nh} honoured routes, "
              f"{time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
