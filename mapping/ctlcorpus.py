#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""LAB control mux codes from normal Quartus builds (M3a): no oracle probes.

The CLRN slot swaps of ctlmap.py put the control mux's line code in frames -12..-2, rows -35..-28 relative to LE N0
(die-wide, two-level like the LUT-input muxes), rows no LUT-input mux uses.  So every build whose back-annotated .rcf
has a hop LAB line k -> LAB_CONTROL_MUX slot j gives that code: the set cells of that band in its LAB.  ffe2:KIND:F
builds give two per build (the control C, and the pin clock B through slot 1).  Kinds ena (slots 2/3) and aclr
(slots 0..3) at many LABs, so Quartus's own choice of line varies.
Output (derived facts only): out/ctlcorpus.json {"job": [[k, j, [[frame, row], ...]], ...]}

  ctlcorpus.py [N_POSITIONS]          (NPAR parallel builds, default 8)
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import random
import re
import sys
import threading

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import lutpos  # noqa: E402
import rcfforce as F  # noqa: E402
import routegraph as G  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcfctl")
NPAR = int(os.environ.get("NPAR", "8"))
RES = os.path.join(OUT, "ctlcorpus.json")
BAND_F, BAND_R = range(-12, -1), range(-35, -27)


def anchor(x, y):
    c0 = lutpos._predict_phys(x, y, 0)
    return min(v[0] for v in c0), min(v[1] for v in c0) + lutpos.PLANE_START[c0[0][2]]


def one(job):
    pr = F.Project(job, ROOT)
    buf = pr.base_rbf
    rows = []
    for _sig, bl in F.branches(pr.base_rcf).items():
        for path, _d in bl:
            for u, v in zip(path, path[1:]):
                mu = re.match(r"LOCAL_INTERCONNECT_X(\d+)_Y(\d+)_N0_I(\d+)$", u)
                mv = re.match(r"LAB_CONTROL_MUX_X(\d+)_Y(\d+)_N0_I(\d+)$", v)
                if not mu or not mv or mu.groups()[:2] != mv.groups()[:2]:
                    continue
                x, y, k, j = int(mu[1]), int(mu[2]), int(mu[3]), int(mv[3])
                f0, l0 = anchor(x, y)
                cells = sorted((f, r) for f in BAND_F for r in BAND_R
                               if (c := G.cell_of(f0 + f, l0 + r)) and buf[32 + c[0] * 255 + c[1]] >> c[2] & 1)
                rows.append([k, j, [list(c) for c in cells]])
    return job.name, sorted({json.dumps(r): r for r in rows}.values(), key=lambda r: (r[0], r[1]))


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    labs = [(x, y) for x in range(1, 41) for y in range(2, 28) if x not in (13, 18, 25, 34)]
    random.Random(7).shuffle(labs)
    jobs = [xdev.Job("c10_016", f"ffe2:{kind}:F", (x, y, 0), "vidor") for x, y in labs[:n] for kind in ("ena", "aclr")]
    jobs = [j for j in jobs if j.name not in res]
    lock = threading.Lock()

    def work(job):
        try:
            name, rows = one(job)
        except (SystemExit, Exception) as e:          # a build that fails at an edge position: skip it
            print(f"{job.name}: {e}", flush=True)
            return
        with lock:
            res[name] = rows
            json.dump(res, open(RES, "w"), indent=0)
        print(f"{name}: {[(k, j, len(c)) for k, j, c in rows]}", flush=True)
    with cf.ThreadPoolExecutor(NPAR) as ex:
        list(ex.map(work, jobs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
