#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""R4 -> LAB-line selects at chosen taps: force the wire as well as the line, with the RCF oracle.

tapmap.py only measures wires Quartus happens to choose, and that stopped adding keys (round 5: 283 builds, 3 held-out
hops).  Here the route of each net of an xrkn:8 build is replaced by "the source LE's buffer b -> R4 w -> line L' of
the sink LAB" for every R4 w that b drives (switchmodel's buffer -> R4 drivers: left-going wires starting 3 columns
left of the source) and every line L' of the sink LAB unused in the build.  The sink LAB lies (source - sink) columns
left, so the build's span picks the tap offset: off = sink - (source - 3) = 3 - span.  (Key, line) pairs already probed
(tapmap.json, tapforce.json; key = (wire index, offset, sink X mod 8)) are skipped.
Outcome per probe (hop of the RCF error): 1 = no driver, 2 = no select, 3 = select, LUT port unreachable,
honoured = exact bits (the diff also clears the old route; only set cells in the sink LAB's select band are kept).
Output (derived facts only): out/tapforce.json, same format as tapmap.json.

  tapforce.py SPAN [SPAN ...] [--per-span N] [--seed S]   (SPAN = source - sink columns, e.g. 1 2 3 4; the seed picks
                                                          the positions; NPAR parallel fits)
"""
from __future__ import annotations

import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the repo root
sys.path[:0] = [os.path.join(HERE, d) for d in ("lib", "flow", "mapping", "hwtests")]
import rcfforce as F  # noqa: E402
import routemap as R  # noqa: E402
import switchmodel as S  # noqa: E402
import xdev  # noqa: E402

OUT = os.path.join(HERE, "out")
ROOT = os.path.join(os.environ.get("CLAUDE_JOB_DIR", OUT), "tmp", "rcftapf")
NPAR = int(os.environ.get("NPAR", "8"))
RES = os.path.join(OUT, "tapforce.json")


def tapkey(w: str, L: str):
    wx, wi = int(w.split("_X")[1].split("_")[0]), int(w.rsplit("_I", 1)[1])
    lx = int(L.split("_X")[1].split("_")[0])
    return wi, lx - wx, lx % 8


def main() -> int:
    args = sys.argv[1:]
    per, seed = 8, 2525
    for opt in ("--per-span", "--seed"):
        if opt in args:
            i = args.index(opt)
            if opt == "--per-span":
                per = int(args[i + 1])
            else:
                seed = int(args[i + 1])
            del args[i:i + 2]
    spans = [int(a) for a in args]
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    done = set()
    for f in (os.path.join(OUT, "tapmap.json"), RES):
        for out in (json.load(open(f)).values() if os.path.exists(f) else []):
            done |= {tapkey(*k.split("|")) + (int(k.rsplit("_I", 1)[1]),) for k in out}   # per (key, line)
    m = S.Model()
    cols = sorted(x for x in range(1, 41) if R._col_frame(x) is not None)
    rnd = random.Random(seed)
    jobs = []
    for span in spans:
        k = 0
        while k < per:
            X, Y = rnd.choice(cols), rnd.randint(2, 22)          # X = sink column
            if X + span not in cols or not 1 <= X + span <= 40:
                continue
            jobs.append(xdev.Job("c10_016", f"xrkn:8:{-span}:0:{rnd.randint(100, 999)}", (X + span, Y, 0), "vidor"))
            k += 1
    for job in jobs:
        if job.name in res:
            continue
        t0 = time.time()
        try:
            pr = F.Project(job, ROOT)
        except SystemExit as e:
            print(f"{job.name}: {e}", flush=True)
            continue
        nets = F.nets(pr.base_rcf)
        used = {F.node_name(r) for p in nets.values() for r in p}
        probes, keys = [], set()
        for s, p in nets.items():
            path = [F.node_name(r) for r in p]
            if not path or not path[0].startswith("LE_BUFFER") or not path[-1].startswith("LOCAL_INTERCONNECT"):
                continue
            sink = path[-1].rsplit("_I", 1)[0] + "_I"
            bq = int(path[0].rsplit("_I", 1)[1])
            sx, sy = path[0].split("_X")[1].split("_N")[0].split("_Y")
            for bb in (bq - bq % 2, bq - bq % 2 + 1):
                b = f"LE_BUFFER_X{sx}_Y{sy}_N0_I{bb}"
                for w, _bits in m.fanout(b):
                    if not w.startswith("R4_") or w in used:
                        continue
                    for li in range(38):
                        L = sink + str(li)
                        k = tapkey(w, L) + (li,)
                        if k in done or L in used:
                            continue
                        keys.add(k)
                        probes.append((s, path, [b, w, L]))
        out = {}
        for (s, old, new), ok, msg, diff in F.scan(pr, probes, workers=NPAR, want_bits=True):
            st = "honoured" if ok else {"rcf error at hop 1": "no driver", "rcf error at hop 2": "no select",
                                        "rcf error at hop 3": "select, port unreachable"}.get(msg, msg)
            out[f"{new[1]}|{new[2]}"] = {"status": st, "bits": [list(c) for c in diff] if ok else None}
        res[job.name] = out
        done |= keys
        json.dump(res, open(RES, "w"), indent=0)
        st = {x: sum(1 for v in out.values() if v["status"] == x) for x in ("honoured", "no select", "no driver")}
        print(f"{job.name[-36:]}: {len(keys)} new (key, line) pairs, {len(probes)} probes, {st}, {time.time() - t0:.0f}s",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
