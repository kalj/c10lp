#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Neighbour-link driver bits per (buffer, dx, line), with the batched RCF oracle.

li_neighbour.json gives one source-side pattern per slot, but the driver moves with the line (buffer I14 -> X10
line 21 in the nextpnr-routed blinky: (16, 0)/(18, 0) of the source LE, not the slot table's (19, -2)/(21, -1)),
and the corpus has too few uses of these hops to learn them (49 over 26 keys).  On xrkn:8:+-1 builds (sinks in the
next LAB), each net's route is forced to "source buffer b -> line L of the sink LAB" for every (b, dx, L) known
legal (router.seen_neighbour_pairs); an honoured route's set cells in frames +13..+22 of the source LAB, within 4
bytes of the source LE's low byte on its plane, are the driver.
Output: out/nbdrv.json {"b|dx|line": [[frame, byte offset], ...]} (frame relative to the LAB's slot-0 LUT frame,
byte relative to the source LE's low byte), used by switchmodel.Model._neighbour.

  nbmap.py [N_BUILDS_PER_DIRECTION]        (NPAR parallel fits)
"""
from __future__ import annotations

import collections
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping")]
import lutpos  # noqa: E402
import rcfforce as F  # noqa: E402
import routemap as R  # noqa: E402
import router  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcfnb")
NPAR = int(os.environ.get("NPAR", "8"))
RES = os.path.join(OUT, "nbmap.json")


def main() -> int:
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    seen = router.seen_neighbour_pairs()
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    cols = sorted(x for x in range(1, 41) if R._col_frame(x) is not None)
    rnd = random.Random(2650)
    jobs = []
    for dx in (1, -1):
        k = 0
        while k < per:
            X, Y = rnd.choice(cols), rnd.randint(2, 22)             # source
            if X + dx not in cols:
                continue
            jobs.append(xdev.Job("c10_016", f"xrkn:8:{dx}:0:{rnd.randint(100, 999)}", (X, Y, 0), "vidor"))
            k += 1
    done = {k for out in res.values() for k in out}
    for job in jobs:
        if job.name in res:
            continue
        t0 = time.time()
        try:
            pr = F.Project(job, ROOT)
        except SystemExit as e:
            print(f"{job.name}: {e}", flush=True)
            continue
        probes = []
        for s, p in F.nets(pr.base_rcf).items():
            path = [F.node_name(r) for r in p]
            if not path or not path[0].startswith("LE_BUFFER") or not path[-1].startswith("LOCAL_INTERCONNECT"):
                continue
            sx, sy = map(int, path[0].split("_X")[1].split("_N")[0].split("_Y"))
            dxx = int(path[-1].split("_X")[1].split("_")[0]) - sx
            if abs(dxx) != 1:
                continue
            bq = int(path[0].rsplit("_I", 1)[1])
            sink = path[-1].rsplit("_I", 1)[0] + "_I"
            l0 = int(path[-1].rsplit("_I", 1)[1])
            for bb in (bq - bq % 2, bq - bq % 2 + 1):
                for (b, d, li) in sorted(seen):
                    key = f"{bb}|{dxx}|{li}"
                    if b != bb or d != dxx or key in done or (bb, li) == (bq, l0):
                        continue                        # the identity probe changes nothing
                    done.add(key)
                    probes.append((s, path, [f"LE_BUFFER_X{sx}_Y{sy}_N0_I{bb}", sink + str(li)]))
        out = {}
        for (s, old, new), ok, msg, diff in F.scan_batched(pr, probes, workers=NPAR, want_bits=True):
            b = int(new[0].rsplit("_I", 1)[1])
            sx, sy = map(int, new[0].split("_X")[1].split("_N")[0].split("_Y"))
            li = int(new[1].rsplit("_I", 1)[1])
            dxx = int(new[1].split("_X")[1].split("_")[0]) - sx
            cells = None
            if ok and diff:
                c0 = lutpos._predict_phys(sx, sy, b - b % 2)
                f0 = min(v[0] for v in lutpos._predict_phys(sx, sy, 0))
                lo, bit = min(v[1] for v in c0), c0[0][2]
                cells = sorted((f - f0, p - lo) for f, p, pl, v in diff
                               if v == 1 and pl == bit and 13 <= f - f0 <= 22 and abs(p - lo) <= 4)
                # the cleared cells are the original link's driver (the net's own route), on its own LE's row
                ob = int(old[0].rsplit("_I", 1)[1])
                oc = lutpos._predict_phys(sx, sy, ob - ob % 2)
                olo = min(v[1] for v in oc)
                ocells = sorted((f - f0, p - olo) for f, p, pl, v in diff
                                if v == 0 and pl == oc[0][2] and 13 <= f - f0 <= 22 and abs(p - olo) <= 4)
                ok_key = f"{ob}|{dxx}|{int(old[-1].rsplit('_I', 1)[1])}"
                if ocells:
                    out.setdefault(ok_key, {"status": "original (cleared)", "cells": ocells})
            out[f"{b}|{dxx}|{li}"] = {"status": "honoured" if ok else msg, "cells": cells}
        res[job.name] = out
        json.dump(res, open(RES, "w"), indent=0)
        print(f"{job.name[-34:]}: {len(probes)} probes, {sum(1 for v in out.values() if v['status'] == 'honoured')} "
              f"honoured, {time.time() - t0:.0f}s", flush=True)
    model = {}
    for out in res.values():
        for k, v in out.items():
            if v["status"] in ("honoured", "original (cleared)") and v["cells"]:
                model.setdefault(k, v["cells"])
    json.dump(model, open(os.path.join(OUT, "nbdrv.json"), "w"), indent=0)
    print(f"{len(model)} of {len(seen)} known neighbour pairs with driver bits -> out/nbdrv.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
